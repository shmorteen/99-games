# 99 Games

99 Games, also referred to as KSA Games in the project docs, is planned as a
real-time multiplayer gaming platform that can grow to at least 99 games through
shared lobby, engine, spectator, bot, and streaming infrastructure.

Initial production games:

1. Connect4
2. Hangman
3. Werewolves vs Villagers

## Status

This repository currently contains the project baseline documentation. The first
implementation task is `KSA-001 Initialize Django project and settings`.

## Documentation

- `AGENTS.md`: engineering instructions and definition of done
- `docs/PRODUCT_SPEC.md`: product requirements
- `docs/ARCHITECTURE.md`: approved architecture direction
- `docs/ROADMAP.md`: implementation phases
- `docs/TASKS.md`: ordered task queue
- `docs/ACCEPTANCE_CRITERIA.md`: verifiable completion criteria
- `docs/DECISIONS.md`: architecture decision records
- `docs/GAME_ENGINE_SPEC.md`: common game engine contract
- `docs/GAME_CATALOG.md`: planned and implemented games

## Planned Stack

- Python 3.11+
- Django
- Django REST Framework
- Django Channels and Daphne
- PostgreSQL
- Redis
- Celery
- django-allauth
- pytest
- Docker Compose
- GitHub Actions

## Development

Implementation has not started yet. After `KSA-001`, this section should be
updated with exact setup, test, migration, and run commands.
