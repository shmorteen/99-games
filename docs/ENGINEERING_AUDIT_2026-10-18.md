# Engineering audit — 2026-10-18

This audit describes the local workspace at commit `9bdd0f3` plus the
game-start delivery repair in this pass. The planned architecture in other
documents is broader than the implementation. The repository was on
`codex/ksa-022-connect4-legal-moves-restart` before this pass; two untracked
`runserver.*.log` files were left untouched.

## Actual execution map

```text
Browser / Django test client
  ├─ /accounts/* → django-allauth → Django session → auth_user + email rows
  └─ /games/* → Django catalog views → GameCategory / GameDefinition

WebSocket client → Channels AuthMiddlewareStack
  → /ws/lobbies/<uuid>/ → LobbyConsumer
  → lobbies.services → GameLobby / LobbyMembership / LobbyAuditEvent
  → start_game → registered game engine → GameSession / participants
  → Channels group events → lobby members and per-user player groups

Celery worker → ksa_games.smoke only
Redis → configured Channels and Celery; lobby-start lock in non-test settings
PostgreSQL → configured for Compose and CI; local tests default to SQLite
```

There is no Django REST Framework dependency, HTTP lobby API, game-action
service, gameplay WebSocket route, production engine registration, bot-turn
task, spectator game view, OBS overlay, or livestream endpoint in this tree.
The three seeded games are `is_playable=False`.

## Verified workflow boundaries

| Workflow | Evidence | State |
| --- | --- | --- |
| Email signup, login, logout | `tests/test_email_auth.py`; allauth routes in `ksa_games/urls.py` | Tested through Django test client; no browser run |
| Lobby creation and join | `GameLobby.objects.create_for_host`, `join_lobby`, `tests/test_game_lobby.py`, `tests/test_lobby_service.py` | Service and WebSocket tests; no user-facing HTTP creation path |
| Ready check and game start | `begin_ready_check`, `start_game`, `tests/test_ready_check_start.py` | Tested with a test-only engine; no production game |
| Human gameplay and match completion | No action service or real game engine | Not implemented |
| Bots | `add_lobby_bot` creates a membership; Celery has only a smoke task | Autonomous turns not implemented |
| Spectators and streaming | Lobby spectator membership and start event exist; no gameplay spectator view or OBS/streaming endpoint | Partial |

## Ranked findings

1. **No complete match workflow.** `games/migrations/0002_gamedefinition.py`
   seeds three unplayable games; `games/urls.py`, `ksa_games/routing.py`, and
   `play/models.py` contain no game-action transport or transition service.
   Users cannot play or finish a match. This is a documented roadmap gap,
   not a newly discovered regression. Continue the Connect4 task sequence
   before declaring a game playable.
2. **Game-start state crossed the spectator boundary.** Before this repair,
   `LobbyConsumer.handle_game_start` sent both `public_state` and
   `spectator_state` to the shared lobby group. The test engine returns a
   narrower spectator state; the WebSocket regression test failed because a
   spectator received the player public state. The repair sends only
   spectator state to eligible shared-group connections and sends player
   public/private state through per-user groups.
3. **Lobby start advertises a route with no view.** `_game_route` in
   `lobbies/services.py` constructs `/games/<slug>/sessions/<uuid>/`, while
   `games/urls.py` registers only catalog, category, and detail pages. A
   Django client request to that route returned HTTP 404. A started session
   cannot be opened at its announced route. Implement the
   player route when the first game interface is ready.
4. **Bots have no autonomous execution chain.** `add_lobby_bot` in
   `lobbies/services.py` only creates membership; `ksa_games/tasks.py` has
   only `celery_smoke`. There is no turn eligibility, scheduling, action
   selection, authoritative action service, or bot result publication.
   Add this only after human actions share a working service.
5. **Readiness expiry has no scheduled trigger.** `expire_ready_check` is
   callable in `lobbies/services.py` and tested directly, but no Celery job
   or other runtime invocation exists. An expired lobby can remain in
   `READY_CHECK` until another path acts. A separate ready-check lifecycle
   task should define the durable timeout trigger and recovery behavior.

## Verification limits

The baseline local test suite passed with 246 tests on SQLite. The repair's
WebSocket test first failed on the leaked `public_state`; a second regression
test first failed because players with empty private state were excluded from
delivery. The focused file then passed with 10 tests, and the full suite
passed with 247 tests. `manage.py check`,
`makemigrations --check --dry-run`, and migrations into a disposable in-memory
SQLite database passed. Docker Compose configuration parsed, but the Docker
daemon was unavailable, so PostgreSQL, Redis, Daphne, and a real Celery worker
were not run. Existing concurrent-join tests assert capacity behavior but do
not execute parallel PostgreSQL transactions. These limits prevent a claim of
production concurrency or worker lifecycle validation.
