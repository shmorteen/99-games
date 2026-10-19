# Game Engine Spec

Every playable game must implement the same core contract so that lobbies,
spectators, bots, and streaming features can reuse platform services.

## GameDefinition

Each game registers metadata including:

- `slug`
- `name`
- `category`
- `min_players`
- `max_players`
- `supports_bots`
- `supports_spectators`
- `rules_url`
- `engine_key`
- `status`

## Engine Contract

An engine must subclass `games.engine.BaseGameEngine` and provide:

- `validate_config()`: reject unsupported configuration before a lobby starts.
- `create_initial_state()`: build authoritative JSON state from server-supplied
  config and actor records.
- `get_public_state()`: return state safe for all game recipients.
- `get_spectator_state()`: return state safe for spectators and broadcast
  overlays.
- `get_private_state()`: return actor-scoped hidden state for one player only.
- `legal_actions()`: calculate legal action payloads for an actor.
- `apply_action()`: validate and apply one human or bot action.
- `handle_timeout()`: apply a deterministic server-triggered timeout.
- `bot_action()`: choose the action payload a bot actor will submit.
- `is_complete()`: report whether the state is terminal.
- `build_results()`: derive final results from authoritative state.

`apply_action()` and `handle_timeout()` return `GameTransition`, which contains
the updated state, emitted domain events, completion status, the next actor when
applicable, and optional result information. Transition payloads, engine state,
events, spectator state, private state, public state, and results must be
JSON-serializable.

Standard engine exceptions cover invalid configuration, illegal action,
unauthorized action, stale state, game already completed, invalid actor, and
invalid payload failures. Services translate these domain errors into HTTP,
WebSocket, audit, or replay responses.

Engine code must not write HTTP responses, render templates, send WebSocket
messages, trust client-supplied score/result/turn data, or mutate database
records directly. Those side effects belong to application services around the
engine.

## Engine Registry

Engine classes are registered in `games.registry.GameEngineRegistry` by
`engine_key` and `engine_version`. The registry supports explicit registration,
decorator registration, lookup, existence checks, instance creation, registered
engine listing, and `GameDefinition` validation.

Startup imports the module paths in `KSA_GAME_ENGINE_MODULES` and calls
`register_engines(registry)` when a module provides it. Duplicate key/version
registrations and invalid versions are rejected and surfaced through Django
system checks. Playable catalog entries must reference a registered engine, but
Hangman and Werewolves vs Villagers are registered at version `0.1`. Connect4
remains unregistered until its engine class exists.

## Action Handling

All human and bot actions must use the same service path:

1. Authenticate and authorize the actor.
2. Load current authoritative state.
3. Validate the action against the engine and membership rules.
4. Apply the transition transactionally.
5. Increment the state version.
6. Persist the action and resulting state.
7. Broadcast role-appropriate events.

## State Visibility

- Public state can be sent to all participants.
- Private state can be sent only to the player it belongs to.
- Spectator state must never include hidden information.
- OBS overlays must use spectator-safe data.

## Connect4 State Foundation (KSA-021)

`games.connect4_state` is a pure state module, not a registered game engine.
It accepts only the seeded standard configuration: six rows, seven columns,
and four discs in a line. It receives two server-supplied membership actor
UUIDs with seats one and two. Seat one is red and takes the first turn; seat
two is yellow. Input order does not assign turns.

The JSON state has `schema_version: "connect4.state.v1"`, `game`, `status`,
`rows`, `columns`, `connect_length`, `board`, `players`, `turn_actor_id`, and
`move_count`. Board row zero is the top row and row five is the bottom row;
empty cells are `null`. `serialize_state` returns detached public data and
omits unrelated fields. It checks structural shape, gravity, turn/count parity,
and terminal result consistency, but does not decide whether a column drop is
legal.

`games.connect4_moves` (KSA-022) lists open columns for the current actor and
returns a pure `GameTransition` for a valid zero-based `drop_disc` action. The
module rejects client-supplied row, turn, score, or winner fields. It validates
the actor, turn, column, and board before placing a disc in a detached state.
The application service added later must authenticate the user, lock the
session, check its version, apply this rule path, and persist exactly one
transition. This module does not write to the database.

KSA-023 calculates wins along horizontal, vertical, and both diagonal axes
after each accepted drop. Four or more contiguous discs win. A full board
without a line is a draw, and a win on the final cell takes precedence. A
terminal state has `status: "completed"`, `turn_actor_id: null`, and a public
`result` object with `outcome` (`win` or `draw`) and `winner_actor_id` (the
winner's UUID or `null`). The transition has `is_complete: true`, no next
actor, the same result, and a `connect4_game_completed` event after the disc
event. Terminal states have no legal actions and reject further drops. The
state serializer derives the result from the board, rejecting forged results,
unfinished winning positions, and impossible winner parity.

KSA-024 routes `GAME_ACTION` through `play.services.submit_game_action`. It
persists Connect4's full JSON state in `GameSession.authoritative_state`,
derives player and spectator snapshots through versioned action rules, and
stores a UUID-keyed receipt for idempotent retries. The game WebSocket route is
`/ws/games/<session_uuid>/`. `GAME_SNAPSHOT` serves connect and `GAME_RESYNC`;
`GAME_STATE` broadcasts a committed action; `GAME_ACTION_ACK` answers a retry;
`ERROR` carries domain error codes. Messages include `request_id`,
`server_timestamp`, `session_uuid`, and `payload`. Client `GAME_ACTION` payloads
contain only `action` and `state_version`.

KSA-025 adds the player page at the game-start route. The HTTP response
authorizes a current player, renders the saved public state, and embeds only
that player's snapshot as escaped JSON. The browser uses the same session
WebSocket, shows server-confirmed board updates, and disables move controls
while disconnected, waiting for a response, out of turn, full, or completed.
It retries an unresolved action after reconnect with its original request UUID
and state version. The browser never calculates a winner or persists a move.
The dependency-free client behavior check is
`node tests/frontend/connect4_client_test.js` when Node.js is available.

Connect4 remains unregistered and `is_playable=False` until the remaining
engine, action transport, interface, spectator, overlay, bot, and result
persistence work is complete.

## Hangman Engine (KSA-029)

`games.hangman.HangmanEngine` is registered as `hangman` version `0.1`.
The engine selects an answer from a server-owned word list during initial state
creation; configuration accepts only `max_wrong_guesses` from 1 through 12.
One to eight unique, consecutively seated actor UUIDs take turns guessing one
letter. Duplicate guesses, out-of-turn actions, client result fields, and stale
action versions are rejected before a transition is returned. A wrong guess
or timeout consumes an attempt. The game ends when every letter is found or
the attempt limit is reached.

The authoritative state contains the answer. Active public, spectator, and
actor-private serializers expose only a letter mask, guesses, attempts, turn,
and player IDs; they reveal the answer and server-derived result only after
completion. The engine has no persistence or WebSocket side effects. Hangman
remains unplayable in the catalog until normal lobby start and full product
integration exist. KSA-030 routes its guesses through the shared transactional
game-action service and renders player, spectator, rules, and signed overlay
pages for existing sessions. Player and spectator snapshots are derived from
authoritative state before delivery; no active view receives the answer.

## Werewolves vs Villagers Engine (KSA-031)

`games.werewolves.WerewolvesEngine` is registered at version `0.1` for five to
twenty seated player UUIDs. Initial role selection is server-owned: a quarter
of players (rounded down, minimum one) are werewolves. Night starts first.
Living wolves vote at night; all living players vote by day. Each actor has
one private ballot per phase and cannot vote for themselves. A phase resolves
when all eligible ballots arrive or a server-triggered timeout occurs. A unique
plurality eliminates its target; ties and empty ballots eliminate nobody.
Eliminating the final wolf wins for villagers; wolves win when living wolves
equal or outnumber living villagers. If neither team wins by the end of day
twenty, the game is a draw.

Public and spectator state expose seats, life status, phase, vote count, and
elimination results, but no live roles or ballots. Private state contains only
the requesting actor's role, own vote, and legal actions. Vote events omit both
voter and target, so a night action cannot identify a wolf. Completed state
reveals roles and the server-derived result. Phase durations are validated and
stored, but scheduling timers and persisting actions are service work for a
later task. No bot support is declared.

KSA-032 routes ballots through the shared transactional game-action service.
Player snapshots contain one actor-scoped private role and ballot; state and
event fanout remain public-safe. Spectators, signed OBS overlays, and the host
public view use read-only spectator state. The host view connects with the
same signed, session-bound overlay token, so it receives no private role over
WebSocket. Pages for existing sessions and a public rules page are available.
Automatic phase timeout scheduling and normal lobby start are still separate
integration work; the catalog entry remains not playable.

## Reusable Game-Family Primitives (KSA-033)

`games.families` holds pure patterns used by current engines and available to
future games without adding a Django application per game:

| Family | Helper | Current use |
| --- | --- | --- |
| Grid | `grid.drop_row`, `grid.winning_markers` | Connect4 placement and line detection |
| Word | `word.mask_answer` | Hangman public and spectator mask |
| Vote | `vote.plurality_target` | Werewolves phase resolution |
| Hidden role | `hidden_role.public_players` | Werewolves role-safe public projection |
| Turn based | `turn_based.actor_for_turn` | Connect4 and Hangman seat rotation |

These helpers return detached data or scalar decisions and never write a model,
send a message, or choose a game result. The engine remains responsible for
validating authoritative state, actor membership, legal actions, completion,
and result consistency. In particular, callers validate grid gravity, ballot
eligibility, and seated actor uniqueness before using the corresponding
helper. The hidden-role projection uses an explicit Boolean reveal flag and
copies only allowlisted fields; live callers must use `reveal_roles=False`.

Future engines can compose these helpers while preserving the same
`BaseGameEngine` contract and shared action service. Existing game state
schemas and action payloads do not change in KSA-033.

## Test Expectations

Each engine requires tests for:

- Initial state.
- Legal and illegal actions.
- Turn order.
- Win, loss, draw, and timeout results.
- Hidden information separation.
- Reconnect serialization.
- Spectator serialization.
- Bot actions when bots are supported.
