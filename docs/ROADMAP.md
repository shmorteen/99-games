# Roadmap

## Phase 1: Platform Foundation

- Initialize Django project and settings.
- Configure PostgreSQL.
- Configure Redis and Django Channels.
- Configure Celery.
- Add email and password authentication.
- Add arena profiles.
- Add Google OAuth configuration.
- Add health checks.
- Add Docker Compose.
- Add GitHub Actions.

## Phase 2: Game Platform Core

- Add game categories and game definitions.
- Add the game catalog.
- Add the base engine interface.
- Add the game engine registry.
- Add lobbies and memberships.
- Add join and leave services.
- Add lobby WebSocket consumers.
- Add ready-check and game start flow.

## Phase 3: Connect4

- Add state representation.
- Add legal move validation.
- Add win and draw detection.
- Add WebSocket actions.
- Add player interface.
- Add spectator and overlay views.
- Add bot strategies.
- Add replay and result support.

## Phase 4: More Initial Games

- Add Hangman.
- Add Werewolves vs Villagers.
- Reuse the common lobby, engine, spectator, bot, and streaming services.

## Phase 5: Scale Toward 99 Games

- Expand the catalog through reusable game families.
- Add stronger admin tooling.
- Improve observability and moderation.
- Add richer replay, ranking, and featured livestream experiences.
