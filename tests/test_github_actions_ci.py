import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED_ENVIRONMENT = {
    "KSA_DEBUG",
    "KSA_SECRET_KEY",
    "KSA_ALLOWED_HOSTS",
    "KSA_DATABASE_ENGINE",
    "KSA_DB_NAME",
    "KSA_DB_USER",
    "KSA_DB_PASSWORD",
    "KSA_DB_HOST",
    "KSA_DB_PORT",
    "KSA_REDIS_URL",
    "KSA_CELERY_BROKER_URL",
    "KSA_CELERY_RESULT_BACKEND",
    "KSA_GOOGLE_OAUTH_CLIENT_ID",
    "KSA_GOOGLE_OAUTH_CLIENT_SECRET",
}


def workflow_text():
    assert WORKFLOW.exists(), "CI workflow must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def test_ci_runs_on_pushes_and_pull_requests_to_main():
    text = workflow_text()

    assert re.search(r"(?m)^on:\s*$", text)
    assert re.search(r"(?m)^  push:\s*$", text)
    assert re.search(r"(?m)^  pull_request:\s*$", text)
    assert text.count("branches: [main]") == 2
    assert "pull_request_target" not in text


def test_ci_has_read_only_repository_permissions_and_concurrency_guard():
    text = workflow_text()

    assert re.search(r"(?m)^permissions:\s*\n  contents: read\s*$", text)
    assert re.search(r"(?m)^concurrency:\s*$", text)
    assert "cancel-in-progress: true" in text
    assert "github.ref" in text


def test_ci_has_single_django_job_and_no_deployment_job():
    text = workflow_text()
    jobs_text = text.split("jobs:", 1)[1]
    job_ids = re.findall(r"(?m)^  ([a-zA-Z0-9_-]+):\s*$", jobs_text)

    assert job_ids == ["django"]
    assert not re.search(r"(?i)\bdeploy\b|\bdeployment\b|production", text)
    assert not re.search(r"(?m)^    environment:\s*", text)


def test_ci_starts_postgres_and_redis_services():
    text = workflow_text()

    assert re.search(r"(?m)^      postgres:\s*$", text)
    assert "image: postgres:16-alpine" in text
    assert "POSTGRES_DB: ksa_games" in text
    assert "POSTGRES_USER: ksa_games" in text
    assert "POSTGRES_PASSWORD: ksa_games_ci_password" in text
    assert "pg_isready -U ksa_games -d ksa_games" in text
    assert "- 5432:5432" in text

    assert re.search(r"(?m)^      redis:\s*$", text)
    assert "image: redis:7-alpine" in text
    assert "redis-cli ping" in text
    assert "- 6379:6379" in text


def test_ci_installs_dependencies_and_runs_required_checks():
    text = workflow_text()

    assert "actions/checkout@v4" in text
    assert "actions/setup-python@v5" in text
    assert 'python-version: "3.12"' in text
    assert 'python -m pip install -e ".[dev]"' in text
    assert "python manage.py check" in text
    assert "python manage.py makemigrations --check --dry-run" in text
    assert "python manage.py migrate --noinput" in text
    assert re.search(r"(?m)^        run: pytest\s*$", text)


def test_ci_uses_local_test_environment_without_repository_secrets():
    text = workflow_text()

    for name in EXPECTED_ENVIRONMENT:
        assert re.search(rf"(?m)^      {name}:", text), f"{name} missing"

    assert "KSA_DATABASE_ENGINE: postgresql" in text
    assert "KSA_DB_HOST: 127.0.0.1" in text
    assert "KSA_REDIS_URL: redis://127.0.0.1:6379/0" in text
    assert "KSA_GOOGLE_OAUTH_CLIENT_SECRET: \"\"" in text
    assert "secrets." not in text
    assert "${{ secrets" not in text
