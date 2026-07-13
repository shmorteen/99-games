# Product Spec

## Vision

Build a real-time multiplayer platform where users can create accounts, browse a
catalog of games, create or join lobbies, play against humans or bots, spectate
live games, and expose streaming-safe views for broadcasts.

The platform should support at least 99 games over time without duplicating the
same lobby, realtime, spectator, bot, or scoring logic for each game.

## Initial Games

1. Connect4
2. Hangman
3. Werewolves vs Villagers

## Core Users

- Players who join public or private lobbies.
- Hosts who create lobbies and manage game setup.
- Spectators who watch active games without accessing hidden information.
- Streamers who use spectator-safe OBS overlays.
- Administrators who manage catalog entries and platform health.

## Core Capabilities

- Email and password authentication.
- Optional Google OAuth.
- Game catalog with playable and upcoming games.
- Public and private lobbies.
- Player and spectator roles.
- Reconnect support for interrupted realtime sessions.
- Server-authoritative action validation.
- Bot participation through the same action path as humans.
- Spectator-safe game state and streaming overlays.
- Match results and replay-ready state history.

## Non-Functional Requirements

- PostgreSQL is the persistent source of truth.
- Redis is used for presence, Channels, queues, locks, timers, and short-lived
  cache data.
- Game actions must be validated server-side.
- Client-supplied scores, winners, balances, roles, results, turns, and
  timestamps must never be trusted.
- Hidden game information must never be present in public or spectator payloads.
- Every externally visible resource should use a UUID.
- Concurrency-sensitive flows must use transactions, idempotency keys, state
  versions, constraints, and distributed locks as appropriate.

## Out of Scope for the Initial Milestone

- Mandatory qualifier systems.
- Real-money wagering.
- Native mobile apps.
- One Django app per game.
