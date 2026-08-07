# Current State Audit

Audit date: 2026-07-13

## Scope Reviewed

The audit reviewed:

- `AGENTS.md`
- `README.md`
- `docs/ACCEPTANCE_CRITERIA.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/GAME_CATALOG.md`
- `docs/GAME_ENGINE_SPEC.md`
- `docs/PRODUCT_SPEC.md`
- `docs/ROADMAP.md`
- `docs/TASKS.md`

## Current Repository State

The repository now contains the KSA-001 Django project shell through the KSA-020
ready-check and game-start slice plus project guidance, product
requirements, architecture notes, task lists, and game planning docs.

The current tree contains:

- `manage.py`
- the `ksa_games` Django project package
- Python dependency metadata in `pyproject.toml`
- PostgreSQL-capable environment-driven database settings
- Redis-backed Django Channels settings and ASGI protocol routing
- Celery app configuration with Redis broker/result backend settings
- django-allauth email/password signup, login, and logout configuration
- django-allauth social account support for Google OAuth only
- minimal account templates with CSRF-protected forms
- the `accounts` app with ArenaProfile public player identities
- a project-owned migration for ArenaProfile
- liveness and readiness endpoints for process, database, and Redis checks
- local Docker Compose services for web, PostgreSQL, Redis, and Celery worker
- `.env.example` for local container environment variables
- GitHub Actions CI for Django checks, migration validation, and pytest
- the `games` app with GameCategory and GameDefinition catalog models
- seeded initial game categories for board, word, deduction, trivia, and party games
- seeded initial game definitions for Connect4, Hangman, and Werewolves vs Villagers
- public game catalog list, detail, and category pages
- the BaseGameEngine contract, GameTransition value object, and standard engine
  errors
- the GameEngineRegistry, startup module loading hook, and registry system checks
- the `lobbies` app with the GameLobby, LobbyMembership, LobbyBan, and
  LobbyAuditEvent models and migrations
- transactional lobby join and leave services
- the authenticated lobby WebSocket consumer and lobby route
- the `play` app with durable GameSession and GameSessionParticipant records
- transactional ready-check and game-start services
- pytest-discovered smoke tests

The current tree does not contain:

- frontend assets

This matches the README status that `KSA-001`, `KSA-002`, `KSA-003`, `KSA-004`,
`KSA-005`, `KSA-006`, `KSA-007`, `KSA-008`, `KSA-009`, `KSA-010`, `KSA-011`,
`KSA-012`, `KSA-013`, `KSA-014`, `KSA-015`, `KSA-016`, `KSA-017`,
`KSA-018`, `KSA-019`, and `KSA-020` are complete and later game-platform
integrations remain deferred.

## Architecture Alignment

The proposed architecture is coherent and internally consistent:

- The product direction is a real-time multiplayer gaming platform.
- PostgreSQL is documented as the durable source of truth.
- Redis is documented for Channels, presence, queues, locks, timers, and cache.
- Django, Django REST Framework, Channels, Daphne, Celery, django-allauth,
  pytest, Docker Compose, and GitHub Actions are listed as required stack.
- The game architecture favors shared platform services instead of one Django
  app per game.
- Public, private, and spectator game state separation is explicitly required.
- Server-authoritative game actions are documented as a hard rule.

The repository is partially implemented against that architecture. It has a
Django shell, realtime configuration, Celery configuration, email/password
authentication, optional Google OAuth, public player profiles, catalog metadata
models, public catalog pages, lobby realtime consumers, and durable game-start
sessions, but no game-action services or domain background jobs yet.
It also exposes deployment health endpoints for the current runtime foundation.
Local Docker Compose now wires the current runtime foundation together for
development, but it is not a production deployment manifest.

## Implementation Gaps

### Runtime Foundation

The Django project shell now exists with settings, ASGI, WSGI, URL routing,
dependency metadata, admin routing, health endpoints, and smoke tests.

Impact: Django checks, pytest, and basic operational probes can run, but no
game-domain behavior exists yet. The documented Compose workflow can also run
Django checks inside the web service image.

### Persistence

PostgreSQL is required by the architecture. The PostgreSQL driver and
environment-driven database settings now exist, with SQLite kept only as a
documented local/test fallback. A project-owned migration now exists for
ArenaProfile.

Impact: the settings can target PostgreSQL, and the repository now exercises one
small profile persistence model. Game and lobby persistence still require future
domain models and a running PostgreSQL service. Readiness now verifies database
connectivity without returning connection details. The Compose setup preserves
local PostgreSQL data in a named `postgres_data` volume.

### Realtime Layer

Redis, Django Channels, and Daphne are required. The dependencies, Redis-backed
channel layer settings, ASGI protocol router, authenticated lobby WebSocket
route, and isolated in-memory test settings now exist.

Impact: realtime infrastructure can be loaded and smoke-tested, and lobbies can
now expose snapshots, presence, joins, leaves, ready checks, ready toggles, host
transfer, bot membership events, chat envelopes, game-start public/private
events, and resyncs over WebSockets. Gameplay action routing, spectator
game-state streaming, and overlay flows still require later game-action work.
Readiness checks Redis when the default Channels backend is Redis, and skips it
only when Redis is not configured for the current settings. Compose provides a
local Redis service for Channels, Celery URLs, and the production lobby-start
lock backend.

### Background Work

Celery is required. The dependency, Celery app, Redis broker/result settings,
worker command documentation, and import-safe smoke task now exist.

Impact: workers can discover the project app and smoke task, but bot turns,
timeouts, cleanup, and scheduled jobs intentionally have no execution path yet.

### Authentication and Profiles

Email/password authentication is configured with django-allauth, including
signup, login, logout, duplicate-email rejection, CSRF-protected server-rendered
forms, and tests. Email verification is intentionally set to `none` for this
foundation slice.

ArenaProfile is implemented in the `accounts` app. Each user receives one
profile with a UUID public identifier and a validated, case-insensitively unique
display name. The profile is registered in Django admin for staff inspection.

Google OAuth is configured through django-allauth social accounts with only the
Google provider installed. Credentials can come from
`KSA_GOOGLE_OAUTH_CLIENT_ID` and `KSA_GOOGLE_OAUTH_CLIENT_SECRET`, or from an
admin-managed SocialApp. The login template exposes the Google login link only
when allauth reports a configured provider. Ratings, balances, and game stats
remain unimplemented.

Impact: the platform can authenticate basic email/password users, but it cannot
yet support game-derived profile data.

### Game Platform Core

GameCategory is now implemented as the first shared game catalog model with a
UUID public identifier, unique name and slug, description, optional icon key,
display order, active status, timestamps, admin management, active public
catalog filtering, and seeded initial categories.

GameDefinition is now implemented as shared game catalog metadata with UUID
public identifiers, protected categories, unique slugs, descriptions, engine
metadata, player limits, estimated duration, support flags, JSON rules/default
configuration, image fields, active/featured/playable flags, admin management,
active public catalog filtering, and seeded initial definitions for Connect4,
Hangman, and Werewolves vs Villagers. Seeded games are not playable because no
engines are registered yet.

BaseGameEngine is now implemented as the shared pure-domain contract for future
playable games. It defines configuration validation, initial-state creation,
public, spectator-safe, and private state serializers, legal-action
calculation, action application, timeout handling, bot-action selection,
completion checks, and result building. `GameTransition` carries
JSON-serializable updated state, events, completion status, next actor, and
optional result data. Standard engine errors cover invalid configuration,
illegal action, unauthorized action, stale state, already completed games,
invalid actors, and invalid payloads.

GameEngineRegistry is now implemented as the code-level lookup table for
available engine classes. It supports explicit and decorator registration,
engine key/version lookup, registered-engine listing, existence checks,
`GameDefinition` validation, startup loading from `KSA_GAME_ENGINE_MODULES`, and
Django system-check reporting for duplicate registrations, invalid versions, and
playable definitions that reference missing engines. No initial game is
registered yet because Connect4, Hangman, and Werewolves vs Villagers do not
have real engine classes.

GameLobby is now implemented in the `lobbies` app. It stores UUID public
identifiers, unique lobby codes, selected games, hosts, visibility, status,
player limits, ranked/bot/spectator options, game configuration, password
hashes, invite token metadata, lifecycle timestamps, and created/updated
timestamps. The model manager restricts lobby creation to saved authenticated
hosts. Model validation blocks inactive or unplayable games, invalid player
ranges, unsupported ranked/bot/spectator settings, invalid bot difficulties,
invalid JSON metadata, plain-text password storage, and invalid engine
configuration.

LobbyMembership is now implemented in the `lobbies` app. It stores durable
human and bot participation records with roles, optional seats, ready state,
connection state, joined/left/kicked timestamps, server-owned score, result
JSON, and metadata JSON. Model validation distinguishes human users from bot
references, limits ready state to player-seat roles, keeps spectators and
moderators out of player seats, validates host ownership, and checks JSON and
timestamp shape. Partial database constraints enforce one active human
membership per lobby, one active member per seat, one active host per lobby,
and one active bot reference per lobby.

Lobby join/leave services are now implemented in `lobbies.services`. Joining
and leaving run in database transactions, lock the lobby row and active
memberships, enforce credentials, bans, suspended-user checks, duplicate
membership rules, player capacity, spectator capacity, idempotency, and audit
events. Leaving marks memberships inactive, clears ready state, updates
connection status, releases the active seat, and transfers host ownership to an
active co-host, earliest active player, or another eligible human member. The
lobby is cancelled when no eligible host successor remains.

Ready-check and game-start services are now implemented. A host or co-host can
move a waiting lobby into ready-check state, human player-seat memberships can
ready or unready only during that state, spectators are excluded from ready
checks, bots are marked ready, and ready-check expiry can return the lobby to
waiting.

The `play` app now stores durable `GameSession` and `GameSessionParticipant`
records. Starting a game uses a Redis lobby-start lock, database transactions,
row locking, idempotency keys, engine configuration validation, initial-state
creation through the registered engine, participant linking from active lobby
memberships, public/spectator/private state serialization, and audit events.
Lobby status transitions from `READY_CHECK` to `STARTING` to `ACTIVE` inside
the transaction, and engine-start failures roll back partial sessions.

Leaving an active lobby records a server-owned disconnect/forfeit policy in
membership metadata for the future gameplay action service.

Lobby WebSocket routing is now implemented at `/ws/lobbies/<lobby_uuid>/`.
Connections validate lobby existence, origin, authentication, suspension,
lobby bans, membership/spectator eligibility, and lobby status before accepting.
Accepted clients receive `LOBBY_SNAPSHOT`, and client events route through lobby
services for joins, leaves, ready/unready, host transfer, bot add/remove, and
resync behavior. Ready-check start and game-start events also route through
services. Successful starts broadcast public `GAME_STARTED` payloads to the
lobby group and private `GAME_STARTED_PRIVATE` payloads only to authenticated
player groups. The consumer owns presence updates and broadcast fanout without
bypassing database constraints.

The public catalog pages now expose `/games/`, `/games/<slug>/`, and
`/games/categories/<slug>/`. They support search, category, player count,
duration, bot-support, playable-only filters, pagination, active-only visibility,
coming-soon behavior for unimplemented games, and detail views with rules,
configuration, feature, and lobby-status metadata.

Impact: the platform can group, describe, render, define the engine boundary,
validate playable catalog entries against available engine classes, persist
lobby metadata and membership rows, join or leave lobbies through services,
route lobby state changes over WebSockets, and create durable game sessions,
but it cannot yet route game actions through persisted services.

### Game Implementations

Connect4, Hangman, and Werewolves vs Villagers are seeded as not-playable
catalog entries, but there are no engines, interfaces, rules pages, overlays,
bot strategies, or gameplay tests.

Impact: no game can be marked playable.

### Security and Concurrency

The docs correctly require server-side validation, hidden-state isolation,
transactions, constraints, state versions, idempotency keys, and distributed
locks. Health responses now intentionally avoid exposing exception text,
database names, Redis URLs, credentials, or stack traces. Lobby start now uses
transactional row locks, idempotency keys, a Redis lock, and separate
public/spectator/private engine state paths.

Impact: health check output is sanitized, and the first game-start boundary has
concurrency and private-state protections. Future game-action services still
need the same guarantees.

### Test and CI

The required checks are documented, and a pytest suite now covers the project
shell, database settings, channel layer settings, Celery settings,
email/password authentication behavior, ArenaProfile validation, admin access,
Google OAuth configuration/page behavior without external Google calls,
healthy/unhealthy health-check behavior, Docker Compose topology, GitHub
Actions workflow shape, GameCategory creation, validation, admin access, seed
data, active filtering, and safe deletion behavior, GameDefinition creation,
invalid ranges, unique slugs, active filtering, playable-engine validation,
configuration validation, admin access, seed data, category protection, and
catalog indexes, and catalog page loading, search, filtering, pagination,
inactive hiding, coming-soon behavior, detail pages, category pages, invalid
slug handling, responsive template markers, base engine contract enforcement,
transition serialization, standard engine exceptions, invalid inputs,
authorization, stale state handling, idempotent retry shape, completed-game
rejection, public/private/spectator state separation, engine registry
registration, duplicate rejection, lookup, version selection, startup loading,
`GameDefinition` validation, system-check failures, and unregistered catalog
behavior, GameLobby creation, authenticated-host enforcement, invalid game
blocking, player-range validation, ranked/bot/spectator support validation,
unique lobby codes, password hashing, engine-backed configuration validation,
lobby admin registration, LobbyMembership player, spectator, bot, duplicate
membership, duplicate seat, one-host, active/inactive, ready-state, seat, JSON,
ownership, admin registration behavior, lobby service public joins, spectator
joins, private passwords, invite tokens, expired invites, full player and
spectator capacity, duplicate joins, idempotent joins and leaves, banned users,
suspended users, leaving, seat release, host transfer, cancellation after host
leave, active-lobby leave policy, lobby WebSocket authorized and unauthorized
connections, invalid lobby rejection, initial snapshots, invalid event and
payload errors, ready/unready permission rules, join/leave broadcasts, host and
bot permissions, reconnect snapshots, presence updates, and spectator
restrictions, ready-check start, player ready/unready behavior during
ready-check, spectator ready rejection, insufficient players, unready-player
rejection, unauthorized start rejection, idempotent start, duplicate session
prevention, engine initial-state creation, rollback after engine-start failure,
public/private state separation, ready-check timeout, bot-ready behavior, and
WebSocket `GAME_STARTED` public/private fanout. Compose validation tests cover
the local service topology and
documented check workflow. GitHub
Actions CI now runs on pushes and pull requests targeting `main`, installs
dependencies, starts PostgreSQL and Redis services, applies migrations, and runs
Django checks, `makemigrations --check --dry-run`, and pytest without repository
secrets. There is still no separate frontend lint/type check setup because the
catalog uses Django templates without a frontend build pipeline.

Impact: local and CI smoke coverage now exist for the foundation. Future
implementation still needs game-domain tests as the domain model arrives.

## Documentation Gaps Addressed By This Pass

This documentation pass added:

- a current-state audit;
- a detailed ordered roadmap where each task is one small vertical slice;
- explicit acceptance criteria for the first ten tasks.

## Recommended Next Task

Start with `KSA-021 Add Connect4 state representation`.

That task should add the first game-specific state shape without implementing
move validation or WebSocket actions.
