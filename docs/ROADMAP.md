# Roadmap

This roadmap is the ordered implementation queue. Each task must remain one
small vertical slice. Do not combine adjacent tasks in one implementation run.

`docs/TASKS.md` is the compact checklist. This file is the detailed execution
order and scope boundary.

## Platform Foundation

### KSA-001 Initialize Django project and settings

Create the minimal Django project shell with settings, URL, ASGI, WSGI, and test
entrypoints.

Do not configure PostgreSQL, Redis, Channels, Celery, auth, game models, or
frontend UI in this task.

### KSA-002 Configure PostgreSQL

Add PostgreSQL dependency and environment-driven database settings. Keep SQLite
available only for isolated local or test use if explicitly documented.

Do not add domain models beyond what Django creates by default.

### KSA-003 Configure Redis and Django Channels

Install and configure Django Channels, Daphne, ASGI routing, and a Redis-backed
channel layer.

Do not add lobby, gameplay, or spectator consumers in this task.

### KSA-004 Configure Celery

Add the Celery application, Redis broker/result settings, worker entrypoint, and
one import-safe smoke task.

Do not add bot logic, timeout logic, scheduled jobs, or gameplay tasks in this
task.

### KSA-005 Add email/password authentication

Configure django-allauth for email/password signup, login, logout, and email
identity behavior.

Do not add Google OAuth or player profile fields in this task.

### KSA-006 Add ArenaProfile

Add the user profile model and admin/test coverage for public player identity.

Do not add ratings, balances, game stats, or social account behavior in this
task.

### KSA-007 Add Google OAuth configuration

Configure Google OAuth through django-allauth social accounts and documented
environment variables.

Do not add additional OAuth providers in this task.

### KSA-008 Add health checks

Add liveness and readiness endpoints that can verify application, database, and
Redis availability.

Do not add metrics, dashboards, or external monitoring integrations in this
task.

### KSA-009 Add Docker Compose

Add Docker Compose services for the current runtime: web, PostgreSQL, Redis, and
Celery worker once Celery exists.

Do not add production deployment manifests in this task.

### KSA-010 Add GitHub Actions

Add CI that installs dependencies and runs the required Django and pytest checks
with PostgreSQL and Redis services.

Do not add deployment automation in this task.

## Game Platform Core

### KSA-011 Add GameCategory

Add the model, admin, migrations, and tests for grouping games in the catalog.

### KSA-012 Add GameDefinition

Add the model, admin, migrations, and tests for registered games and their
metadata.

### KSA-013 Add game catalog pages

Add the minimal user-facing catalog list/detail views backed by GameCategory and
GameDefinition.

### KSA-014 Add BaseGameEngine

Add the abstract Python interface that every game engine must implement.

### KSA-015 Add GameEngineRegistry

Add engine registration and lookup so game definitions can resolve their engine
by key.

### KSA-016 Add GameLobby

Add the lobby model with UUID public identifier, host, game definition, status,
visibility, and capacity fields.

### KSA-017 Add LobbyMembership

Add the membership model for player, spectator, host, and bot participation.

### KSA-018 Add lobby join/leave service

Add transactional join and leave behavior with capacity, credential,
idempotency, and host-transfer rules.

### KSA-019 Add lobby WebSocket consumer

Add a lobby-scoped WebSocket consumer for presence and lobby state updates.

### KSA-020 Add ready-check and game start

Add ready state and a server-authoritative transition from waiting lobby to game
session.

## Connect4

### KSA-021 Add Connect4 state representation

Add the Connect4 board, player markers, turn state, and serialized state shape.

### KSA-022 Add legal move validation

Add Connect4 column validation and illegal-action errors.

### KSA-023 Add win and draw detection

Add Connect4 result calculation for horizontal, vertical, diagonal, and draw
states.

### KSA-024 Add Connect4 WebSocket actions

Route Connect4 moves through the shared game-action service over WebSocket.

### KSA-025 Add Connect4 player interface

Add the playable Connect4 page and player controls.

### KSA-026 Add spectator and overlay views

Add spectator-safe Connect4 state views and OBS overlay output.

### KSA-027 Add Connect4 bots

Add bot move selection through the same action service used by humans.

### KSA-028 Add replay and results

Persist Connect4 action history and expose result/replay views.

## Additional Initial Games

### KSA-029 Add Hangman engine

Add Hangman state, hidden answer handling, legal guesses, results, and tests.

### KSA-030 Add Hangman interfaces

Add Hangman player, spectator, rules, and overlay views.

### KSA-031 Add Werewolves vs Villagers engine

Add phase, role, vote, hidden-state, result, and timeout mechanics.

### KSA-032 Add Werewolves vs Villagers interfaces

Add player, moderator-safe, spectator, rules, and overlay views.

## Scale Toward 99 Games

### KSA-033 Add reusable game-family templates

Extract shared patterns for grid, word, vote, hidden-role, and turn-based games.

### KSA-034 Add admin catalog management

Add admin workflows for game availability, feature flags, and catalog metadata.

### KSA-035 Add replay and observability tooling

Add operational tools for replay inspection, action audit trails, and realtime
health diagnostics.
