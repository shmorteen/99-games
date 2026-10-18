# Decisions

This file records architecture decisions that should remain stable unless a new
decision supersedes them.

## ADR-001: Use One Shared Game Platform

Status: Accepted

The platform will use shared lobby, realtime, spectator, bot, streaming, and
rating infrastructure instead of creating one isolated Django app per game.

Reasoning:

- The platform must eventually support at least 99 games.
- Repeated lobby and WebSocket implementations would increase maintenance cost.
- Shared services make authorization, concurrency, observability, and streaming
  behavior easier to audit.

## ADR-002: PostgreSQL Is Authoritative

Status: Accepted

PostgreSQL is the durable source of truth for users, lobbies, memberships,
sessions, actions, results, and game definitions.

Redis may support coordination and cache data, but the application must be able
to rebuild durable truth from PostgreSQL.

## ADR-003: Server-Authoritative Game Actions

Status: Accepted

All game actions are validated and applied on the server. Clients can request an
action, but they cannot decide winners, scores, roles, turn order, balances,
timestamps, or final results.

## ADR-004: Separate Public, Private, and Spectator State

Status: Accepted

Every game engine must expose separate serializers for public state, private
player state, and spectator state. Hidden information must not be present in
spectator-safe or public payloads.

## ADR-005: ArenaProfile Public Identity

Status: Accepted

Each authenticated user has one ArenaProfile for player-facing identity. Public
references to profiles should use the profile UUID instead of the database
primary key.

Display names are normalized, limited to 3-24 characters, restricted to letters,
numbers, spaces, hyphens, and underscores, and unique case-insensitively. The
initial display name is generated without exposing the user's email address.

## ADR-006: Keep Google OAuth Secrets Out Of Source

Status: Accepted

Google OAuth support uses django-allauth social accounts with only the Google
provider installed.

OAuth client credentials must come from environment variables or from an
admin-managed allauth SocialApp. The repository must not contain real Google
client IDs or client secrets.

## ADR-007: Game Engines Are Pure Domain Contracts

Status: Accepted

Playable games implement `BaseGameEngine` and return JSON-serializable
`GameTransition` objects instead of performing framework side effects.

Reasoning:

- Shared lobby, realtime, bot, spectator, and replay services need one
  consistent engine boundary.
- Keeping HTTP, templates, WebSockets, and database writes outside engines makes
  authorization, transactions, idempotency, and audit behavior easier to test.
- Public and private state serializers are part of the contract so hidden data
  cannot be exposed by a generic transport layer.

## ADR-008: Load Game Engines Through an Explicit Registry

Status: Accepted

Game engine classes are registered in a process-local `GameEngineRegistry` by
engine key and version. Startup imports configured engine modules instead of
depending on incidental import order.

Reasoning:

- `GameDefinition` is durable catalog metadata, while engine classes are code
  artifacts available in the deployed process.
- Explicit module loading makes startup deterministic and system-checkable.
- Duplicate registrations, invalid versions, and playable games with missing
  engines can be reported before gameplay services depend on them.

## ADR-009: Keep Lobby Metadata Separate From Membership Services

Status: Accepted

`GameLobby` stores durable lobby metadata and local validation rules, while
membership mutation, join/leave behavior, realtime updates, and game start
transactions remain in later service layers.

Reasoning:

- Lobby metadata must exist before membership and ready-check workflows can be
  built safely.
- Keeping the first lobby slice model-only avoids hiding concurrency-sensitive
  join/leave behavior inside model methods.
- Passwords can be hashed at the model boundary, while invite tokens, audit
  events, distributed locks, and idempotency are deferred to service code.

## ADR-010: Store Lobby Participation In Durable Membership Rows

Status: Accepted

Lobby participation is represented by `LobbyMembership` rows with partial
database constraints for active user, seat, host, and bot uniqueness.

Reasoning:

- PostgreSQL remains the authoritative source for lobby participation.
- Partial unique constraints protect join and reconnect flows even if future
  services receive concurrent requests.
- Inactive memberships stay available for audit and results while releasing
  active seats after a user leaves or is kicked.
- The model stores membership state, but join, leave, kick, host transfer,
  idempotency, locks, audit events, and realtime broadcasts stay in services.

## ADR-011: Mutate Lobby Memberships Through Transactional Services

Status: Accepted

Lobby joins and leaves are handled by dedicated services that lock the lobby
state, enforce membership constraints, and write audit events.

Reasoning:

- HTTP views and WebSocket consumers should not duplicate capacity,
  credential, ban, idempotency, or host-transfer rules.
- Lobby row locking plus membership constraints prevents capacity overflow
  under concurrent join attempts.
- Audit rows provide durable evidence for joins, leaves, host transfers, and
  lobby cancellation.
- Idempotency keys live on audit events so repeated client requests can return
  the original membership without creating duplicate rows.

## ADR-012: Route Lobby WebSockets Through Service-Backed Event Envelopes

Status: Accepted

Lobby WebSocket traffic uses a shared envelope and delegates membership
mutations to lobby services instead of mutating rows directly in consumers.

Reasoning:

- WebSocket and future HTTP paths need the same permission, capacity, ban,
  idempotency, and host-transfer behavior.
- A stable event envelope keeps clients, tests, and future game consumers aligned
  around `type`, request correlation, server timestamps, lobby UUIDs, and
  payloads.
- Structured `ERROR` events make invalid client messages observable without
  leaking server internals or relying on transport-level disconnects.
- Consumers can own presence and broadcast fanout while PostgreSQL constraints
  and transactional services remain authoritative for lobby state.

## ADR-013: Persist Game Starts As Durable Sessions

Status: Accepted

Ready-check completion creates a durable `GameSession` and linked
`GameSessionParticipant` rows before gameplay actions exist.

Reasoning:

- PostgreSQL remains the source of truth for started games, selected engine
  versions, actor mappings, initial state, and private per-actor state.
- Lobby start must be idempotent and guarded by both a Redis lock and database
  row locks so duplicate start attempts cannot create multiple sessions.
- Game engines create initial state through the pure engine contract; services
  persist state, participants, audit events, and lobby status changes.
- Public start payloads can be broadcast to the lobby group while private state
  is sent only through per-user WebSocket groups.
- Ready-check timeout policy is intentionally explicit and currently limited to
  returning the lobby to waiting until richer kick/fill policies are designed.

## ADR-014: Issue Read-Only Connect4 OBS Links to Lobby Hosts

Status: Accepted

The current lobby host receives a signed, 24-hour, session-bound overlay URL on
their Connect4 player page. OBS can load it without sharing account cookies.
HTTP and WebSocket overlay reads verify the signature, session, current active
host, and ban status. A host transfer invalidates existing links. Overlay
connections receive only the validated spectator state and cannot submit game
actions. Responses disable caching and referrer forwarding. The host may reload
the player page to issue a fresh link after expiry. A copied URL is a bearer
credential and must be kept private by the host.

## ADR-015: Run Connect4 Bots Through Versioned Shared Actions

Status: Accepted

The seeded `casual` bot strategy is deterministic and reads the authoritative
board. A Celery task receives only a session UUID and expected version, then
derives the current actor from PostgreSQL and submits its chosen move through
`submit_game_action`. The service's Redis lock, database transaction, state
version, and idempotency receipt handle concurrent or repeated jobs. Enqueueing
occurs on transaction commit after session start and accepted actions. The
worker publishes the committed result to the common game channel. Queue
delivery is best effort until a durable outbox or reconciliation task is added.
