# Game Catalog

The catalog tracks planned and implemented games. A game is playable only when
its engine, interface, rules, spectator view, overlay, and tests are complete.

## Initial Production Games

| Game | Status | Notes |
| --- | --- | --- |
| Connect4 | Planned | First implementation target after platform foundation. |
| Hangman | Planned | Requires private answer state and public progress state. |
| Werewolves vs Villagers | Planned | Requires hidden roles, phases, voting, and spectator safety. |

## Future Catalog Requirements

Each game definition should include:

- Stable slug and display name.
- Category and tags.
- Minimum and maximum players.
- Supported spectator mode.
- Bot support status.
- Estimated duration.
- Rules page.
- Engine registration key.
- Playable, beta, disabled, or planned status.

## Readiness Checklist

- Engine registered.
- Configuration validated.
- Legal actions implemented.
- Win, loss, draw, and timeout results implemented.
- Public and private serializers implemented.
- Spectator serializer implemented.
- Player interface complete.
- Spectator interface complete.
- OBS overlay complete.
- Bot strategy complete when bot support is declared.
- Unit, integration, WebSocket, reconnect, and authorization tests passing.
