# Acceptance Criteria

## KSA-001 - Initialize Django project and settings

Complete when:

1. A Django project package and `manage.py` exist.
2. Settings are environment-driven and have a documented local development path.
3. URL, ASGI, and WSGI entrypoints import without side effects.
4. The project can run `python manage.py check`.
5. pytest can discover and run at least one smoke test.
6. No PostgreSQL, Redis, Channels, Celery, auth, game, lobby, or UI work is added.
7. README or docs include the exact local check commands.

## KSA-002 - Configure PostgreSQL

Complete when:

1. The PostgreSQL driver is declared in the dependency metadata.
2. Database settings are read from environment variables.
3. Local development defaults are documented without hard-coded production
   secrets.
4. Django can run `python manage.py check` against the configured database.
5. `python manage.py makemigrations --check --dry-run` succeeds.
6. Tests cover database setting construction for expected environment values.
7. No domain models are introduced in this task.

## KSA-003 - Configure Redis and Django Channels

Complete when:

1. Django Channels and Daphne are declared in dependency metadata.
2. ASGI is configured to route HTTP and future WebSocket traffic.
3. The channel layer is configured from Redis environment variables.
4. Test settings can use an isolated in-memory channel layer.
5. A smoke test verifies the channel layer can be loaded.
6. `python manage.py check` passes.
7. No lobby, gameplay, spectator, or overlay consumer is added.

## KSA-004 - Configure Celery

Complete when:

1. Celery is declared in dependency metadata.
2. A Celery app loads Django settings without import errors.
3. Broker and result backend settings are read from environment variables.
4. A smoke task exists only to validate worker discovery.
5. Tests verify the Celery app imports and has the expected configuration.
6. Documentation includes the local worker command.
7. No bot, timeout, scheduled gameplay, or cleanup task is added.

## KSA-005 - Add email/password authentication

Complete when:

1. django-allauth is installed and configured for email/password auth.
2. Users can sign up, log in, and log out with email credentials.
3. Duplicate email signup is rejected.
4. Authentication views use server-side validation and CSRF protection.
5. Tests cover signup, login, logout, and invalid credentials.
6. Documentation states the configured email verification behavior.
7. No Google OAuth or ArenaProfile fields are added.

## KSA-006 - Add ArenaProfile

Complete when:

1. Each user has one ArenaProfile.
2. ArenaProfile exposes a UUID public identifier.
3. Display names have uniqueness and validation rules.
4. Profile creation is covered for new users.
5. Admin registration allows safe profile inspection.
6. Tests cover profile creation, uniqueness, and string representation.
7. No ratings, balances, game stats, or OAuth behavior is added.

## KSA-007 - Add Google OAuth configuration

Complete when:

1. django-allauth social account support is configured for Google.
2. Google client ID and secret are read from environment variables or documented
   admin configuration.
3. No OAuth secret is committed to the repository.
4. Login templates expose the Google login path when configured.
5. Tests verify configuration and page behavior without calling Google.
6. Documentation explains local setup for Google OAuth.
7. No additional OAuth provider is added.

## KSA-008 - Add health checks

Complete when:

1. A liveness endpoint returns success when the Django process is running.
2. A readiness endpoint checks database connectivity.
3. A readiness endpoint checks Redis connectivity once Redis is configured.
4. Health responses do not expose secrets or stack traces.
5. Tests cover healthy and unhealthy readiness behavior.
6. Docker or deployment docs reference the health endpoints.
7. No metrics dashboard or external monitoring integration is added.

## KSA-009 - Add Docker Compose

Complete when:

1. Docker Compose defines services for web, PostgreSQL, Redis, and Celery worker.
2. Services use environment variables documented in an example env file.
3. Volumes preserve PostgreSQL data in local development.
4. `docker compose config` succeeds.
5. The documented compose workflow can run Django checks.
6. No production deployment manifest is added.
7. Secrets are not committed.

## KSA-010 - Add GitHub Actions

Complete when:

1. A CI workflow runs on pull requests and pushes to the main development branch.
2. CI installs project dependencies.
3. CI starts PostgreSQL and Redis services.
4. CI runs `python manage.py check`.
5. CI runs `python manage.py makemigrations --check --dry-run`.
6. CI runs `pytest`.
7. The workflow does not require repository secrets for normal test execution.
8. No deployment job is added.


## KSA-011 — Add GameCategory

Complete when:

1. A `GameCategory` model exists with:

   * UUID or stable primary key;
   * unique name;
   * unique slug;
   * description;
   * optional icon or image;
   * display order;
   * active status;
   * created and updated timestamps.

2. Category names and slugs are unique at the database level.

3. Slugs are generated or validated consistently.

4. Inactive categories do not appear in the public game catalog.

5. Categories can be created, edited, reordered, activated, and deactivated through Django admin.

6. Deleting a category that still contains games is prevented or handled safely through an explicit reassignment policy.

7. At least the following initial categories are seeded:

   * Board Games;
   * Word Games;
   * Deduction Games;
   * Trivia Games;
   * Party Games.

8. A migration creates the required database table and constraints.

9. Tests verify:

   * category creation;
   * unique names;
   * unique slugs;
   * active category filtering;
   * admin registration;
   * safe deletion behavior.

10. The following commands pass:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
```

---

## KSA-012 — Add GameDefinition

Complete when:

1. A `GameDefinition` model exists with:

   * UUID;
   * category;
   * unique slug;
   * name;
   * short description;
   * full description;
   * engine key;
   * engine version;
   * minimum players;
   * maximum players;
   * estimated duration;
   * bot support flag;
   * spectator support flag;
   * ranked support flag;
   * private lobby support flag;
   * broadcast support flag;
   * difficulty options;
   * rules JSON;
   * default configuration JSON;
   * thumbnail;
   * banner;
   * playable status;
   * featured status;
   * active status;
   * created and updated timestamps.

2. Database validation prevents:

   * minimum players below one;
   * maximum players below minimum players;
   * playable games without an engine key;
   * duplicate slugs;
   * negative estimated duration.

3. Configuration JSON is validated before saving.

4. Game definitions can be managed through Django admin.

5. Public queries return only active game definitions.

6. Unimplemented games may exist in the catalog but must have `is_playable=False`.

7. Connect4, Hangman, and WvV are created as initial game definitions.

8. No game is marked playable unless its registered engine exists.

9. Tests verify:

   * valid game creation;
   * invalid player ranges;
   * unique slugs;
   * active filtering;
   * playable-engine validation;
   * configuration validation;
   * admin registration.

10. Database indexes exist for:

    * slug;
    * category;
    * is_active;
    * is_playable;
    * is_featured.

---

## KSA-013 — Add Game Catalog Pages

Complete when:

1. The following pages exist:

```text
/games/
/games/<slug>/
/games/categories/<slug>/
```

2. The game catalog displays:

   * game name;
   * category;
   * thumbnail;
   * short description;
   * minimum and maximum players;
   * estimated duration;
   * bot availability;
   * spectator availability;
   * ranked availability;
   * playable status.

3. Inactive games are never shown publicly.

4. Unimplemented games are shown as “Coming Soon” and cannot create a lobby.

5. Playable games display actions such as:

   * Create Lobby;
   * Find Lobby;
   * Quick Match;
   * View Rules.

6. The catalog supports:

   * text search;
   * category filter;
   * minimum player filter;
   * maximum duration filter;
   * bot-support filter;
   * playable-only filter.

7. Invalid filter values are handled safely without server errors.

8. The game detail page displays:

   * full description;
   * rules;
   * configuration options;
   * active public lobby count;
   * player limits;
   * game features;
   * create-lobby action.

9. Category pages display only games belonging to the selected active category.

10. Missing or inactive games return HTTP 404.

11. Pagination is implemented for large catalogs.

12. Catalog templates are responsive and usable on desktop and mobile.

13. Tests verify:

* catalog page loads;
* search;
* category filtering;
* playable filtering;
* hidden inactive games;
* coming-soon behavior;
* game detail page;
* invalid slug handling;
* pagination.

---

## KSA-014 — Add BaseGameEngine

Complete when:

1. An abstract `BaseGameEngine` contract exists.

2. The interface defines at least:

```python
validate_config()
create_initial_state()
get_public_state()
get_private_state()
legal_actions()
apply_action()
handle_timeout()
bot_action()
is_complete()
build_results()
```

3. A `GameTransition` value object exists and includes:

   * updated state;
   * emitted events;
   * completion status;
   * next turn or actor where applicable;
   * optional result information.

4. Game engines do not directly:

   * write HTTP responses;
   * access templates;
   * send WebSocket messages;
   * trust client-supplied scores;
   * mutate database records without going through services.

5. The base interface documents:

   * input expectations;
   * return structure;
   * error behavior;
   * public/private state requirements;
   * idempotency expectations;
   * timeout behavior.

6. Standard engine exceptions exist, including:

   * invalid configuration;
   * illegal action;
   * unauthorized action;
   * stale state;
   * game already completed;
   * invalid actor;
   * invalid payload.

7. Engine state must be JSON-serializable.

8. Tests verify:

   * incomplete engines cannot be instantiated;
   * valid test engines satisfy the contract;
   * `GameTransition` serialization;
   * standard exceptions;
   * public/private state separation expectations.

9. Architecture documentation explains how a new game implements the engine contract.

---

## KSA-015 — Add GameEngineRegistry

Complete when:

1. A `GameEngineRegistry` exists.

2. Engines can be registered using:

   * an explicit registration method; or
   * a registration decorator.

3. Each engine is registered by:

   * engine key;
   * engine version.

4. Duplicate engine key and version registration is rejected.

5. The registry can:

   * register an engine;
   * retrieve an engine;
   * list registered engines;
   * check whether an engine exists;
   * validate a `GameDefinition`;
   * return a clear error when an engine is missing.

6. Application startup registers available engines reliably.

7. The registry does not depend on import order in an unsafe way.

8. A Django system check reports:

   * playable games with missing engines;
   * duplicate engine registrations;
   * invalid engine versions.

9. Connect4, Hangman, and WvV may be registered as development engines only when their actual engine classes exist.

10. Tests verify:

* successful registration;
* lookup;
* duplicate rejection;
* unknown engine error;
* engine-version lookup;
* playable-game validation;
* Django system check failures.

11. Game catalog queries do not mark an unregistered game playable.

---

## KSA-016 — Add GameLobby

Complete when:

1. A `GameLobby` model exists with:

   * UUID;
   * lobby code;
   * name;
   * selected game;
   * host;
   * visibility;
   * status;
   * minimum players;
   * maximum players;
   * ranked status;
   * bot-fill setting;
   * bot difficulty;
   * spectator setting;
   * spectator limit;
   * game configuration;
   * optional password hash;
   * invite token metadata;
   * scheduled start;
   * started time;
   * ended time;
   * created and updated timestamps.

2. Visibility choices include:

   * public;
   * private;
   * friends-only;
   * invite-only.

3. Status choices include:

   * waiting;
   * ready check;
   * starting;
   * active;
   * paused;
   * completed;
   * cancelled;
   * abandoned.

4. Lobby code is unique and human-readable.

5. Lobby passwords are hashed, never stored as plain text.

6. Lobby configuration is validated using the selected game engine.

7. Lobby player limits cannot exceed the game definition’s limits.

8. Ranked lobbies are rejected for games that do not support ranked play.

9. Spectators cannot be enabled for games that do not support spectators.

10. Bots cannot be enabled for games that do not support bots.

11. Lobby creation is restricted to authenticated users.

12. Lobby creation is blocked for inactive or unplayable games.

13. Tests verify:

* valid lobby creation;
* unauthenticated rejection;
* invalid game;
* invalid player range;
* ranked support validation;
* spectator support validation;
* bot support validation;
* unique lobby code;
* password hashing;
* configuration validation.

---

## KSA-017 — Add LobbyMembership

Complete when:

1. A `LobbyMembership` model exists with:

   * lobby;
   * user or bot reference;
   * membership role;
   * seat number;
   * ready status;
   * connection status;
   * joined timestamp;
   * left timestamp;
   * kicked timestamp;
   * score;
   * result;
   * metadata.

2. Supported roles include:

   * host;
   * co-host;
   * player;
   * spectator;
   * moderator;
   * bot.

3. A user cannot hold multiple active memberships in the same lobby.

4. A player cannot occupy more than one seat in the same lobby.

5. Two active members cannot occupy the same seat.

6. Spectators do not consume player seats.

7. Only one active host exists per lobby.

8. Bot memberships are clearly distinguishable from human memberships.

9. A membership that leaves or is kicked is no longer considered active.

10. Ready status applies only to eligible player roles.

11. Membership creation and changes are handled through services rather than direct view mutations.

12. Tests verify:

* player membership;
* spectator membership;
* duplicate membership prevention;
* duplicate seat prevention;
* one-host constraint;
* bot membership;
* active/inactive status;
* ready-state validation.

---

## KSA-018 — Add Lobby Join and Leave Service

Complete when:

1. A dedicated lobby service handles joining and leaving.

2. An authenticated user can join a public waiting lobby as a player.

3. A user can join as a spectator when spectators are enabled.

4. A private lobby requires the correct password.

5. An invite-only lobby requires a valid, unexpired invite token.

6. A banned user cannot join.

7. A suspended user cannot join.

8. A user cannot join the same lobby twice.

9. Player capacity cannot be exceeded.

10. Spectator capacity cannot be exceeded.

11. Concurrent join attempts cannot create more active players than the lobby limit.

12. Joining uses:

* `transaction.atomic`;
* row locking where needed;
* database constraints;
* idempotent behavior.

13. Leaving:

* marks the membership inactive;
* releases the player seat;
* updates lobby presence;
* removes ready status;
* triggers host transfer when required.

14. If the host leaves, host ownership transfers according to a deterministic rule, such as:

15. active co-host;

16. earliest active player;

17. another active eligible member;

18. lobby cancellation when no eligible member remains.

19. Leaving an active game follows the selected game’s disconnect or forfeit rules.

20. Join and leave actions create audit events.

21. Tests verify:

* public join;
* spectator join;
* private password;
* invite token;
* invalid password;
* expired invite;
* full lobby;
* full spectator capacity;
* duplicate join;
* concurrent joins;
* banned user;
* suspended user;
* leave;
* seat release;
* host transfer;
* idempotent join and leave.

---

## KSA-019 — Add Lobby WebSocket Consumer

Complete when:

1. An authenticated WebSocket endpoint exists:

```text
/ws/lobbies/<lobby_uuid>/
```

2. Anonymous connections are rejected unless explicit spectator guest access is enabled in development.

3. The consumer validates:

   * lobby existence;
   * membership;
   * spectator permission;
   * user suspension;
   * lobby ban;
   * connection origin.

4. On connection, the client receives a `LOBBY_SNAPSHOT`.

5. Supported client events include:

   * `LOBBY_JOIN`;
   * `LOBBY_LEAVE`;
   * `LOBBY_READY`;
   * `LOBBY_UNREADY`;
   * `LOBBY_CHAT`;
   * `HOST_TRANSFER`;
   * `BOT_ADD`;
   * `BOT_REMOVE`;
   * `GAME_RESYNC`.

6. Supported server events include:

   * `LOBBY_SNAPSHOT`;
   * `LOBBY_MEMBER_JOINED`;
   * `LOBBY_MEMBER_LEFT`;
   * `READY_STATE_CHANGED`;
   * `HOST_CHANGED`;
   * `LOBBY_STATUS_CHANGED`;
   * `SPECTATOR_COUNT`;
   * `ERROR`.

7. The consumer routes mutations through lobby services.

8. The consumer does not directly bypass database constraints.

9. Invalid event types return a structured error.

10. Invalid payloads return a structured validation error.

11. Users cannot:

* ready another player;
* transfer host without permission;
* add bots without permission;
* remove another human player through bot endpoints;
* join as a player when capacity is full.

12. Presence and connection state are updated on connect and disconnect.

13. Reconnecting restores the current lobby snapshot.

14. WebSocket messages use a documented schema containing:

* event type;
* request ID where applicable;
* server timestamp;
* lobby UUID;
* payload.

15. Tests verify:

* authorized connection;
* unauthorized connection;
* invalid lobby;
* initial snapshot;
* ready/unready;
* join/leave broadcasts;
* host permission;
* bot permission;
* invalid payload;
* reconnect;
* presence update;
* spectator restrictions.

---

## KSA-020 — Add Ready Check and Game Start

Complete when:

1. The lobby host can initiate a ready check while the lobby status is `WAITING`.

2. Initiating a ready check changes the lobby status to `READY_CHECK`.

3. Active human players can mark themselves ready or unready.

4. Spectators cannot participate in ready checks.

5. Bots are automatically considered ready unless explicitly configured otherwise.

6. The host can start the game only when:

   * the game is playable;
   * the required minimum player count is met;
   * player count does not exceed the maximum;
   * every required human player is ready;
   * the lobby is not already active;
   * the lobby configuration is valid.

7. Only the host or an authorized co-host can start the game.

8. Game start uses:

   * `transaction.atomic`;
   * `select_for_update`;
   * a Redis distributed lock;
   * an idempotency key.

9. Two simultaneous start requests cannot create two sessions.

10. Starting creates exactly one `GameSession`.

11. Initial game state is created through the registered game engine.

12. The selected engine version is stored on the session.

13. Game memberships are copied or linked into the session correctly.

14. Lobby status changes atomically:

```text
READY_CHECK → STARTING → ACTIVE
```

15. If initial-state creation fails:

* no partial session remains;
* the lobby returns to a safe status;
* the error is logged;
* clients receive an error message.

16. Successful start broadcasts:

* `GAME_STARTED`;
* session UUID;
* game slug;
* game route;
* public initial state;
* each player’s private state separately.

17. Spectators never receive private player state.

18. A ready-check timeout is supported.

19. After timeout, configurable behavior may:

* cancel the ready check;
* remove unready users;
* fill empty seats with bots;
* return the lobby to waiting.

20. Game start creates an audit event.

21. Tests verify:

* successful ready check;
* player ready/unready;
* spectator rejection;
* insufficient players;
* unready player rejection;
* unauthorized start;
* duplicate start prevention;
* concurrent start requests;
* one session created;
* engine initial-state creation;
* rollback after engine failure;
* public/private state separation;
* ready-check timeout;
* bot-ready behavior;
* correct lobby status transitions.

## KSA-021 — Add Connect4 State Representation

Complete when:

1. A pure Connect4 state module creates the standard 6-row, 7-column board
   with four-in-a-row configuration and rejects unsupported settings.
2. Initial state requires exactly two distinct UUID actor IDs in seats one and
   two. Input order does not change marker or turn assignment.
3. State records schema version, game key, status, dimensions, board, player
   markers, current actor, and move count as strict JSON values.
4. Board rows and serialized results are detached copies, and caller-provided
   actor records are not modified.
5. Serialization validates the state shape, actor and marker mapping, board
   cells, disc counts, and turn parity. It omits unknown or private fields.
6. Tests cover valid and invalid configuration, actor records, state shape,
   serialization, and a structurally valid next-turn state.
7. No engine is registered and the seeded Connect4 definition remains
   unplayable. Move legality, win/draw detection, and action transport remain
   later tasks.
8. Django checks, migration checks, migrations on a disposable database, and
   pytest pass.

## KSA-022 — Add Legal Move Validation

Complete when:

1. A pure Connect4 move module lists only open columns for the current actor.
   Unknown actors are rejected and non-current actors have no legal actions.
2. A `drop_disc` action accepts only an integer column from zero through six.
   Missing, boolean, non-integer, extra, and client-owned result or turn fields
   are rejected as invalid payloads. Out-of-range and full columns are illegal.
3. Out-of-turn actors are rejected as unauthorized, and unknown actors cannot
   submit a move.
4. A valid action places the actor's server-owned marker in the lowest empty
   row, increments move count, changes the turn, and returns a JSON-serializable
   `GameTransition` with a server-derived move event.
5. Rejected actions leave the supplied state unchanged. State validation
   rejects floating discs before calculating or applying an action.
6. Tests cover valid consecutive moves, legal-column calculation, malformed
   actions, full and out-of-range columns, out-of-turn and unknown actors,
   corrupt state, and non-mutation on rejection.
7. Connect4 remains unregistered and unplayable. Result calculation and the
   transactional action-persistence path remain later tasks.
8. Django checks, migration checks, migrations on a disposable database, and
   pytest pass.

## KSA-023 — Add Win and Draw Detection

Complete when:

1. Every accepted drop checks horizontal, vertical, and both diagonal axes
   for four contiguous discs belonging to the actor who moved.
2. A board filled without a winning line produces a draw; a winning final
   drop takes precedence over a draw.
3. Win and draw transitions set the state to completed, clear the next actor,
   include a server-derived result in both state and `GameTransition`, and
   emit a completion event after the disc event.
4. Completed states have no legal actions and reject any further move without
   changing the supplied state.
5. State serialization rejects forged terminal results, unfinished states
   containing a win or full board, and winners inconsistent with move parity.
6. Tests cover every win direction, a full-board draw, a win on the last cell,
   terminal action rejection, JSON serialization, and tampered result state.
7. Connect4 remains unregistered and unplayable; session persistence,
   transport, interface, spectator, bot, and replay work remain later tasks.
8. Django checks, migration checks, migrations on a disposable database, and
   pytest pass.

## KSA-024 — Add Connect4 WebSocket Actions

Complete when:

1. A session-scoped WebSocket route accepts authenticated current players and
   permitted session spectators, and rejects outsiders, inactive users, and
   disallowed origins.
2. `GAME_ACTION` carries a UUID request ID, server-validated action, and
   expected state version. The consumer delegates every mutation to the shared
   game-action service and broadcasts only after it commits.
3. The service derives the actor from a current session participant (or a
   server-owned bot actor), checks session and lobby status, and applies
   versioned Connect4 rules to authoritative state.
4. A Redis action lock and database row lock serialize actions. Stale versions
   and reused request IDs with different content are rejected. A same-key retry
   returns its durable response without applying or broadcasting another move.
5. The accepted action atomically updates authoritative, public, and spectator
   state, increments the session version, and persists an action receipt.
   A terminal action completes the session and lobby.
6. Connect and `GAME_RESYNC` provide role-scoped snapshots. Broadcasts expose
   only the public or spectator state for each viewer.
7. Tests cover service success, invalid and unauthorized actions, stale state,
   idempotency, lock failure, bot service use, terminal completion, WebSocket
   delivery, spectator rejection, and reconnect state.
8. Connect4 remains unplayable in the catalog until the remaining player and
   spectator interfaces, overlay, and other engine requirements are complete.
9. Django checks, migration checks, migrations on a disposable database, and
   pytest pass.

## KSA-025 — Add Connect4 Player Interface

Complete when:

1. The game-start route `/games/connect4/sessions/<uuid>/` serves a player-only
   Connect4 page for an existing matching session. Anonymous, outsider,
   spectator, inactive, or non-Connect4 access is rejected.
2. The first HTTP render shows the server's public board, current turn,
   player marker, move count, and terminal result without exposing
   authoritative or other private state.
3. Seven accessible column buttons and a labeled six-by-seven board work at
   mobile and desktop widths. Empty, full, out-of-turn, disconnected, pending,
   and completed conditions disable the appropriate controls.
4. The client sends only `drop_disc` with an integer column, a UUID request
   ID, and the current state version. It waits for server messages before
   changing the board or result.
5. `GAME_SNAPSHOT`, `GAME_STATE`, and `GAME_ACTION_ACK` update the view.
   Connection loss disables controls; reconnect resends an unresolved move
   with its original request ID or accepts a newer authoritative snapshot.
6. Errors are announced, stale state triggers resync, and status and cells
   have text labels in addition to color.
7. Page tests cover authorization, first render, turns, full columns,
   completed results, and public-state isolation. A dependency-free client
   behavior check covers move submission, live updates, and reconnect retry.
8. The seeded Connect4 definition remains unplayable until the remaining
   spectator, overlay, engine, and other required work is complete.
9. Django checks, migration checks, migrations on a disposable database,
   Python tests, and configured frontend checks pass.

## KSA-026 — Add Connect4 Spectator and Overlay Views

Complete when:

1. An authenticated, current spectator can open a read-only Connect4 page for
   an existing matching session. Players, outsiders, disabled spectators, and
   anonymous visitors cannot use that page.
2. The first render and WebSocket updates use the validated spectator state,
   show the board, turn, move count, and terminal result, and omit private and
   unknown state fields. Neither page contains move controls.
3. The active lobby host can copy a signed OBS browser-source URL from the
   player page. Other players and spectators do not receive that URL.
4. The OBS URL works without a login cookie, expires after 24 hours, and stops
   working if the host changes or becomes inactive or banned. It grants only
   Connect4 spectator snapshots and read-only live WebSocket updates.
5. The overlay uses a transparent page background. Both viewers reconnect to
   the shared game WebSocket, accept authoritative snapshots and state updates,
   and label cells and status in text.
6. HTTP and WebSocket tests cover authorized and denied access, token scope and
   expiry, state isolation, live updates, resync, and action rejection.
7. Connect4 remains not playable in the catalog until its remaining engine,
   bot, replay, rules, and integration requirements are complete.
8. Django checks, migration checks, migrations, tests, and applicable frontend
   checks pass.

## KSA-027 — Add Connect4 Bots

Complete when:

1. A pure, deterministic Connect4 strategy selects a legal action for the
   current bot actor using the seeded `casual` difficulty. It takes an immediate
   win, blocks an immediate loss, and otherwise prefers a safe central column.
2. The strategy rejects unsupported difficulty, out-of-turn and completed
   states and never selects a full column.
3. Existing Connect4 sessions queue a bot turn after a committed human or bot
   move, or after session start when a bot acts first. The queued job carries
   only session UUID and expected state version; it reads actor and state from
   PostgreSQL when executed.
4. The worker submits through the same `submit_game_action` service used by
   humans, with a deterministic idempotency UUID for that actor and version.
   Stale, missing, non-bot, inactive, and completed turns do not persist moves.
5. Accepted bot moves broadcast on the shared game channel. Player and
   spectator viewers receive their existing audience-specific payloads.
6. Tests cover strategy choices and failures, commit-time scheduling, worker
   persistence and replay safety, task registration, and live WebSocket fanout.
7. Connect4 stays unplayable in the catalog until replay/results and other
   required engine and product work are complete. Its seeded metadata declares
   bot support with the existing `casual` difficulty.
8. Django checks, migration checks, migrations, and the full Python suite pass.

## KSA-028 — Add Connect4 Replay and Results

Complete when:

1. A completed Connect4 session's durable action receipts provide one ordered
   replay step per accepted move, starting from the saved initial state.
2. Replay reconstruction reapplies each move through the Connect4 rules and
   checks consecutive versions, actor, action hash, event, saved public and
   spectator state, terminal result, and final session state. Altered history fails
   closed instead of showing a partial or misleading result.
3. Authenticated current players and allowed spectators can view completed
   result and replay pages. Anonymous, outsider, inactive, departed, disabled
   spectator, non-Connect4, and unfinished access is denied.
4. Result and replay views expose only validated public Connect4 state and
   server-derived winner or draw. Unknown fields in saved state never render.
5. The replay interface steps between moves with labeled controls and a board
   whose cells have text labels. Completed live player and spectator pages link
   to results and replay.
6. Tests cover win and draw results, ordered history, access rules, missing and
   tampered data, public-state isolation, and browser replay controls.
7. Connect4 remains unplayable in the catalog until the registered engine,
   timeout behavior, rules page, and final integration requirements are done.
8. Django checks, migration checks, migrations, Python tests, and applicable
   frontend checks pass.

## KSA-029 — Add Hangman Engine

Complete when:

1. The `hangman` version `0.1` engine is registered and creates an authoritative
   state for one to eight uniquely seated players using a server-owned word.
2. Active public, spectator, and player-private serializers conceal the answer;
   completed states expose the answer and server-derived win or loss result.
3. One-letter guesses rotate by seat. Invalid payloads, repeated guesses,
   outsiders, stale versions, out-of-turn actions, and completed actions fail.
4. Wrong guesses and deterministic turn timeouts consume the configured attempt
   limit. Correct guesses reveal letters and completing the word wins.
5. Unit tests cover both outcomes, timeout, configuration, authorization,
   state isolation, and malformed authoritative state.
6. Hangman stays unplayable until its action service integration and interfaces
   are complete. Django checks, migration checks, and Python tests pass.

## KSA-030 — Add Hangman Interfaces

Complete when:

1. An authenticated current player can open an existing Hangman session page
   with the masked word, attempts, turn, and 26 labeled letter controls.
2. Controls submit only letter guesses through the shared versioned WebSocket
   action service, wait for confirmed state, and retry unresolved requests on
   reconnect with the same request ID.
3. Authorized spectators have a read-only live page. A host-issued, expiring
   OBS URL provides read-only guest access and revokes when host access changes.
4. Active HTTP and WebSocket payloads hide the answer. Completed states reveal
   it with the server-derived result. All pages use no-store responses.
5. A public rules page explains turns, attempts, timeouts, and outcomes.
6. HTTP, service, WebSocket, and browser behavior tests cover success, denial,
   live updates, completion, and hidden-state isolation. Hangman remains
   unplayable until normal lobby start and full product integration are done.

## KSA-031 — Add Werewolves vs Villagers Engine

Complete when:

1. A registered version `0.1` engine creates server-assigned roles for five to
   twenty uniquely seated actors and validates day and night durations.
2. Night wolf votes and day votes validate actor, target, phase, state version,
   and one ballot per actor. All eligible ballots or a server timeout
   resolves a phase; a tied or empty tally eliminates nobody.
3. Villagers win when no wolves live, wolves win at parity, and unresolved play
   ends in a draw after day twenty. Results derive from authoritative state.
4. Active public and spectator state and transition events reveal no roles,
   voter identities, or ballot targets. Actor-private state contains only the
   requesting player's role and ballot. Completed state may reveal roles.
5. Tests cover both team wins, draw, timeout, tied votes, invalid actions,
   malformed state, role separation, and no bot support.
6. The game stays unplayable until shared action transport, timers, and the
   KSA-032 interfaces are complete. Django and Python checks pass.
