# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Core functionality is implemented and tested: settings, role/playbook discovery, the
inventory builder, `JobManager`/ansible-runner integration, and the full FastAPI app (routes +
templates). Not yet done: the Dockerfile/Docker Hub publishing described under "Distribution".
Update this file as the remaining pieces land and decisions evolve — do not let it drift out of
sync with the actual repo.

## What AnsiBlaster is

A small web UI for running Ansible roles against a single target host on demand:

1. It scans a configured directory (default `/opt/ansible/roles`) for Ansible roles — e.g.
   `<roles_path>/docker-host/tasks/main.yml` is discovered as a role named `docker-host`.
2. The user checks one or more roles in the UI, either individually or by clicking a **playbook**
   — a named preset (e.g. "LAMP") that checks a predefined set of roles (e.g. `apache`, `mysql`,
   `php`) in one click. Playbook clicks only *add* checks; the user can still uncheck individual
   roles or combine/stack multiple playbooks and manual picks before applying.
3. The user fills in target connection details: IP address, port, username, password. There is
   no separate Linux/Windows picker — the OS is implied by which port preset is chosen (see
   "Backend & UI" below) — and username/password fields are pre-filled from configured per-OS
   defaults but remain editable before submitting. A status dot next to the port field shows a
   quick reachability check once the field loses focus.
4. Clicking "Apply" launches an Ansible run (via `ansible-runner`) that applies the selected
   roles to that single target host, authenticating over SSH (Linux, via `sshpass`) or WinRM
   (Windows), depending on the chosen OS.
5. The user watches a live log of the run in the browser.

Runs are tracked as jobs; multiple runs can execute concurrently, and run history (metadata +
logs) is persisted so past runs can be reviewed later.

## Architecture

### Backend & UI

- **FastAPI** is the web framework. Pages and fragments are server-rendered with **Jinja2**
  templates; **HTMX** drives most interactivity declaratively (refreshing the role/playbook
  lists, the Cancel button) without a separate frontend build/JS framework. Two interactions —
  submitting the apply form and opening a run from History — go through plain `fetch()` instead
  of htmx's `hx-post`/`hx-get`, because both need to relocate the server's response into a
  dynamically-created run tab (see "Live logs" below) rather than swap it into a fixed target;
  letting htmx swap into a throwaway element first, only to relocate its content afterwards,
  would mean htmx briefly initializes that throwaway element for real (in particular opening a
  live SSE connection) before it's discarded.
- The role checklist is built by scanning the configured roles directory at request time (or on
  a refresh action) — a directory is treated as a role if it looks like a standard Ansible role
  (contains `tasks/main.yml`, etc.), not by any hardcoded list.
- **UI design**: a fixed-viewport, three-column IDE layout (Playbooks / Roles / Deploy) below a
  thin title bar, styled after VS Code with the Dracula color palette (`style.css`'s `:root`
  custom properties) — always dark, no light-mode variant. Each column manages its own internal
  scroll (`overflow-y: auto` with `min-height: 0` on the flex chain) rather than the page
  itself scrolling. Playbooks and Roles each have a client-side **fuzzy filter** at the top
  (VS Code command-palette style: query characters must appear in order, not contiguously —
  see `fuzzyMatch()` in `index.html`) that filters the already-rendered list with no server
  round trip per keystroke, and re-applies itself after a list is refreshed. The Deploy
  column's top third is a read-only reflection of whichever role checkboxes are currently
  checked (`syncSelectedRolesSummary()`, delegated off `change` events so it survives a
  role-list refresh) — unchecking happens back in the Roles column, not in this summary. The
  Apply button is pinned outside the column's scrollable areas, `flex: 0 0 auto` after two
  `flex: 1` scrolling sections (selected-roles summary, then the target form). There is no
  visible Linux/Windows picker in the target form: a `<select>` of port presets ("22 (SSH)" /
  "5985 (WinRM)", defaulting to 22) both fills in the port field and implies the OS, written
  into a hidden `target_os` input (`applyPortPreset()` in `index.html`) — the only thing
  actually submitted for OS is that hidden field, so `POST /runs` and everything downstream of
  it (inventory building, `become`, etc.) are unchanged. A status dot next to the port field
  calls `GET /target/check-port` (a plain, service-agnostic TCP connect — see `portcheck.py`)
  whenever that field loses focus, via plain `fetch()` rather than htmx so the request's query
  string can't end up including the password field's value the way htmx's default form-scraping
  would.
- Below the three columns, a full-width collapsible panel has two tabs: **Log** (one sub-tab
  per concurrent run, opened by submitting the form or clicking a run in History) and
  **History** (`GET /runs`, restyled but otherwise unchanged). Role/playbook checkboxes live in
  their own columns, outside `<form id="apply-form">` (which now wraps only the Deploy column,
  since that's where the Apply button lives) — they're associated to that form via the HTML5
  `form="apply-form"` attribute rather than DOM nesting, which is what both `FormData(form)` and
  native form submission need to pick them up.

### Playbooks (role presets)

- A **playbook** is a YAML file — written like a normal Ansible playbook (a list of plays, each
  with a `roles:` list) — that lives in a configured directory (`ansible.playbooks_path`,
  parallel to `roles_path`) and names a preset group of roles, e.g. a `lamp.yml` playbook listing
  `apache`, `mysql`, `php`.
- Playbook parsing only needs to extract role *names*, not build a runnable playbook: it reads
  each play's `roles:` list (supporting plain string entries and `- role: <name>` dict entries),
  aggregating across every play in the file if there's more than one. There's no need for a full
  Ansible playbook parser since vars/tags/conditionals on those role entries are irrelevant here.
- Selecting a playbook is a **pure client-side action, not a server round trip**: when the
  playbook list is rendered, each playbook's roles are baked into the HTML (e.g. as a data
  attribute on its button), and a small inline script checks those specific role checkboxes on
  click. Because it only ever adds checks, this naturally unions with whatever roles are already
  checked (individually or from another playbook) with no extra request needed.
- Playbooks are a convenience layer only — they do not change what gets submitted or how a run
  executes. `POST /runs` still just receives whatever roles ended up checked (see Data model &
  routes), regardless of whether they came from a playbook, manual picks, or both.

### Ansible execution

- Ansible is invoked through the **`ansible-runner`** Python library, not by shelling out to
  `ansible-playbook` directly. This gives programmatic access to run status and per-event
  output, which the log streaming and job-tracking layers depend on.
- Each job builds a **dynamic, single-host inventory** in memory (or in the run's
  `private_data_dir`) from the submitted OS/IP/port/username/password — there is no static
  inventory file to maintain.
- **Authentication is OS-dependent**, chosen per run by the target's OS field, and always
  password-based (no SSH keys or WinRM certs):
  - **Linux** targets use the standard `ssh` connection plugin together with **`sshpass`**,
    which feeds the password non-interactively. `sshpass` must be present wherever a run
    actually executes (dev environment and container image both need it installed as a system
    package, not a Python dependency).
  - **Windows** targets use the `winrm` connection plugin (via the **`pywinrm`** Python package,
    which does need to be a declared dependency, unlike `sshpass`), which accepts the password
    directly — no extra system package required for this path.
  - `inventory.py` is responsible for branching on the target's OS and setting the right
    `ansible_connection`/`ansible_port`/auth variables for the host it generates.
  - Both branches deliberately skip trust verification that would otherwise block a genuinely
    new target: Linux sets `StrictHostKeyChecking=no`/`UserKnownHostsFile=/dev/null` (no
    known_hosts entry required), and Windows ignores WinRM cert validation and uses the
    `ntlm` transport (works over plain HTTP without extra server-side trust config). This
    matches the app's ad hoc "type an IP and go" workflow, at the cost of not verifying a
    target's identity on first contact.
- The generated playbook runs with **`become: true` on Linux targets only** (installing things
  like `docker-host`/`apache` needs root). Since the app only ever collects one password,
  `ansible_become_password` is deliberately set to the same value as the login password
  (harmless no-op if `target_user` is already root) rather than prompting for a second one.
  Windows targets skip `become` entirely — they're expected to connect as an already-admin
  account, and Ansible's sudo-based become doesn't apply to WinRM anyway.

### Concurrency & job tracking

- Multiple runs can be in flight simultaneously, each against its own target. Every run is a
  distinct job with its own id, status, and log stream — jobs are not serialized behind a single
  global lock.
- Each job gets its own `ansible-runner` `private_data_dir`, keeping inventories, run artifacts,
  and logs isolated per job.

### Live logs

- Log lines reach the browser via **Server-Sent Events (SSE)**, one stream per job
  (e.g. `GET /runs/{job_id}/stream`), fed from `ansible-runner`'s event/status callbacks as the
  run progresses. Each stdout chunk becomes an unnamed ("message") SSE event; when the job
  finishes, the stream emits one final **named `done` event with no payload** and closes.
- The client side is a **plain `EventSource` managed per-run in vanilla JS**
  (`connectRunStream()`/`closeRunStream()` in `index.html`), not htmx's SSE extension. That
  extension was tried first and dropped: its `hx-trigger="sse:done"` binding needs to locate
  its own element's just-created `EventSource` at trigger-setup time, which reliably failed
  (`htmx:noSSESourceError`, the "done" listener silently never binding) when the element
  carrying `hx-ext="sse"`/`sse-connect` is inserted via `htmx.process()` — a manual DOM
  insertion, which opening a run tab requires — rather than through htmx's own swap pipeline.
  The practical symptom was a finished run's tab staying stuck showing "pending" forever, even
  though the log lines themselves streamed in fine (`sse-swap="message"` did work reliably;
  only the completion signal didn't). Hand-rolling both halves in JS avoids the mismatch and
  keeps one code path instead of mixing two mechanisms for one conceptual stream.
- `message` events append to that run's `<pre class="run-log">` via plain `textContent +=`;
  the `done` event closes the `EventSource` and re-`fetch()`es `/runs/{job_id}`, feeding the
  result back into `openRunTab()` (see below) to refresh the tab in place with the final
  status/return code/log — the same "re-fetch rather than parse a status out of the event"
  approach as before, just driven by JS instead of an `hx-trigger`.
- **Run tabs**: one per concurrent run, inside the bottom panel's Log tab (see "Backend & UI"
  above). `openRunTab(html)` parses the `run_detail.html` fragment the server has always
  returned (from `POST /runs` or `GET /runs/{job_id}`), creates or reuses that run's tab
  button + content pane, calls `htmx.process()` on it (so the Cancel button's `hx-post` still
  works) and `connectRunStream()` if the run is still active
  (`run_detail.html`'s `data-active="true"`). Each tab is a `<div class="run-tab">` (not a
  `<button>` — it wraps two buttons, `.run-tab-label` and `.run-tab-close`, and a button can't
  nest inside a button) with a single delegated click listener on `#run-tabs`, since
  `openRunTab()` replaces a tab's `innerHTML` wholesale on every status/log refresh, which would
  silently drop per-button listeners bound directly to the old nodes. Tabs also carry
  `data-active` (mirrored from `run_detail.html`) so the close handler below can tell whether to
  prompt without re-reading the DOM.
- **Closing a run tab** is only exposed on the tab strip's own `.run-tab-close` button —
  `run_detail.html` used to carry a second close button in its own header, but that read as two
  redundant close controls for the same tab, so it was replaced (see "Load into Deploy" below).
  `requestCloseRunTab(runId)` is what the tab strip's close button calls. If the tab's run is
  still active, it shows a `window.confirm()` ("stop it and close the tab?") before doing
  anything — declining leaves the tab open and running untouched; accepting `POST`s
  `/runs/{job_id}/cancel` first. Either way (or immediately, for an already-finished run)
  `closeRunTab()` then closes that run's `EventSource` before removing the DOM nodes, so an
  abandoned tab doesn't leak a connection or leave an orphaned job running with nothing left to
  show its log.
- **"Load into Deploy"**, in `run_detail.html`'s header (where the redundant close button used
  to live), re-populates the Deploy column's target form and role checkboxes from that run via
  `loadRunIntoDeploy(runId)`, reading the target fields back off `run_detail.html`'s own
  `data-target-os`/`data-target-port`/`data-target-user`/`data-roles` attributes. It replaces
  the current role selection outright (unlike a playbook click, which only ever adds checks) so
  it exactly mirrors that run. The password field is deliberately left at that OS's *configured*
  default rather than the run's actual password — the actual password was never persisted (see
  the `runs` table's password note below) — so there's nothing else to offer there.
- **The History tab refreshes itself** (`refreshHistory()`, a `fetch("/runs")` that replaces
  `#run-list`'s `innerHTML`) rather than requiring the panel's manual "Refresh history" button —
  called right after a run is submitted (so it appears as `pending`/`running` immediately),
  again when its SSE stream's `done` event fires, and again after a cancel-via-close, since
  `closeRunTab()` tears down that run's `EventSource` itself and so its own `done` listener
  never gets the chance to fire.
- **The panel between the 3-column workspace and the bottom panel is drag-resizable**: a thin
  `#panel-resizer` div (`role="separator"`) sits between them; a `mousedown` on it starts
  tracking `mousemove` and sets `#bottom-panel-body`'s inline `height` directly from the
  cursor's distance to the viewport bottom (clamped to a sane min/max). Since `.workspace` above
  it is `flex: 1`, it grows or shrinks to fill whatever space the drag leaves automatically —
  no separate logic needed for the top half. Disabled (via CSS `:has()` + `pointer-events:
  none`) while `.bottom-panel` is `.collapsed`, since there's nothing to resize then.

### Persistence

- **SQLite via SQLAlchemy** stores run *metadata*: job id, target host, selected roles, status,
  timestamps, and result. This is the queryable "run history" the UI lists.
- Full run *logs* are not duplicated into the database — they live as files under each job's
  `ansible-runner` artifacts directory, and are looked up by job id when a log needs to be
  replayed or re-streamed.

### Settings

- App settings (most importantly the roles directory path, default `/opt/ansible/roles`) live in
  a **YAML config file**, with **environment variable overrides** for container-friendly
  deployment (12-factor style). There is no settings UI/database — settings are static per
  process start.
- Implemented via **`pydantic-settings`**: `settings.py`'s `Settings` model merges the YAML file
  and `ANSIBLASTER_*` env vars (`__`-nested), with the YAML source resolved dynamically per
  `ANSIBLASTER_CONFIG`/`./config.yaml` rather than fixed at class definition time. Application
  code should call `get_settings()` (a cached singleton) rather than constructing `Settings()`
  directly; `load_settings()` is the uncached version tests use.

## Data model & routes

### `runs` table (SQLite via SQLAlchemy)

| Column | Type | Notes |
|---|---|---|
| `id` | `String` (UUID), PK | Also used as the `ansible-runner` `ident` / `private_data_dir` name |
| `target_os` | `String`/enum, not null | `linux` or `windows` — determines the connection method used |
| `target_host` | `String`, not null | IP address entered by the user |
| `target_port` | `Integer`, not null | Default `22` for `linux`, `5985` for `windows` (chosen by the form/route, not the DB) |
| `target_user` | `String`, not null | |
| `roles` | `JSON` (list[str]), not null | Snapshot of selected role names at submit time (regardless of whether they came from a playbook, manual picks, or both) |
| `playbooks` | `JSON` (list[str]), nullable | Name(s) of any playbook(s) used to seed the selection (empty/null if the run was built purely from ad hoc role picks). Purely informational — `roles` above is still the source of truth for what actually ran |
| `status` | `String`/enum, not null, default `pending` | `pending → running → successful \| failed \| canceled \| error` |
| `return_code` | `Integer`, nullable | ansible-runner's `rc` once finished |
| `created_at` | `DateTime`, not null | |
| `started_at` | `DateTime`, nullable | |
| `finished_at` | `DateTime`, nullable | |
| `artifact_dir` | `String`, nullable | Path to this job's ansible-runner artifacts, for log lookup |

The target's password (SSH or WinRM, whichever the OS calls for) is **never persisted** — it is
deliberately not a column on this table, only ever held in memory for the life of the
request/job (used to build the inventory, then discarded). Re-running a past job means
re-entering the password, even though the *default* password shown in the form comes from
config (see "Configuration file" below).

Roles are recorded as a JSON snapshot rather than a normalized association table — roles are
filesystem-defined, not DB entities, so a run's `roles` column is just an immutable record of
what was selected at submit time, not a live reference. `playbooks` is the same idea applied to
whichever playbook(s) contributed to that selection: a snapshot for history/audit purposes, not a
foreign key to some playbook table (playbooks aren't DB entities either — they're files).

### Routes

| Method & path | Purpose |
|---|---|
| `GET /` | Main page: role checklist, apply form, recent run history |
| `GET /roles` | HTMX fragment — rescans the roles directory, re-renders the checklist |
| `GET /playbooks` | HTMX fragment — rescans the playbooks directory, re-renders the playbook button list (each button's roles baked in as a data attribute for the client-side check script) |
| `GET /runs` | HTMX fragment/page — run history list |
| `POST /runs` | Create a run (`roles[]`, `playbooks[]` (informational, may be empty), `target_os`, `target_host`, `target_port`, `target_user`, `target_password`); inserts a `pending` row, launches the ansible-runner job async, returns the new run's detail panel |
| `GET /runs/{job_id}` | Run detail fragment/page — status, target, roles, timestamps, log panel container |
| `GET /runs/{job_id}/stream` | SSE endpoint — live log lines + status transitions for the job; closes when the run ends |
| `GET /runs/{job_id}/log` | Full plain-text log — used for replaying a finished run, or backfilling before SSE attaches |
| `POST /runs/{job_id}/cancel` | Cancel an in-progress run (`ansible-runner` stop) → status becomes `canceled` |
| `GET /target/check-port` | JSON `{"open": bool}` — quick, service-agnostic TCP reachability check for the Deploy column's port status dot (`host`/`port` query params) |

## Configuration file

Settings live in a YAML file, discovered via `ANSIBLASTER_CONFIG` (an explicit path) falling
back to `./config.yaml` in the current working directory if unset. The file is optional — every
key has a built-in default, so a missing file (e.g. a fresh container with no volume mounted) is
not an error.

```yaml
# config.yaml — all keys shown with their defaults

server:
  host: "0.0.0.0"
  port: 8000

ansible:
  roles_path: /opt/ansible/roles        # directory scanned for roles
  playbooks_path: /opt/ansible/playbooks   # directory scanned for playbook YAML files (role presets)
  artifacts_path: /opt/ansiblaster/artifacts   # base dir for ansible-runner's per-job private_data_dir

database:
  path: /opt/ansiblaster/ansiblaster.db  # SQLite file location

logging:
  level: INFO

defaults:
  linux:
    username: ""
    password: ""
  windows:
    username: ""
    password: ""
```

`defaults.linux` / `defaults.windows` pre-fill the target form's username/password fields
depending on which OS the user selects, purely as a convenience — they are never used directly
without passing through the form, and the actual value submitted (default or edited) is the one
held in memory for that run (see the password-persistence note above).

Every key is overridable via an environment variable using the `ANSIBLASTER_` prefix with `__` as
the nesting delimiter, e.g.:

- `ANSIBLASTER_SERVER__PORT=9000`
- `ANSIBLASTER_ANSIBLE__ROLES_PATH=/srv/ansible/roles`
- `ANSIBLASTER_ANSIBLE__PLAYBOOKS_PATH=/srv/ansible/playbooks`
- `ANSIBLASTER_DATABASE__PATH=/data/ansiblaster.db`
- `ANSIBLASTER_DEFAULTS__LINUX__PASSWORD=...` / `ANSIBLASTER_DEFAULTS__WINDOWS__PASSWORD=...`

## Project layout

```
src/ansiblaster/
├── __init__.py
├── __main__.py         # entrypoint: uv run ansiblaster → starts uvicorn
├── app.py              # FastAPI app factory: creates app, mounts static/, includes routers,
│                       # wires startup/shutdown (settings load, DB init, JobManager) onto
│                       # app.state
├── deps.py             # Shared FastAPI dependency providers (get_app_settings,
│                       # get_session_factory, get_job_manager, all reading app.state) plus
│                       # the Jinja2Templates instance. Kept separate from app.py so route
│                       # modules can import it without an app.py <-> routes circular import
├── settings.py         # YAML config + env var overrides → Settings object
├── db.py               # SQLAlchemy engine/session factory, declarative Base, init_db()
├── models.py           # Run ORM model + RunStatus enum
├── roles.py            # Role discovery: scans settings.roles_path, returns valid role names
├── playbooks.py        # Playbook discovery: scans settings.playbooks_path, parses each file's
│                       # roles: list(s) into {playbook_name: [role_names]}
├── inventory.py        # Builds the ephemeral single-host inventory for ansible-runner
│                       # from a run's target fields
├── jobs.py             # JobManager: creates the Run DB row, launches ansible-runner's
│                       # run_async, keeps the in-process registry (job_id → runner handle,
│                       # asyncio.Queue for SSE, cancel event), event_handler callback that
│                       # persists status/log to DB and pushes lines to the job's queue.
│                       # Also stdout_log_path(run), mirroring ansible-runner's own
│                       # private_data_dir/artifacts/<ident>/stdout convention
├── portcheck.py        # check_port(host, port): a plain, service-agnostic async TCP connect
│                       # (not a protocol-specific banner grab) backing the Deploy column's
│                       # port status dot
├── routes/
│   ├── __init__.py     # aggregates routers for app.py to include
│   ├── pages.py        # GET /
│   ├── roles.py        # GET /roles fragment (distinct module from top-level roles.py —
│   │                   # that one discovers roles, this one serves the HTTP fragment)
│   ├── playbooks.py    # GET /playbooks fragment (distinct from top-level playbooks.py, same
│   │                   # naming pattern as roles.py above)
│   ├── runs.py         # POST /runs, GET /runs, GET /runs/{job_id}, GET /runs/{job_id}/stream,
│   │                   # GET /runs/{job_id}/log, POST /runs/{job_id}/cancel
│   └── target.py       # GET /target/check-port -- thin JSON wrapper around portcheck.py
├── templates/
│   ├── base.html
│   ├── index.html       # 3-column workspace + bottom panel; owns nearly all client-side JS
│   │                   # (fuzzy filter, playbook->checkbox, run tabs, EventSource management)
│   └── partials/
│       ├── role_list.html
│       ├── playbook_list.html  # playbook buttons, each with its roles baked in as a data
│       │                       # attribute for the client-side check script
│       ├── run_list.html
│       ├── run_row.html     # single history-list item; opened via a delegated fetch(),
│       │                   # not hx-get (see "Backend & UI")
│       └── run_detail.html  # one run's status + log; relocated into a run tab client-side
└── static/
    ├── htmx.min.js     # vendored, not CDN — the app must work with no outbound internet access
    └── style.css       # Dracula palette + the 3-column/bottom-panel IDE layout
```

- `tests/` mirrors this layout alongside `src/` (not inside the package): `test_roles.py`,
  `test_playbooks.py`, `test_inventory.py`, `test_jobs.py`, `test_portcheck.py`,
  `test_routes_pages.py`, `test_routes_roles.py`, `test_routes_playbooks.py`,
  `test_routes_runs.py`, `test_routes_target.py`, plus a shared
  `conftest.py` (the `client` fixture — a `TestClient` wired to per-test tmp_path
  roles/playbooks/artifacts/DB paths — and `make_role`/`make_playbook` helpers).
- Tests mock `ansible-runner` execution (`monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", ...)`)
  rather than running real playbooks/SSH — no live target host is required to run the test suite.

### Job execution model

Each run is launched via `ansible-runner`'s own `run_async`, which handles thread isolation and
per-job `private_data_dir`s internally — the app does not manage its own worker/thread pool on
top of it. `jobs.py` keeps a simple in-process registry mapping `job_id` → runner handle, an
`asyncio.Queue` feeding that job's SSE stream, and a cancel event, so concurrent jobs stay
independent without extra process-management code.

## Tooling & commands

- **Dependency management**: [`uv`](https://github.com/astral-sh/uv), via `pyproject.toml` +
  `uv.lock`.
  - Install dependencies: `uv sync`
  - Run the app: `uv run ansiblaster` (registered via `[project.scripts]`), or
    `uv run uvicorn ansiblaster.app:app --reload` during development for auto-reload
- **Lint & format**: [`ruff`](https://github.com/astral-sh/ruff) handles both linting and
  formatting (no separate black/isort/flake8). `pyproject.toml`'s
  `[tool.ruff.lint.flake8-bugbear] extend-immutable-calls` allowlists FastAPI's
  `Depends(...)`-as-a-default-argument idiom, which bugbear's B008 would otherwise flag.
  - Check: `uv run ruff check .`
  - Format: `uv run ruff format .`
- **Tests**: `pytest` (with `pytest-asyncio`, `asyncio_mode = "auto"` so `async def test_...`
  functions just work) and `httpx` (for FastAPI's `TestClient`).
  - Full suite: `uv run pytest`
  - Single test: `uv run pytest tests/path/to/test_file.py::test_name`

## Distribution

- **`Dockerfile`** (multi-stage): a `builder` stage uses `uv` (via
  `COPY --from=ghcr.io/astral-sh/uv:latest`) to resolve `pyproject.toml`/`uv.lock` into a
  self-contained `.venv` (dependencies synced in their own layer, before the `src/` copy, so
  editing application code doesn't bust that slower layer); the `runtime` stage is a fresh
  `python:3.11-slim` with only `/app/.venv` copied in — no `uv`, no build tools. Runtime system
  packages: `sshpass` + `openssh-client` (Ansible's `ssh` connection plugin needs both to
  authenticate to Linux targets with a password) and `gosu` (privilege drop, see below).
  `ansible-core`/`ansible-runner`/`pywinrm` are just Python deps already in `pyproject.toml`,
  installed into the venv like everything else.
- **Container user**: non-root by default (`ansiblaster`, baseline uid/gid 1000), but the
  container starts as root and **`docker-entrypoint.sh`** remaps that user to `PUID`/`PGID` env
  vars (default `1000`/`1000`, a no-op at those values) before dropping privileges via `gosu`
  — the common self-hosted-tool convention (popularized by linuxserver.io images). This lets a
  bind-mounted host directory just work by setting `PUID`/`PGID` to match its owner, instead of
  requiring the host directory's ownership to match some fixed in-image uid. The entrypoint
  only `chown`s `/opt/ansiblaster` (the app's own artifacts/db storage) — deliberately *not*
  `/opt/ansible/roles` or `/opt/ansible/playbooks`, since those are expected to be a read-only
  bind mount of the user's existing Ansible content and `chown`ing a bind mount also changes
  ownership on the *host* filesystem.
- Image paths matches `settings.py`'s defaults exactly (`/opt/ansible/roles`,
  `/opt/ansible/playbooks`, `/opt/ansiblaster/artifacts`, `/opt/ansiblaster/ansiblaster.db`'s
  parent dir), declared as `VOLUME`s, so the image works with zero config beyond bind-mounting
  your own roles at `/opt/ansible/roles` — e.g.
  `docker run -p 8000:8000 -v /path/to/roles:/opt/ansible/roles -v ansiblaster-data:/opt/ansiblaster ansiblaster`.
- **`docker-compose.yml`** wraps that same setup (`HOST_PORT`/`PUID`/`PGID`/`HOST_ROLES_DIR`/
  `HOST_PLAYBOOKS_DIR` env vars, documented in `.env.example`) and defaults
  `HOST_ROLES_DIR`/`HOST_PLAYBOOKS_DIR` to the bundled **`example/`** directory — a minimal
  Ubuntu/Debian LAMP stack (`apache`/`mysql`/`php` roles + a `lamp.yml` playbook, all
  `ansible.builtin`-only, no extra collections needed) so `docker compose up` has something
  real to show on first run instead of an empty checklist. See `example/README.md`.
- The repo must also be directly runnable from a clone (via `uv sync` + `uv run`) without
  Docker — both distribution paths are first-class, not just the container.
- **`.github/workflows/docker-publish.yml`** builds and publishes to Docker Hub
  (`bamhm182/ansiblaster`) automatically: a `test` job (`uv sync`, `ruff check`, `pytest`) gates
  a `docker` job that builds the image (`linux/amd64` only) via `docker/build-push-action`.
  Push to `main` publishes `latest`; pushing a `vX.Y.Z` git tag additionally publishes matching
  `X.Y.Z`/`X.Y`/`X` tags (via `docker/metadata-action`). Pull requests run the same build for
  validation but never push (no Docker Hub login happens on PR events, since forked PRs don't
  have secrets access anyway). Requires two repo secrets set in GitHub —
  `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` (a Docker Hub access token, not the account
  password) — which aren't and shouldn't be committed anywhere in this repo.
- **Still not verified by a real `docker build`**: no session so far has had a Docker daemon
  available (client only). One real bug already slipped through this gap: the builder stage's
  second `uv sync` originally lacked `--no-editable`, so it installed the project in editable
  mode — a `.pth` file in site-packages pointing back at the builder stage's `/app/src` — which
  works inside that stage but breaks the instant the runtime stage copies only `.venv`, since
  the `.pth` then points nowhere (`ModuleNotFoundError: No module named 'ansiblaster'` at
  container start). Found via a real `docker compose up` failure report, and the fix was
  verified by faithfully reproducing the two-stage layering with `uv` directly (separate
  directories per stage, physically removing the builder's `src/` before testing the "runtime"
  `.venv` in isolation) rather than guessed at — but that is still not the same as an actual
  `docker build`/`docker run` pass, which is owed before trusting this in production.
