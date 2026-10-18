# Game Catalog

The catalog tracks planned and implemented games. A game is playable only when
its engine, interface, rules, spectator view, overlay, and tests are complete.

## Initial Production Games

| Game | Status | Notes |
| --- | --- | --- |
| Connect4 | Seeded, not playable | Validated state shape exists; engine, actions, and UI are deferred. |
| Hangman | Seeded, not playable | Catalog metadata exists; private answer handling is deferred. |
| Werewolves vs Villagers | Seeded, not playable | Catalog metadata exists; hidden-role engine work is deferred. |

## Initial Categories

| Category | Slug | Status |
| --- | --- | --- |
| Board Games | `board-games` | Seeded |
| Word Games | `word-games` | Seeded |
| Deduction Games | `deduction-games` | Seeded |
| Trivia Games | `trivia-games` | Seeded |
| Party Games | `party-games` | Seeded |

## Future Catalog Requirements

Each game definition includes:

- Stable slug and display name.
- Category.
- Minimum and maximum players.
- Supported spectator mode.
- Bot support status.
- Estimated duration.
- Rules page.
- Engine registration key.
- Playable, beta, disabled, or planned status.

Playable actions, lobby creation, game engines, and realtime gameplay are
deferred to later tasks.

## Public Pages

The current public catalog routes are:

- `/games/`
- `/games/<slug>/`
- `/games/categories/<slug>/`

Only active games in active categories appear publicly. Unimplemented games are
shown as `Coming Soon` and do not expose lobby creation actions.

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
