# 99 Games

99 Games, also referred to as KSA Games in the project docs, is planned as a
real-time multiplayer gaming platform that can grow to at least 99 games through
shared lobby, engine, spectator, bot, and streaming infrastructure.

Initial production games:

1. Connect4
2. Hangman
3. Werewolves vs Villagers

## Status

`KSA-001 Initialize Django project and settings`, `KSA-002 Configure
PostgreSQL`, `KSA-003 Configure Redis and Django Channels`, `KSA-004 Configure
Celery`, `KSA-005 Add email/password authentication`, `KSA-006 Add
ArenaProfile`, `KSA-007 Add Google OAuth configuration`, `KSA-008 Add health
checks`, `KSA-009 Add Docker Compose`, `KSA-010 Add GitHub Actions`,
`KSA-011 Add GameCategory`, `KSA-012 Add GameDefinition`, `KSA-013 Add game
catalog pages`, `KSA-014 Add BaseGameEngine`, `KSA-015 Add
GameEngineRegistry`, `KSA-016 Add GameLobby`, `KSA-017 Add LobbyMembership`,
`KSA-018 Add lobby join/leave service`, `KSA-019 Add lobby WebSocket
consumer`, `KSA-020 Add ready-check and game start`, `KSA-021 Add Connect4
state representation`, and `KSA-022 Add legal move validation` are complete. The
repository contains a minimal Django project shell with
environment-driven settings, URL/ASGI/WSGI entrypoints, dependency metadata,
PostgreSQL-capable database configuration, Redis-backed channel layer
configuration, Celery worker configuration, django-allauth email/password
authentication, optional Google OAuth, ArenaProfile public player identity,
health endpoints, Docker Compose local services, GitHub Actions CI, the first
game catalog category and definition models, public catalog pages, the shared
game engine contract, the engine registry, lobby metadata, lobby memberships,
transactional lobby join/leave services, the lobby WebSocket consumer,
durable game-session start flow, pure Connect4 state and move-rule modules,
and smoke tests. Connect4 remains unplayable until its results, transport,
and interfaces are complete.

## Documentation

- `AGENTS.md`: engineering instructions and definition of done
- `docs/PRODUCT_SPEC.md`: product requirements
- `docs/ARCHITECTURE.md`: approved architecture direction
- `docs/ROADMAP.md`: implementation phases
- `docs/TASKS.md`: ordered task queue
- `docs/ACCEPTANCE_CRITERIA.md`: verifiable completion criteria
- `docs/DECISIONS.md`: architecture decision records
- `docs/GAME_ENGINE_SPEC.md`: common game engine contract
- `docs/GAME_CATALOG.md`: planned and implemented games

## Planned Stack

- Python 3.11+
- Django
- Django REST Framework
- Django Channels and Daphne
- PostgreSQL
- Redis
- Celery
- django-allauth
- pytest
- Docker Compose
- GitHub Actions

## Development

Create and activate a virtual environment, then install the project with its
development dependencies.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

If `py` is not installed, use any Python 3.11+ executable to create the virtual
environment.

Run the required checks:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
```

Apply local database migrations after installing dependencies or changing the
local SQLite database:

```powershell
python manage.py migrate
```

Run a local Celery worker:

```powershell
celery -A ksa_games worker --loglevel=info
```

### Docker Compose

The Compose setup is for local development only. Copy the example environment
file, validate the Compose file, start PostgreSQL and Redis, then run the
Django checks from the web service image.

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up -d db redis
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
docker compose run --rm web pytest
docker compose up web worker
```

The `postgres_data` named volume preserves local PostgreSQL data between
container restarts. Use `docker compose down -v` only when you intentionally
want to delete local database state.

### Continuous Integration

GitHub Actions runs CI on pushes and pull requests targeting `main`. The
workflow installs project dependencies, starts PostgreSQL and Redis service
containers, applies migrations, and runs:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
```

The CI workflow uses local test environment values and does not require
repository secrets for normal test execution.

### Environment

The project shell reads these optional local environment variables:

- `KSA_DEBUG`: boolean; defaults to `true`.
- `KSA_SECRET_KEY`: Django secret key. Required when `KSA_DEBUG=false`.
- `KSA_ALLOWED_HOSTS`: comma-separated host list; defaults to local hosts.
- `KSA_DATABASE_URL`: database URL. Supports `postgresql://`, `postgres://`,
  and `sqlite://`.
- `KSA_DATABASE_ENGINE`: `sqlite` or `postgresql`; defaults to `sqlite` for
  isolated local development and tests.
- `KSA_SQLITE_PATH`: local SQLite database path when using the SQLite fallback.
- `KSA_DB_NAME`: PostgreSQL database name when using discrete PostgreSQL
  variables.
- `KSA_DB_USER`: PostgreSQL user; defaults to `postgres`.
- `KSA_DB_PASSWORD`: PostgreSQL password; defaults to empty for local
  development only.
- `KSA_DB_HOST`: PostgreSQL host; defaults to `localhost`.
- `KSA_DB_PORT`: PostgreSQL port; defaults to `5432`.
- `KSA_DB_CONN_MAX_AGE`: optional non-negative Django connection age.
- `KSA_DB_SSLMODE`: optional PostgreSQL SSL mode.
- `KSA_REDIS_URL`: Redis URL for Channels; defaults to
  `redis://localhost:6379/0`.
- `KSA_CHANNEL_PREFIX`: Redis channel key prefix; defaults to `ksa-games`.
- `KSA_CHANNEL_CAPACITY`: optional positive channel capacity.
- `KSA_CHANNEL_EXPIRY`: optional positive channel message expiry in seconds.
- `KSA_CHANNEL_GROUP_EXPIRY`: optional positive group expiry in seconds.
- `KSA_CELERY_BROKER_URL`: Celery broker URL; defaults to
  `redis://localhost:6379/1`.
- `KSA_CELERY_RESULT_BACKEND`: Celery result backend URL; defaults to
  `redis://localhost:6379/2`.
- `KSA_CELERY_TASK_DEFAULT_QUEUE`: default Celery queue; defaults to
  `ksa-games`.
- `KSA_CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP`: optional boolean broker
  startup retry flag.
- `KSA_GOOGLE_OAUTH_CLIENT_ID`: optional Google OAuth client ID.
- `KSA_GOOGLE_OAUTH_CLIENT_SECRET`: optional Google OAuth client secret. Must
  be set together with `KSA_GOOGLE_OAUTH_CLIENT_ID`.
- `KSA_GAME_ENGINE_MODULES`: optional comma-separated Python module paths loaded
  at startup for engine registration. Defaults to no modules.
- `KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS`: optional boolean. Defaults to
  `false`; when `true`, anonymous spectator WebSocket connections are allowed
  only in debug mode and only for lobbies that allow spectators.
- `KSA_READY_CHECK_TIMEOUT_SECONDS`: optional positive integer ready-check
  timeout; defaults to `30`.
- `KSA_READY_CHECK_TIMEOUT_BEHAVIOR`: ready-check expiry behavior. Currently
  only `return_to_waiting` is supported.
- `KSA_LOBBY_START_LOCK_BACKEND`: lobby start lock backend. Defaults to
  `redis`; tests override this to `noop`.
- `KSA_LOBBY_START_LOCK_REDIS_URL`: Redis URL for lobby start locks. Defaults
  to `KSA_REDIS_URL` or `redis://localhost:6379/0`.
- `KSA_LOBBY_START_LOCK_PREFIX`: Redis lock key prefix; defaults to
  `ksa-games`.
- `KSA_LOBBY_START_LOCK_TIMEOUT_SECONDS`: optional positive integer lock lease
  timeout; defaults to `10`.
- `KSA_LOBBY_START_LOCK_BLOCKING_TIMEOUT_SECONDS`: optional positive integer
  lock acquisition timeout; defaults to `5`.

For PostgreSQL with discrete variables, set at minimum:

```powershell
$env:KSA_DATABASE_ENGINE = "postgresql"
$env:KSA_DB_NAME = "ksa_games"
```

For isolated local development and tests, SQLite remains the default. Do not use
the SQLite fallback as production state.

`ksa_games.test_settings` switches Channels to an isolated in-memory channel
layer for tests that should not use Redis.

### Authentication

django-allauth is configured for email/password authentication at:

- `/accounts/signup/`
- `/accounts/login/`
- `/accounts/logout/`

Email verification is intentionally disabled for this foundation slice with
`ACCOUNT_EMAIL_VERIFICATION = "none"`. Email messages use Django's in-memory
email backend in local settings.

Google OAuth is configured through django-allauth social accounts. The Google
login path is `/accounts/google/login/` and the callback path is
`/accounts/google/login/callback/`.

For environment-backed local setup, create a Google OAuth web client, add this
authorized redirect URI, and set both variables before starting Django:

```powershell
$env:KSA_GOOGLE_OAUTH_CLIENT_ID = "your-google-client-id"
$env:KSA_GOOGLE_OAUTH_CLIENT_SECRET = "your-google-client-secret"
```

For admin-backed setup, leave those environment variables unset, run
`python manage.py migrate`, sign in to `/admin/`, and add a `SocialApp` for the
Google provider on the current Django site. Do not commit Google OAuth secrets
to the repository.

### Health Checks

Deployment and local operations can use:

- `/health/live/`: liveness; returns success when the Django process can serve
  requests.
- `/health/ready/`: readiness; checks database connectivity and checks Redis
  connectivity when the default Channels backend is Redis.

Readiness returns HTTP 200 with `status: "ready"` when required dependencies are
available, and HTTP 503 with `status: "not_ready"` when a configured dependency
is unavailable. Health responses intentionally expose only check names and
sanitized statuses.

### Arena Profiles

Each user receives one `ArenaProfile` when the user is created. Profiles expose
a UUID `public_id` for public identity and a display name for player-facing
labels. Default display names use the format `Player <user id>` and do not
reuse the user's email address.

Display names are normalized before save, limited to 3-24 characters, and may
contain only letters, numbers, spaces, hyphens, and underscores. They must start
and end with a letter or number and are unique case-insensitively. Profiles are
registered in Django admin for staff inspection.

### Game Categories

`GameCategory` is the first shared game-catalog model. It stores a UUID public
identifier, unique name, unique slug, description, optional icon key, display
order, active flag, and timestamps. The initial seeded categories are Board
Games, Word Games, Deduction Games, Trivia Games, and Party Games.

Inactive categories are excluded from the public catalog query helper. Category
management is available in Django admin for staff users, including reorder and
activate/deactivate controls.

### Game Definitions

`GameDefinition` stores registered game metadata for the shared catalog:
category, UUID public identifier, unique slug, descriptions, engine key and
version, player limits, estimated duration, support flags, rules JSON, default
configuration JSON, image fields, playable/featured/active flags, and
timestamps.

The initial game definitions are Connect4, Hangman, and Werewolves vs Villagers.
They are seeded as active catalog entries with `is_playable=False` because their
engines, interfaces, rules pages, spectator views, overlays, and tests are not
implemented yet. The model rejects playable games unless a registered engine
check passes.

### Game Catalog Pages

The public game catalog is available at:

- `/games/`
- `/games/<slug>/`
- `/games/categories/<slug>/`

The catalog supports text search, category filtering, player-count filtering,
maximum-duration filtering, bot-support filtering, playable-only filtering, and
pagination. Public pages show only active games in active categories. Seeded
unimplemented games appear as `Coming Soon` and do not expose lobby creation
actions.

### Game Engine Contract

`games.engine.BaseGameEngine` defines the pure domain interface that every
playable game must implement. Engines validate configuration, create initial
JSON state, expose public, spectator-safe, and actor-private state, calculate
legal actions, apply actions through `GameTransition`, handle timeouts, choose
bot actions, detect completion, and build server-derived results.

Engine transitions are JSON-serializable and carry updated state, emitted domain
events, completion status, the next actor when applicable, and optional result
information. Standard exceptions cover invalid configuration, invalid payloads,
invalid actors, unauthorized or illegal actions, stale state, and already
completed games. Engines do not perform HTTP, template, WebSocket, or database
side effects directly.

### Game Engine Registry

`games.registry.GameEngineRegistry` stores the engine classes available in the
current application process by engine key and version. Engines can be registered
with `register()` or the registration decorator, then resolved with `get()`,
`create()`, `exists()`, `registered_engines()`, and
`validate_game_definition()`.

Application startup imports modules listed in `KSA_GAME_ENGINE_MODULES`; each
module may expose `register_engines(registry)` or use registration decorators.
No Connect4, Hangman, or Werewolves vs Villagers development engines are
registered yet because their real engine classes are not implemented.

Django system checks report registry registration problems. Database-backed
checks for playable catalog entries with missing or invalid engines run when
checks are invoked with a database context, such as
`python manage.py check --database default`.

### Game Lobbies

`lobbies.GameLobby` stores lobby metadata for future join, membership, and game
start flows. Each lobby has a UUID public identifier, unique human-readable
lobby code, selected playable game, authenticated host, visibility, status,
player limits, ranked/bot/spectator settings, game configuration, invite token
metadata, optional password hash, lifecycle timestamps, and created/updated
timestamps.

Lobby creation through the model manager requires a saved authenticated host.
Lobby validation blocks inactive or unplayable games, player ranges outside the
selected game's limits, unsupported ranked/bot/spectator settings, invalid bot
difficulties, invalid JSON metadata, plain-text password storage, and invalid
engine configuration. Passwords are set through `set_password()` and checked
with `check_password()`.

### Lobby Memberships

`lobbies.LobbyMembership` stores durable participation records for human users
and bots in a lobby. Memberships support host, co-host, player, spectator,
moderator, and bot roles; player-seat roles occupy a seat, while spectators and
moderators do not.

Active memberships are constrained so a human user can have only one active
membership in a lobby, two active members cannot occupy the same seat, a lobby
can have only one active host, and an active bot reference cannot be duplicated
within a lobby. Leaving or being kicked makes a membership inactive by setting
`left_at` or `kicked_at`, which releases those active constraints.

The model validates human versus bot identity, host ownership, seat eligibility,
ready-state eligibility, JSON metadata shape, and basic timestamp order.

### Lobby Join And Leave Services

`lobbies.services.join_lobby()` and `lobbies.services.leave_lobby()` are the
single mutation path for lobby joins and leaves. They use database transactions,
lobby row locking, active-membership locks, membership constraints, and audit
events to keep lobby membership state server-authoritative.

Joining validates saved authenticated users, suspended users, lobby status,
visibility credentials, lobby bans, duplicate memberships, player capacity, and
spectator capacity. Public lobbies can be joined directly, private lobbies
require the correct password, and invite-only lobbies require a valid unexpired
token stored under `invite_token_metadata["tokens"]`.

Leaving marks the membership inactive, clears ready state, updates connection
status, releases the seat through active-membership constraints, writes an audit
event, and transfers host ownership deterministically. The next host is the
earliest active co-host, then the earliest active player, then another eligible
human member; the lobby is cancelled if no successor exists.

`LobbyBan` stores durable lobby bans, and `LobbyAuditEvent` stores join, leave,
host-transfer, and cancellation events with optional idempotency keys. Repeated
join or leave requests with the same key return the original membership without
creating duplicates.

### Lobby WebSocket Consumer

Lobby realtime traffic is available at:

- `/ws/lobbies/<lobby_uuid>/`

Authenticated clients receive a `LOBBY_SNAPSHOT` immediately after connecting.
Messages use a common envelope with `type`, optional `request_id`,
`server_timestamp`, `lobby_uuid`, and `payload`.

The consumer accepts `LOBBY_JOIN`, `LOBBY_LEAVE`, `LOBBY_READY`,
`LOBBY_UNREADY`, `LOBBY_CHAT`, `HOST_TRANSFER`, `BOT_ADD`, `BOT_REMOVE`,
`READY_CHECK_START`, `GAME_START`, and `GAME_RESYNC`. Lobby joins, leaves,
ready-state changes, host transfer, bot membership changes, ready checks, and
game starts route through services so WebSocket traffic shares the same
authorization, capacity, ban, suspended-user, idempotency, and
database-constraint rules as future HTTP paths.

Anonymous WebSocket connections are rejected by default. Development-only guest
spectator access requires `KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS=true`,
`KSA_DEBUG=true`, and a lobby that explicitly allows spectators.

### Ready Check And Game Start

`lobbies.services.begin_ready_check()` moves a waiting lobby into
`READY_CHECK`, records ready-check timestamps, resets required human player
ready flags, marks bots ready, and writes an audit event. Human player-seat
members can ready or unready only while a ready check is active. Spectators do
not participate.

`lobbies.services.start_game()` requires a host or co-host, an active ready
check, a playable game, valid lobby configuration, valid player counts, and all
required human players ready. It uses a Redis lobby-start lock, database
transactions, `select_for_update()` row locks, and idempotency keys to create
exactly one durable `GameSession`.

The `play` app stores `GameSession` and `GameSessionParticipant` rows. Sessions
capture the selected engine key/version, lobby configuration, initial
authoritative state, public state, spectator state, state version, and start
time. Participants link lobby memberships into the session and store actor IDs,
role/seat data, bot metadata, and per-actor private state.

Successful WebSocket starts broadcast `GAME_STARTED` with public initial state
to the lobby and send `GAME_STARTED_PRIVATE` only to each authenticated player.
Spectators never receive private player state.

Game-specific action handling, Connect4 moves, replay history, results, bot
turn execution, and spectator/overlay gameplay views are intentionally deferred
to later tasks.
