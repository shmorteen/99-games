# Depth-first implementation audit — 2026-10-19

## Baseline and evidence rules

Baseline: GitHub `origin/master` and local `codex/ksa-035-replay-observability`
both pointed to `431d8f21019ee0a7d2201278d3f26ac5392a50ea` before KSA-036.
This audit traces source, rendered-template tests, and service tests. A checked
roadmap box is not treated as an end-to-end release result. Local tests use
SQLite and an in-memory channel layer (`ksa_games/test_settings.py`). Docker's
daemon was unavailable on this host, so PostgreSQL/Redis/Celery and two-browser
runtime claims remain **BLOCKED**, not passed.

| Capability | Current evidence | Assessment |
| --- | --- | --- |
| Accounts and catalog | `accounts`, allauth templates, `games/views.py` | Working components; browser signup and navigation not exercised here. |
| Lobby model and service | `lobbies/models.py`, `lobbies/services.py` | Durable join, leave, ready and start rules exist. Before KSA-036 there was no browser create or join route. |
| Connect4 rules | `games/connect4_state.py`, `games/connect4_moves.py` | Pure state, legality and result rules exist. No registered `BaseGameEngine` adapter in `KSA_GAME_ENGINE_MODULES`. |
| Connect4 session actions | `play/services.py`, `play/consumers.py` | Versioned transaction, receipt and audience fanout exist for already-created sessions. |
| Connect4 bot and replay | `play/bots.py`, `play/replays.py` | Bot scheduling and validated completed replay exist. Broker publish failure is logged, without durable recovery. |
| Hangman | `games/hangman.py`, `play/views.py` | Registered engine and existing-session interfaces. Browser lobby path and complete runtime journey unverified. |
| Werewolves | `games/werewolves.py`, `play/views.py` | Registered engine and role-safe state. No automatic phase timer delivery. |
| CI and docs | `.github/workflows/ci.yml`, `README.md` | CI watches `main`, but the actual GitHub default is `master`. README status and `docs/CURRENT_STATE_AUDIT.md` stop around KSA-020/022; `docs/TASKS.md` reaches KSA-035. |

All three seeded `GameDefinition` rows are intentionally `is_playable=False`
(`games/migrations/0002_gamedefinition.py`, `docs/GAME_CATALOG.md`). This is a
correct release gate, despite many checked implementation tasks.

## Journey trace and first actual blockers

| Journey | Existing path | First blocker | Corrective sequence |
| --- | --- | --- | --- |
| A: two humans | allauth → catalog → lobby service → ready check → session → WebSocket → replay | Catalog action was a fragment link and no browser lobby creation/join page existed (`templates/games/detail.html`, `ksa_games/urls.py`). Seeded Connect4 also fails the playable gate. | KSA-036 adds browser entry behind that gate. Then register the Connect4 engine, connect browser ready/start controls, and verify a full match. |
| B: human/bot | catalog → lobby bot membership → start → `play.bots` → shared action service | Same catalog/lobby entry blocker. A lost Celery publish has no automatic reconciliation (`play/bots.py`). | Build the ordinary lobby path, then test bot start and durable recovery under broker interruption. |
| C: spectator/streamer | lobby spectator role → session spectator page → signed overlay | No browser lobby discovery/join flow; views are reachable for existing sessions only. | Add authorized discovery/join after lobby entry; verify audience payloads with real Channels/Redis. |
| D: hidden information | lobby start → Hangman/Werewolves engine → private snapshot → vote/guess | No browser lobby journey. Werewolves timeout action exists but no scheduled delivery. | Verify lobby path, then implement durable phase timeout scheduling as a separate slice. |

KSA-036 corrects only the first browser lobby entry gap. It does not enable
Connect4's seeded entry or claim that any journey completes end to end.

## Prioritized findings (maximum five)

1. **P1 — No browser lobby entry.** `templates/games/detail.html` offered
   fragment-only actions, while `ksa_games/urls.py` had no lobby HTTP routes.
   Oracle: an authenticated user can create a waiting lobby, see its UUID page,
   and a second user can join without exceeding capacity. KSA-036 addresses this.
2. **P1 — Connect4 cannot start through the registry.** `ksa_games/settings.py`
   registers Hangman and Werewolves modules, but no Connect4 engine adapter.
   Oracle: a real Connect4 `GameDefinition` passes registry validation and
   `start_game` creates a session with two seated actors. Keep `is_playable=False`
   until complete release criteria pass.
3. **P1 — CI misses the default branch.** `.github/workflows/ci.yml` and its
   test assume `main`; GitHub reports `master`. Oracle: a push/PR targeting
   `master` triggers PostgreSQL/Redis-backed checks. Correct separately.
4. **P2 — Bot recovery is incomplete.** `play/bots.py` logs broker publish
   failures after commit. Oracle: interrupt publish or worker and verify a
   durable recovery job eventually advances the same version once.
5. **P2 — Werewolves phase progression can stall.** The engine handles a
   server-triggered timeout, but no persisted due time or scheduler drives it.
   Oracle: a timed-out phase advances once after worker interruption/restart,
   with no private ballot disclosure.

## Independently checkable invariants and game matrix

| Invariant / oracle | Connect4 | Hangman | Werewolves |
| --- | --- | --- | --- |
| Legal actions and result agree with final authoritative state; replay accepted history from initial state | Unit and receipt replay tests **PASS**; whole match runtime **BLOCKED** | Unit results **PASS**; durable replay not implemented **NOT RUN** | Unit results **PASS**; durable replay not implemented **NOT RUN** |
| Nonmembers cannot act, and spectator/overlay receive only public state; oracle is an unauthorized action rejection plus recursive secret absence in snapshots/events | Existing action and overlay tests **PASS**; Redis runtime **BLOCKED** | Existing interface tests **PASS**; Redis runtime **BLOCKED** | Existing role/overlay tests **PASS**; Redis runtime **BLOCKED** |
| Exactly one state version advances per accepted action; duplicate request returns prior receipt and stale request cannot mutate state | Shared service/WebSocket tests **PASS**; PostgreSQL concurrency **BLOCKED** | Shared service tests **PASS**; PostgreSQL concurrency **BLOCKED** | Shared service tests **PASS**; PostgreSQL concurrency **BLOCKED** |
| Reconnect never increases actor privilege; oracle is a fresh snapshot for the same authenticated identity and no newly visible private fields | WebSocket reconnect/resync test **PASS**; two-browser run **BLOCKED** | Audience snapshot tests **PASS**; actual reconnect protocol **NOT RUN** | Audience snapshot and JavaScript retry tests **PASS**; actual two-browser reconnect **BLOCKED** |
| Bot/timeout work eventually advances after interruption; oracle is one committed transition following a controlled worker restart | Recovery **NOT RUN**; current publish path lacks reconciliation | No bot support declared | Timeout delivery **NOT RUN**; scheduling absent |

Lobby invariants: active seated membership count must never exceed
`maximum_players` (oracle: concurrent joins yield at most that many rows);
one host belongs to each active lobby (oracle: unique active host constraint);
creation retry with the same request UUID returns one lobby and one host seat
(oracle: durable unique request ID plus audit count). KSA-036 adds HTTP tests;
PostgreSQL concurrent-request verification remains blocked locally.

## Gameplay quality and release standard

The catalog's dead action links were a demonstrated interaction failure;
KSA-036 replaces them with real create/join entry points and removes Find Lobby
and Quick Match claims that have no route. Existing match templates do show
turn or phase text, reconnecting state, alerts, and labeled controls
(`templates/play/*`, `play/static/play/*`), but no complete browser journey
has verified that navigation, focus, error recovery, and finished-match
handoff feel coherent. Do not redesign these screens based only on source review.

Declare an existing game playable only after a real authenticated lobby can be
created and filled, ready/start produces its registered engine state, legal and
illegal WebSocket actions satisfy version and authorization oracles, result and
public replay (where supported) agree with persisted state, reconnect and
spectator/overlay views protect hidden data, and browser plus PostgreSQL/Redis
integration tests pass. For Connect4, also complete a human/human and declared
human/bot match. For Werewolves, test phase timeout delivery after worker
interruption. Record a reproducible release environment and keep the catalog
flag false until every applicable condition is met.

## Verification ledger

| Check | Outcome | Evidence / limit |
| --- | --- | --- |
| Source and documentation trace | **PASS** | Files and routes named above inspected at baseline SHA. |
| GitHub default vs CI branches | **FAIL** | GitHub default `master`; workflow triggers only `main`. |
| Docker Compose service status | **BLOCKED** | Docker daemon unavailable on local Windows host. |
| Real PostgreSQL/Redis/Celery journeys | **BLOCKED** | No accessible local Compose services. |
| Two-browser end-to-end flow | **NOT RUN** | No complete runtime stack available. |
| KSA-036 focused tests | **PASS** | `python -m pytest tests/test_browser_lobby_entry.py tests/test_game_catalog_pages.py tests/test_lobby_service.py -q`: 46 passed. |
| Django system, migration check and migrate | **PASS** | `manage.py check`: no issues; `makemigrations --check --dry-run`: no changes; `migrate`: `lobbies.0006` applied, later no pending migrations. |
| Full Python suite on final patch | **PASS** | `python -m pytest -q`: 401 passed. |
| Standalone frontend behavior scripts | **PASS** | Four Node scripts passed after permitted filesystem access. Initial sandboxed invocation was **BLOCKED** by Windows `EPERM` while resolving the workspace path; no assertion ran in that attempt. |

KSA-036 changes only public browser lobby entry. The seeded Connect4 catalog
flag remains false, and no live PostgreSQL/Redis/Celery or complete browser
match was verified. The next independent slice is a registered Connect4 engine
adapter with start-game integration tests; CI branch alignment is a separate
release-verification correction.
