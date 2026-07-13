# KSA Games Engineering Instructions

## Product

KSA Games is a real-time multiplayer gaming platform.

Users can:

* create accounts;
* browse a game catalog;
* create and join game lobbies;
* play against humans or bots;
* spectate active games;
* host a lobby broadcast;
* expose spectator-safe OBS overlays;
* watch games featured on the official platform livestream page.

There is no mandatory qualifier system.

Initial production games:

1. Connect4
2. Hangman
3. Werewolves vs Villagers

The architecture must eventually support at least 99 games through reusable game engines and game families.

## Engineering principles

1. PostgreSQL is the persistent source of truth.
2. Redis is used for Channels, presence, locks, queues, timers, and short-lived caching.
3. Never use process-local dictionaries as authoritative production state.
4. Never trust client-supplied score, role, turn, result, balance, timestamp, or winner information.
5. All game actions must be validated server-side.
6. Hidden information must never appear in public or spectator state.
7. Human users and bots must use the same game-action service.
8. Every externally visible resource should use a UUID.
9. Use database transactions, constraints, idempotency keys, state versions, and distributed locks.
10. Do not implement one Django application per game.
11. Do not duplicate lobby, WebSocket, spectator, bot, streaming, or rating logic between games.
12. Only mark a game playable when its engine, interface, tests, rules, and spectator view are complete.

## Required stack

* Python 3.11+
* Django
* Django REST Framework
* Django Channels
* Daphne
* PostgreSQL
* Redis
* Celery
* django-allauth
* pytest
* Docker Compose
* GitHub Actions

## Work loop

For every task:

1. Read this file and the relevant documents in `docs/`.
2. Inspect the current implementation before editing.
3. Confirm the task is listed in `docs/TASKS.md`.
4. Identify the acceptance criteria.
5. Create or update tests first where practical.
6. Implement only the selected task.
7. Run the narrow tests.
8. Run the full required checks.
9. Review the diff.
10. Fix regressions.
11. Update documentation.
12. Mark the task complete only when acceptance criteria pass.
13. Commit the change to a dedicated branch.

## Required checks

Run all applicable checks:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest
```

For frontend code, also run its configured lint, type-check, and build commands.

## Task scope

Complete exactly one coherent task or one small vertical slice per run.

Do not:

* implement multiple roadmap phases in one run;
* silently broaden the task;
* rewrite unrelated working code;
* delete working functionality without an approved migration;
* mark failing tests as skipped merely to pass CI;
* replace real implementations with placeholders;
* claim a feature works without testing it.

## Definition of done

A task is complete only when:

* its acceptance criteria pass;
* tests cover success and failure cases;
* authorization is enforced;
* concurrency concerns are handled;
* migrations are valid;
* public and private state are separated;
* no unrelated test fails;
* documentation is updated;
* the diff has been reviewed;
* remaining limitations are documented honestly.

## Repository documents

* `docs/PRODUCT_SPEC.md`: product requirements
* `docs/ARCHITECTURE.md`: approved architecture
* `docs/ROADMAP.md`: implementation phases
* `docs/TASKS.md`: ordered task queue
* `docs/ACCEPTANCE_CRITERIA.md`: verifiable completion conditions
* `docs/DECISIONS.md`: architecture decision records
* `docs/GAME_ENGINE_SPEC.md`: common engine contract
* `docs/GAME_CATALOG.md`: planned and implemented games

## Game implementation rule

Every playable game must provide:

* `GameDefinition` metadata;
* registered engine;
* validated configuration;
* initial-state creation;
* legal-action calculation;
* action validation;
* state transition logic;
* public-state serializer;
* private-state serializer;
* timeout behavior;
* result calculation;
* player interface;
* spectator interface;
* OBS overlay;
* rules page;
* bot strategy when bot support is declared;
* unit tests;
* integration tests;
* WebSocket tests;
* reconnect tests;
* authorization tests.

## Final response after each task

Report:

1. task completed;
2. files changed;
3. migrations added;
4. commands run;
5. tests passed and failed;
6. security or concurrency considerations;
7. documentation updated;
8. remaining limitations;
9. recommended next task.

Never conceal failing checks.
