# Game Catalog

The catalog tracks planned and implemented games. A game is playable only when
its engine, interface, rules, spectator view, overlay, and tests are complete.

## Initial Production Games

| Game | Status | Notes |
| --- | --- | --- |
| Connect4 | Seeded, not playable | Pure rules, versioned WebSocket actions, player and spectator pages, host-issued OBS overlay, deterministic `casual` bot turns, and validated result/replay pages exist for completed sessions. Bot support is declared; the registered engine, rules, timeout, and final integration requirements remain. |
| Hangman | Seeded, not playable | Registered `0.1` engine and shared action transport provide server-selected words, rotating letter guesses, answer-safe active snapshots, and results. Player, spectator, rules, and signed OBS overlay views work for existing sessions. Normal lobby start and full product integration remain pending. |
| Werewolves vs Villagers | Seeded, not playable | Registered `0.1` engine and shared action transport provide private roles and ballots, day/night votes, and results. Player, spectator, host public, rules, and signed OBS overlay pages work for existing sessions. Automatic phase timer delivery and normal lobby start remain pending. |

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
