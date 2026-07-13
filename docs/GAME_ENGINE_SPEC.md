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

An engine must provide:

- Configuration validation.
- Initial state creation.
- Legal action calculation.
- Action validation.
- State transition logic.
- Public-state serialization.
- Private-state serialization for each player.
- Spectator-state serialization.
- Timeout behavior.
- Result calculation.
- Replay-safe action and state history data.

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
