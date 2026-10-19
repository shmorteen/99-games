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

## Game Engine Contract

Every playable game implements `games.engine.BaseGameEngine`. A new game engine
must validate its configuration, create initial JSON state, expose public,
spectator-safe, and actor-private state, list legal actions, apply actions,
handle timeouts, choose bot actions, detect completion, and build
server-derived results.

Engine methods receive server-owned configuration, actor records, state, action
payloads, idempotency keys, and state versions. They return JSON-serializable
state or `GameTransition` objects and raise standard engine exceptions for
invalid configuration, invalid actors, unauthorized actions, illegal actions,
stale state, completed games, and malformed payloads.

Engines are pure domain logic. They must not write HTTP responses, render
templates, send WebSocket messages, trust client-supplied scores or winners, or
mutate database records directly. Application services wrap engines with
authentication, membership authorization, transactions, idempotency persistence,
state-version checks, broadcasting, and audit logging.

Public and spectator state must not contain hidden information. Private state
must be scoped to the requested actor and must never include another actor's
hidden data. Timeout transitions must be deterministic for the supplied state so
scheduled workers can retry safely.

## Game Engine Registry

`games.registry.GameEngineRegistry` maps deployed engine classes by engine key
and version. `GameDefinition` remains durable catalog metadata in PostgreSQL;
the registry is the code-level lookup table for engine implementations available
in the current application process.

Engine modules are loaded explicitly from `KSA_GAME_ENGINE_MODULES` during
`GamesConfig.ready()`. A module can register engines directly or expose a
`register_engines(registry)` hook. This keeps startup deterministic and avoids
depending on incidental import order.

Playable `GameDefinition` validation checks the registry before allowing a game
to be marked playable. Django system checks report duplicate registrations,
invalid engine versions, failed engine module imports, and playable definitions
that reference missing engines when database checks are enabled.

## Lobby Model

`lobbies.GameLobby` stores durable lobby metadata in PostgreSQL. The model owns
the lobby UUID, human-readable code, selected game, host, visibility, status,
capacity settings, ranked/bot/spectator options, configuration JSON, password
hash, invite metadata, and lifecycle timestamps.

Lobby model validation enforces only the invariants that can be checked before
membership services exist: the host must be a saved authenticated user when
created through the manager, the selected game must be active and playable,
capacity must fit the selected game, unsupported ranked/bot/spectator options
are rejected, lobby configuration is validated through the selected engine, and
passwords must be stored as Django hashes. Join/leave behavior, membership
roles, row locking, distributed locks, audit events, and realtime updates remain
service-layer responsibilities for later tasks.

## Lobby Membership Model

`lobbies.LobbyMembership` stores durable lobby participation records in
PostgreSQL. Each membership belongs to one lobby and represents either a human
user or a bot reference, with a role, optional player seat, ready flag,
connection status, joined/left/kicked timestamps, server-owned score, result
JSON, and metadata JSON.

Supported roles are host, co-host, player, spectator, moderator, and bot. Host,
co-host, player, and bot memberships consume player seats; spectators and
moderators do not. Ready status is limited to player-seat roles.

Database constraints protect the concurrency-sensitive invariants that can be
known at the model layer: one active membership per human user per lobby, one
active member per occupied seat, one active host per lobby, and one active bot
reference per lobby. A membership is active only while both `left_at` and
`kicked_at` are empty, so leaving or being kicked releases those active
constraints for future service-layer joins.

Membership rows validate human versus bot identity, host ownership, seat
eligibility, ready-state eligibility, JSON object shape, and basic timestamp
ordering. Join, leave, kick, host transfer, idempotency, locks, audit events,
and realtime notifications remain service-layer responsibilities.

## Lobby Join And Leave Service

`lobbies.services.join_lobby()` and `lobbies.services.leave_lobby()` are the
single application boundary for lobby membership mutations in this slice.
HTTP handlers and WebSocket consumers must call these services instead of
creating or updating memberships directly.

Joining runs inside `transaction.atomic()`, locks the lobby row and active
memberships, validates the actor, verifies lobby visibility credentials, checks
lobby bans, enforces player or spectator capacity, creates the membership, and
writes an audit event. The service supports idempotency keys by storing them on
audit events and returning the original membership for repeated join requests
with the same key.

Leaving also runs in a transaction, locks the lobby and active membership,
marks the membership inactive, clears ready state, updates connection status,
writes an audit event, and handles host transfer. If the host leaves, ownership
transfers first to the earliest active co-host, then to the earliest active
player, then to another eligible human member. If no eligible successor exists,
the lobby is cancelled.

`lobbies.LobbyBan` stores durable lobby bans. `lobbies.LobbyAuditEvent` stores
join, leave, host-transfer, and lobby-cancellation events, including optional
idempotency keys. Active gameplay sessions are not implemented yet, so leaving
an active lobby records the server-side disconnect/forfeit policy on the
membership metadata for the future play service to consume.

## Lobby WebSocket Consumer

`lobbies.consumers.LobbyConsumer` handles authenticated realtime lobby traffic
at `/ws/lobbies/<lobby_uuid>/`. The ASGI routing stack uses Channels
authentication middleware and keeps the HTTP app and WebSocket app behind the
same project routing boundary.

Connections validate lobby existence, allowed origin, authenticated user state,
lobby bans, membership/spectator eligibility, and lobby status before accepting.
Anonymous WebSocket connections are rejected by default; development-only guest
spectator access requires `DEBUG`, `KSA_ALLOW_GUEST_SPECTATOR_WEBSOCKETS=true`,
and a lobby that explicitly allows spectators.

Accepted connections receive a `LOBBY_SNAPSHOT` envelope immediately. All
consumer messages use a common schema with `type`, optional `request_id`,
`server_timestamp`, `lobby_uuid`, and `payload`. Invalid event types and invalid
payload shapes return structured `ERROR` envelopes instead of raising transport
exceptions.

Lobby membership mutations still route through `lobbies.services`. The consumer
may broadcast join, leave, ready-state, host-change, status-change, spectator,
chat, and snapshot events, but it must not bypass database constraints or
service-layer permission checks for ready state, host transfer, bot membership,
player capacity, bans, or suspended users.

## Ready Check And Game Start

`lobbies.services.begin_ready_check()` moves a waiting lobby into
`READY_CHECK`, records ready-check timestamps, resets required human player
ready flags, treats bot player seats as ready, and writes an audit event. Human
player-seat memberships may ready or unready only while the lobby is in
ready-check state. Spectators and moderators do not participate in ready checks.

`lobbies.services.start_game()` is the first game-start boundary. It requires a
host or co-host, an active ready check, a playable game, a valid lobby
configuration, player counts within lobby limits, and every required human
player to be ready. It uses a Redis lobby-start lock plus database transactions
and `select_for_update()` row locks so repeated or concurrent start attempts
cannot create duplicate sessions. Idempotent retries with the same key return
the original session.

The `play` app stores durable `GameSession` and `GameSessionParticipant` rows.
Each session stores the selected engine key/version, lobby configuration,
initial authoritative state, public state, spectator state, state version, and
start time. Participants link active lobby memberships into the session and
store actor IDs, role/seat data, bot metadata, and actor-private state.

Game start transitions the lobby from `READY_CHECK` to `STARTING` to `ACTIVE`
inside one transaction. If engine validation, initial-state creation, or state
serialization fails, the transaction rolls back so no partial session remains
and the lobby returns to its previous ready-check state. Successful starts emit
`GAME_STARTED` with only the engine's spectator state to eligible lobby
connections. Authenticated connected nonmembers do not receive game-start
state; development guest spectators can receive it when explicitly enabled.
Each human player receives `GAME_STARTED_PRIVATE` through the lobby's per-user
group with the player public state and their own private state, including an
empty private state. The persisted session stores authoritative initial,
public, spectator, and per-participant private state separately.

Ready-check expiry currently supports the `return_to_waiting` behavior: expired
ready checks clear ready flags, clear ready-check timestamps, return the lobby
to `WAITING`, and write an audit event. Other timeout behaviors such as kicking
unready users or filling seats with bots remain later policy work.

## Realtime Flow

The `play` app now owns a shared session action service and `/ws/games/<uuid>/`
consumer. The service reads the durable `authoritative_state` on a locked
`GameSession` row, checks actor membership and the expected state version, and
applies versioned pure action rules. A Redis session lock surrounds the
transaction. Each successful action writes new authoritative, public, and
spectator states plus a versioned, uniquely keyed action receipt. Repeating a
request UUID with the same content returns the receipt; reusing it with other
content fails. The consumer broadcasts after the transaction commits and
rechecks each viewer before sending role-appropriate state. Reconnect and
resync read a fresh database snapshot.
Clients use `state_version` to ignore older deliveries and can resync after a
missed broadcast; a durable outbound event queue is not part of this task.

Connect4 `0.1` is the first action-rule registration. Its seeded catalog entry
remains unplayable, so this route can act on an existing session but does not
enable production lobby start for Connect4 yet.

The Connect4 player page reuses the `game_route` issued at session start. It
authorizes a session player before returning HTML, renders the saved public
board for first paint, and embeds a JSON-escaped snapshot. A small static
client submits versioned moves through the session WebSocket and paints only
confirmed snapshots. Reconnect uses the same idempotency UUID for an unresolved
action. No game result or turn decision is accepted from the browser.

Connect4 bot turns use a pure deterministic `casual` strategy. Session start
and committed game actions enqueue a version-bound Celery job when the current
actor is a bot. The worker reloads PostgreSQL state, checks the current bot
membership and version, then calls the same transactional action service as a
human player. A UUID derived from session, actor, and version makes duplicate
jobs idempotent. The worker broadcasts through the existing game group, whose
consumer applies player and spectator audience filtering. Test settings disable
automatic queue publishing; tests explicitly enable and mock it where needed.
Broker publish failures are logged after commit; a durable outbox or automatic
reconciliation of missed bot jobs is still needed for recovery from a broker
outage. Connect4 remains unplayable in the catalog.

Completed Connect4 sessions use the existing durable `GameActionReceipt` rows
for replay history. A read service authorizes the current viewer, starts with
the stored initial state, reapplies each receipt's drop through the pure rules,
and checks its version, original action hash, event, serialized states, result,
and the session's terminal state. Result and replay pages render only validated
public frames.
No second action log is written, and malformed or incomplete history returns
no result or partial replay. These views are available only after completion.

KSA-035 exposes these durable records for operations. The admin receipt list is
view-only and omits stored response JSON. Each session admin page links to a
read-only inspection report containing receipt version continuity and, for a
completed Connect4 session, validated public replay frames. Tampered replay
history returns an unavailable marker without partial frames. The staff-only
`/admin/game-health/` endpoint requires `play.view_gamesession` and reports
database/Redis readiness, active-session count, and actions accepted in the
last five minutes. It does not count live WebSocket connections; that would
require durable presence instrumentation and is not inferred from sessions.

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
