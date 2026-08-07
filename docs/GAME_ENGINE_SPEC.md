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
Connect4, Hangman, and Werewolves vs Villagers remain unregistered until their
actual engine classes exist.

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
