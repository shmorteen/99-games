# Architecture

## Overview

99 Games is a Django-based realtime multiplayer platform. The backend remains
server-authoritative, with PostgreSQL storing durable state and Redis supporting
realtime coordination, queues, timers, locks, presence, and short-lived caching.

## Runtime Components

- Django provides the application model, admin, templates, and server-rendered
  pages where useful.
- Django REST Framework exposes HTTP APIs for account, catalog, lobby, and game
  operations.
- Django Channels and Daphne handle WebSocket traffic for lobbies, gameplay,
  spectators, and overlays.
- PostgreSQL stores users, profiles, game definitions, lobbies, memberships,
  game sessions, actions, results, and audit data.
- Redis supports Channels, presence, distributed locks, timers, queues, and
  short-lived cache data.
- Celery runs background work such as bot turns, timeouts, cleanup, and
  scheduled platform tasks.

## Suggested Django Apps

- `accounts`: authentication integration and arena profiles.
- `games`: game catalog, definitions, categories, and engine registry.
- `lobbies`: lobby models, membership, permissions, and join/leave services.
- `play`: game sessions, actions, state versions, results, and replays.
- `realtime`: shared WebSocket consumers, event envelopes, and presence helpers.
- `bots`: bot strategies and scheduling.
- `streaming`: spectator pages and OBS overlays.

These boundaries may change during implementation, but the project should avoid
one Django application per playable game.

## State Model

- Durable state lives in PostgreSQL.
- Redis may mirror short-lived coordination state, but it is not authoritative.
- Process-local dictionaries must not be used for production state.
- Game state transitions must be atomic and versioned.
- Public state, private player state, and spectator state must be serialized
  through separate code paths.

## Realtime Flow

1. A client sends a game or lobby action over HTTP or WebSocket.
2. The server authenticates the user and authorizes the action.
3. The relevant service validates the action against current authoritative state.
4. The service applies the transition in a transaction with concurrency guards.
5. The server emits role-appropriate events to players, spectators, overlays, and
   bots.

## Security Rules

- Never trust client-supplied game results or hidden state.
- Never include hidden information in public payloads.
- Treat spectators and players as different audiences.
- Enforce membership and host permissions in services, not only in views.
- Use idempotency keys for retryable actions.

## Deployment Direction

The baseline deployment target is Docker Compose with Django, Daphne,
PostgreSQL, Redis, Celery worker, and Celery beat services. GitHub Actions should
run checks before changes are merged.
