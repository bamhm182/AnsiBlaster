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
   roles or combine/stack multiple playbooks and manual picks before applying. A role can also
   declare its own fillable **variables** (name, type, optional default, whether it's required)
   via a standard `meta/argument_specs.yml` — checking that role surfaces them in the Deploy
   column's Variables area, any declared default autofilled (see "Role variables
   (argument_specs)" below).
3. The user fills in target connection details: IP address, port, username, password. There is
   no separate Linux/Windows picker — the OS is implied by which port preset is chosen (see
   "Backend & UI" below) — and username/password fields are pre-filled from configured
   per-preset defaults but remain editable before submitting. A status dot shows a quick
   reachability check whenever the IP address or Port field loses focus, or a new preset is
   picked.
4. Clicking "Apply" launches an Ansible run (via `ansible-runner`) that applies the selected
   roles to that single target host, authenticating over SSH (Linux, via `sshpass`), WinRM, or
   PSRP (the latter two both Windows), depending on the chosen preset.
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
  live SSE connection) before it's discarded. Every URL the browser is ever asked to hit --
  `base.html`'s stylesheet/script tags, every `hx-get`/`hx-post`, and every JS-built
  `fetch()`/`EventSource()` URL in `index.html` -- is written **relative, with no leading
  slash** (`static/style.css`, `runs`, `` `runs/${runId}/stream` ``, etc.), never root-absolute
  (`/static/style.css`). This is what lets the app work when reverse-proxied at an arbitrary,
  request-invisible subpath -- e.g. Coder OSS's path-based workspace-app proxying
  (`https://coder.example.com/@user/workspace.agent/apps/ansiblaster/`) -- which strips its own
  prefix before forwarding to the backend and sends no `X-Forwarded-Prefix`-style header either,
  so the backend has no way to learn its external prefix from the request it receives; only the
  browser's own address bar knows it. Root-absolute URLs resolve against the domain root and so
  silently skip straight past that prefix (fetching a *different* app's, or Coder's own,
  `/static/style.css`); relative URLs resolve against the current document's own address --
  whatever the browser is actually looking at, prefix included -- which is why this only works
  correctly when that address ends in a trailing slash (true for `GET /`, the app's only real
  page). `base_url` values baked server-side into `partials/file_browser.html` (from
  `routes/roles.py`/`routes/playbooks.py`) follow the same rule (`f"roles/{name}"`, not
  `f"/roles/{name}"`). Since the backend itself is never asked to serve anything at a prefixed
  path (Coder strips it before proxying), none of this needs any server-side `root_path`
  handling -- no uvicorn `--root-path`, no `X-Forwarded-*` middleware -- the fix is entirely in
  how URLs are *written*, not how they're *resolved server-side*. Keep any new URL added to a
  template or to `index.html`'s JS on this same relative convention.
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
  round trip per keystroke, and re-applies itself after a list is refreshed. Below the Deploy
  column's header, a small, **fixed-height (not flex-grow) read-only reflection** of whichever
  role checkboxes are currently checked
  (`syncSelectedRolesSummary()`, delegated off `change` events so it survives a role-list
  refresh) — unchecking happens back in the Roles column, not in this summary, though each
  entry also gets its own eyeball button (same as Roles/Playbooks, see "Viewer tab" below) so a
  selected role's files can be checked without leaving the Deploy column. A drag handle
  (`#deploy-resizer`, `setupDeployResizer()` in `index.html`) sits right below it — the same
  technique as the bottom log panel's own `#panel-resizer` (see "Live logs" below), just
  measured from the summary's top edge instead of the viewport's bottom, since this one grows
  downward from a fixed top rather than upward from a fixed bottom. Below *that* is the target
  form (`.deploy-target`, now `flex: 1 1 auto` — the one that actually grows to fill whatever
  the small fixed-height summary above doesn't use), which is a **single scrolling area**
  (`overflow-y: auto` on `.deploy-target` itself, nothing scrolling independently inside it)
  listing one `<fieldset class="deploy-vars-role">` after another: first a static "Host"
  fieldset (IP/port, then username/password), then one more such fieldset per checked role
  that declares variables via `meta/argument_specs.yml` (see "Role variables (argument_specs)"
  below) — the **Variables** area (`.deploy-vars`/`#deploy-vars-summary`), which
  `syncRoleVariables()` rebuilds wholesale on every selection change and appends directly after
  the Host fieldset, both using the same fieldset+legend styling so the whole list reads as one
  consistent set of sections rather than a visually distinct "fixed fields" part and
  "Variables" part. `syncRoleVariables()` is called from the same delegated `change` listener
  plus every other place `syncSelectedRolesSummary()` is called — `applyPlaybook()`, the page's
  initial load, and `loadRunIntoDeploy()`. Unlike the role checkboxes (which live in a
  different column and need the `form="apply-form"` attribute trick), the Variables area's
  inputs are built directly inside `#apply-form`'s own DOM subtree, so `FormData(applyForm)`
  picks them up with no extra wiring. There is no visible Linux/Windows picker in the target
  form: a small "SSH"/"WinRM"/
  "WinRM (Secure)"/"PSRP"/"PSRP (Secure)" `<select>` is merged with the port number input into
  one bordered
  control (`.port-field-group` in `style.css` — the select and input themselves are
  borderless/transparent so only the group's shared border shows, making them read as one field
  rather than two) — picking a preset writes the OS+connection it implies into a hidden
  `target_os` input and fills the port input from the *selected `<option>`'s own value*, not a
  per-OS lookup table (`applyPortPreset()` in `index.html`): WinRM and WinRM (Secure) share an
  OS/connection (so a per-OS port lookup can't tell them apart) but need different actual ports
  (5985 vs 5986), same for the two PSRP options. The port stays freely editable afterward (e.g.
  a non-standard SSH port). That hidden `target_os` field is the only thing actually submitted
  for OS, so `POST /runs` and everything downstream of it (inventory building, `become`, etc.)
  are unchanged by any of this. WinRM and PSRP are two different Ansible connection
  plugins/Python libraries (`pywinrm`/`pypsrp`) that both talk to the same Windows WinRM
  listener (secure or not), so they get their own `TargetOS` members (`WINDOWS`/`WINDOWS_PSRP`)
  but share default ports and are otherwise treated identically everywhere except
  `inventory.py` (see "Ansible execution" below). A dedicated Status row ("Status: ⟳ ⬤ <text>")
  sits at the bottom of the column, outside `.deploy-target`'s scrollable area, with the Apply
  button on the same row, pushed to its right edge (`margin-left: auto` on `.apply-button`
  itself rather than a separate wrapper) — the Status row shows a quick reachability check
  (`checkTargetPort()`/`resetPortStatusDot()` in
  `index.html`, calling `GET /target/check-port` — see `portcheck.py`) run whenever the IP
  address field *or* the Port field loses focus, or a port preset is picked (`applyPortPreset()`
  calls `checkTargetPort()` directly rather than just resetting the dot, since the port/protocol
  just changed out from under whatever was last checked): the text is whatever banner the
  target volunteers unprompted (e.g. `SSH-2.0-OpenSSH_10.2`, the same thing `nc host port` would
  show), since a protocol like SSH sends that the instant a connection opens. WinRM/PSRP targets
  just show "open, no banner" — both are HTTP/SOAP underneath, and HTTP is request-driven, so
  nothing arrives until the client sends a request first, which this check deliberately never
  does (keeping the same passive connect-and-listen behavior for every target rather than
  branching per protocol is what makes it "service-agnostic"). That call is plain `fetch()`
  rather than htmx so the request's query string can't end up including the password field's
  value the way htmx's default form-scraping would. A small refresh (`.icon-button`, the same
  one used elsewhere) sits to the left of the dot to re-run the check on demand, calling the
  same `checkTargetPort()`.
- Below the three columns, a full-width collapsible panel has three tabs: **Log** (one sub-tab
  per concurrent run, opened by submitting the form or clicking a run in History), **History**
  (`GET /runs`, restyled but otherwise unchanged), and **Viewer** (a read-only file browser, see
  below). Role checkboxes live in their own column, outside `<form id="apply-form">` (which
  now wraps only the Deploy column, since that's where the Apply button lives) — they're
  associated to that form via the HTML5 `form="apply-form"` attribute rather than DOM nesting,
  which is what both `FormData(form)` and native form submission need to pick them up. Playbook
  buttons carry no form control at all (see "Playbooks (role presets)" below) — they only ever
  drive role checkboxes via client-side JS, so there's nothing of theirs for a form to submit.
- **Viewer tab**: every role and playbook row in the Playbooks/Roles columns, *and* every role
  in the Deploy column's selected-roles summary, has an eyeball button (`.icon-button
  .eyeball-button`, an inline SVG rather than an emoji character — a colored emoji glyph would
  clash with the otherwise monochrome Dracula icon set, and rendering is font/platform-dependent
  in a way a `stroke="currentColor"` SVG isn't; the SVG markup is shared three ways: a Jinja
  partial, `partials/eye_icon.html`, for the two server-rendered lists, and a JS constant,
  `EYE_ICON_SVG` in `index.html` -- built by `{% include %}`ing that same partial into a
  template literal -- for the selected-roles summary, since that list is built client-side and
  can't `{% include %}` a partial into its own markup at runtime) right after its name. It's
  invisible (`visibility: hidden`, not `display: none`, so it doesn't shift the row's layout
  when it appears) until its row is hovered or it has keyboard focus — clicking it switches the
  bottom panel to the Viewer tab and loads that item's files into a two-pane read-only browser
  (`.viewer-file-list` + `.viewer-file-content`), via `openViewer(kind, name)` in `index.html`
  calling `GET /{roles|playbooks}/{name}/files` (`partials/file_browser.html`) and, per file
  clicked, `GET /{roles|playbooks}/{name}/file?path=...` (`partials/file_content.html`) — both
  plain `hx-get`s on the file browser's own buttons, no extra JS needed for that part.
  `browse.py` backs both: a role's "files" are every regular file under its directory
  (`rglob("*")`, relative paths); a playbook's is always exactly one entry, its own filename, so
  the same two-step "browse, then click a file" UI works for both without special-casing either.
  Once the file list loads, `selectDefaultViewerFile()` auto-loads a file into
  `.viewer-file-content` without waiting for a click: a role's `tasks/main.yml` if it has one
  (matched by each file button's `data-relpath`), otherwise whichever file is the *only* one
  (always true for a playbook) — it issues its own `htmx.ajax()` GET for that file rather than
  calling `.click()` on the matching button, since that button was just swapped in by the
  files-list request's own `htmx.ajax()` and isn't necessarily done being wired up for click
  handling by the time its promise resolves (confirmed via Playwright: a synthetic `.click()`
  right there was silently a no-op, while issuing the equivalent request directly was not).
  Every lookup re-validates the role/playbook name against the same rules `roles.py`/
  `playbooks.py` use for discovery, and every resolved path (the name itself, and any requested
  file path within a role) is checked to still be inside its expected base directory once
  resolved — defense against a `../`-laden name or path, or a symlink, trying to read something
  outside `roles_path`/`playbooks_path`. Neither the eyeball button nor the row it sits in could
  just be `<button>`-in-`<button>` (roles' would also need to sit inside the checkbox's `<label>`,
  which would otherwise toggle the checkbox too) — see `role_list.html`/`playbook_list.html`'s
  comments; playbook rows use the same "outer `<div>`, two sibling `<button>`s" shape as the run
  tabs described below.

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
  executes, and they are not tracked once a run is created. `POST /runs` only ever receives
  `roles[]` (see Data model & routes); there's no `playbooks[]` field and no record anywhere of
  which playbook(s), if any, contributed to a given run's role selection — a run's history is
  just the roles that were actually applied, the same regardless of whether they came from a
  playbook, manual picks, or both.

### Role variables (argument_specs)

- A role can declare fillable variables via `meta/argument_specs.yml` (or `.yaml`) — Ansible's
  own standard for declaring a role's inputs (ansible-core 2.11+, normally consumed by
  `ansible-doc`/`ansible-lint`), under `argument_specs.main.options`. Each option can carry
  `type`, `default`, `required`, and `description`. This was chosen over reading
  `defaults/main.yml` directly because that file has no way to express "this variable exists
  but has no default and must be filled in" — everything in it already has a value.
- `role_vars.py`'s `discover_role_variables(roles_path, roles)` parses this per role, returning
  `{role: {var_name: {"type", "default", "required", "description"}}}`. A role with no
  argument_specs file, unreadable/malformed YAML, or the wrong shape simply has no entry in the
  result (never an empty `{}`) — mirrors `roles.py`/`playbooks.py`'s "missing/bad data on disk =
  no data, never raise" philosophy, since this reads config files, not user input. Exposing
  variables in the Deploy column is opt-in per role: a role with no argument_specs file just
  shows nothing in the Variables area.
- Both `GET /roles` (`routes/roles.py`) and `GET /` (`routes/pages.py`) call
  `discover_role_variables()` alongside `discover_roles()` and pass the result to
  `role_list.html`, which bakes each role's variable spec into a `data-vars` attribute on its
  checkbox (`{{ (role_variables.get(role) or {}) | tojson }}`) — the same "bake it into HTML,
  zero extra round trips" precedent playbook buttons already use for their roles list. See
  "Backend & UI" above for how the client renders this into the Variables area.
- Field naming is `vars[<role>][<var_name>]`, parsed server-side in `routes/runs.py`'s
  `create_run()` via a small bracket-notation regex (`_parse_role_variables()`), then validated/
  type-coerced against the *selected* roles' own argument_specs (`_coerce_role_variables()`,
  `_coerce_value()`) — `bool` from `true/1/yes/on` and `false/0/no/off` (case-insensitive),
  `int`/`float` via a direct cast, `list`/`dict` via `yaml.safe_load()` plus an `isinstance`
  check (YAML is a JSON superset, so `["a", "b"]` or `{"key": "val"}` typed into a plain text
  box parses correctly), anything else (`str`, unrecognized types) passed through as-is. A
  blank + required variable is a **400** (`"<role>: '<var_name>' is required."`); a blank +
  optional variable is omitted entirely (so the role's own argument_specs default — applied by
  Ansible itself at role invocation — wins, rather than being overridden by an explicit empty
  string); a bad cast (e.g. non-numeric text for an `int`) is also a 400. This is deliberately
  **stricter** than the "never raise" discovery philosophy above — validating what a user just
  typed in before launching a privileged job against a real host is a different concern than
  reading config off disk, closer in spirit to the existing `target_port` int-cast 400. A stray
  `vars[<role-not-selected>][...]` field is silently ignored (only `roles`, and each of their
  own specs, are iterated) — same lenient-toward-unknown-fields precedent as a stray
  `playbooks[]` field.
- A role entry in the generated playbook's `roles:` list becomes `{"role": name, "vars": {...}}`
  only when that role actually has variables supplied (`jobs.py`'s `_build_playbook()`) — kept
  as a plain string otherwise, so the common no-vars case stays exactly as minimal as before. A
  mixed list is expected and fine: `playbooks.py`'s own `_role_name_from_entry()` already reads
  this exact dict shape (currently discarding `vars:`) when *parsing* a playbook file's `roles:`
  list, confirming it's the right Ansible-native shape rather than an invention here.
- Submitted variables are **not** persisted anywhere — `create_run()` passes the parsed/coerced
  `variables` dict straight into `job_manager.start_job(..., variables=variables)`, which uses
  it only to build that one job's ephemeral playbook (`jobs.py`'s `_build_playbook()`); the
  `Run` row itself carries no `variables` column. Same treatment as the target password (see
  the `runs` table note below), and for the same reason: a variable named e.g.
  `mysql_root_password` typed into the Variables area should never end up sitting in run
  history in the clear. "Load into Deploy" (see "Live logs" below) therefore has nothing to
  restore — it resets the Variables area to each re-checked role's declared default (or blank),
  the same as freshly checking that role, rather than reproducing whatever was actually
  submitted last time.
- A variable's *default* (as opposed to a submitted run's actual value, never persisted per the
  point above) can itself be overridden persistently via the Settings popup — see "Settings
  popup" below. Each variable field in the Deploy column carries its own "Save as Default"
  icon button next to it for this. Overridden defaults are baked into the same `data-vars`
  attribute this section describes, merged in server-side before `role_list.html` ever
  renders, so the client-side code in "Backend & UI" above needs no awareness that an override
  happened at all -- to it, an overridden default just looks like a role's own declared one.

### Ansible execution

- Ansible is invoked through the **`ansible-runner`** Python library, not by shelling out to
  `ansible-playbook` directly. This gives programmatic access to run status and per-event
  output, which the log streaming and job-tracking layers depend on.
- Each job builds a **dynamic, single-host inventory** in memory (or in the run's
  `private_data_dir`) from the submitted OS/IP/port/username/password — there is no static
  inventory file to maintain.
- **Authentication is OS/connection-dependent**, chosen per run by the target's `TargetOS`
  value (`linux` / `windows` / `windows_psrp`), and always password-based (no SSH keys or
  WinRM/PSRP certs):
  - **Linux** targets use the standard `ssh` connection plugin together with **`sshpass`**,
    which feeds the password non-interactively. `sshpass` must be present wherever a run
    actually executes (dev environment and container image both need it installed as a system
    package, not a Python dependency).
  - **Windows** targets use either the `winrm` connection plugin (via the **`pywinrm`** Python
    package) or the `psrp` connection plugin (via the **`pypsrp`** Python package) — both
    declared dependencies, unlike `sshpass`, and both talk HTTP/SOAP to the same WinRM listener
    on the target, just via different client libraries/Ansible connection plugins. Either way
    the password is accepted directly — no extra system package required for this path.
  - `inventory.py` is responsible for branching on the target's OS/connection and setting the
    right `ansible_connection`/`ansible_port`/auth variables for the host it generates.
  - All three branches deliberately skip trust verification that would otherwise block a
    genuinely new target: Linux sets `StrictHostKeyChecking=no`/`UserKnownHostsFile=/dev/null`
    (no known_hosts entry required), and both Windows connection types ignore the WinRM/PSRP
    cert validation and use the `ntlm` auth/transport (works over plain HTTP without extra
    server-side trust config). This matches the app's ad hoc "type an IP and go" workflow, at
    the cost of not verifying a target's identity on first contact.
- The generated playbook runs with **`become: true` on Linux targets only** (installing things
  like `docker-host`/`apache` needs root). Since the app only ever collects one password,
  `ansible_become_password` is deliberately set to the same value as the login password
  (harmless no-op if `target_user` is already root) rather than prompting for a second one.
  Windows targets (either connection type) skip `become` entirely — they're expected to
  connect as an already-admin account, and Ansible's sudo-based become doesn't apply to
  WinRM/PSRP anyway.

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
  it exactly mirrors that run's roles, and reflects the run's OS/connection in the port preset
  dropdown too, matched by `data-os` *and* port together first (falling back to a `data-os`-only
  match, then to no selection) since WinRM/PSRP's plain and "(Secure)" presets now share a
  `data-os`. Its Variables area is *not* restored from the run — variables are never persisted
  (see "Role variables (argument_specs)" above) — `syncRoleVariables({})` resets each re-checked
  role's fields to its declared default (or blank) instead, same as freshly checking that role.
  The run's actual password was never persisted either (see the `runs` table's password note
  below), so there's nothing to restore it to -- but a password the user already *typed* into
  the form before clicking this is worth more than the configured default, so it's preserved
  rather than clobbered: `loadRunIntoDeploy()` only lets `applyOsDefaults()`'s default password
  through when the Password field was empty beforehand, restoring whatever was there otherwise.
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

### Settings popup

Distinct from the static, config-file-driven "Settings" above (same name, different thing --
this is the gear-icon popup in the app's own UI, not `config.yaml`): a small set of **runtime,
DB-backed overrides**, editable from a modal opened via a cog button in the title bar (top
right, next to "AnsiBlaster" -- `base.html`). The modal has two tabs, **Role Variables** and
**Host Variables** (`.settings-tab`/`.settings-tab-content`, switched purely client-side by
`switchSettingsTab()` -- same technique as the bottom panel's Log/History/Viewer tabs):

- **Role Variables tab** -- overrides for what a role variable (declared via a role's
  `meta/argument_specs.yml` -- see "Role variables (argument_specs)" above) autofills to when
  its role is checked. Overrides are keyed **globally by variable name, not per role** -- a
  saved `mysql_port` override applies to every role that happens to declare a variable named
  `mysql_port`, matching the tab's own "sorted alphabetically by variable name" / "+ to add a
  variable by name" design, which has no notion of "for this role only". Existing overrides are
  listed one per line (each just a name + its value, styled like a single-line "row" -- no
  per-row save button) under a single **"Save Role Variables"** button that saves every edited
  row's current value at once (`POST /settings/role-variables/bulk`, fields named
  `value[<name>]`, same bracket-notation convention `routes/runs.py`'s own
  `vars[<role>][<var_name>]` fields already use); adding a brand-new override by name is its own
  separate small "+" action instead, since there's no existing value to bulk-save alongside yet
  (`POST /settings/role-variables`, also what a Deploy-column "Save as Default" click hits --
  see below). Removing one is still a per-row action (`DELETE /settings/role-variables/{name}`).
- **Host Variables tab** -- username/password overrides per port preset (`ssh`/`winrm`/`psrp` --
  the same three `config.yaml` already has under `defaults.*`, see "Configuration file" below),
  each field its own full-width line (the same row shape the Role Variables tab's list uses,
  not the Deploy column's side-by-side username/password pairing). Leaving a field blank means
  "no override, fall back to `config.yaml`'s value" (shown as that field's placeholder) rather
  than "override it with an explicit blank" -- submitting a blank field clears any existing
  override for that exact preset+field rather than saving an empty string over a real
  configured default. Saved all at once via a single **"Save Host Settings"** button
  (`POST /settings/host`).

Each variable field in the Deploy column's Variables area also carries its own "Save as
Default" icon button (`saveVariableAsDefault()` in `index.html`), saving that field's *current*
value as the new global default for its variable name with no need to open the popup at all.

Both override kinds are backed by a **single generic key/value `Setting` table** (`key: str`
PK, `value: JSON` -- see `models.py`) rather than a bespoke table per override kind,
specifically to sidestep this project's lack of a schema-migration framework (see the `runs`
table's no-migration-framework note below): a new *kind* of setting only ever needs a new
key-naming convention, never a new column or table. `settings_store.py` owns the key
conventions (`"role_variable:<name>"` / `"host:<preset>:<field>"`) and the get/set/delete
helpers; nothing outside that module should query the `Setting` table directly. It also has the
merge helpers that layer these overrides on top of their non-DB source of truth --
`apply_role_variable_overrides()` (over `discover_role_variables()`'s output) and
`apply_host_overrides()` (over `settings.defaults`) -- a DB override always wins over the
matching `config.yaml`/argument_specs value when both exist. Values are parsed with
`parse_override_value()`, which is `yaml.safe_load()`-based (a JSON superset, so typed text like
`42`/`true`/`["a", "b"]` round-trips to its natural Python type, same technique
`routes/runs.py`'s own `_coerce_value()` already uses for list/dict variable submissions) --
except a blank submission, kept as an explicit empty string rather than
`yaml.safe_load("") -> None`, since a blank *default* is itself a meaningful, deliberate choice
here.

`routes/pages.py` (`GET /`) and `routes/roles.py` (`GET /roles`) both call
`apply_role_variable_overrides()` right after their existing `discover_role_variables()` call,
and `routes/pages.py` also swaps what it passes to the template as `defaults` for
`apply_host_overrides(settings.defaults, ...)`'s merged result -- everywhere else in the
codebase (`index.html`'s `defaults.ssh.username` etc., `OS_DEFAULTS` in its inline script) reads
that same `defaults` context variable unchanged, with no awareness an override might be
involved. But that merge only happens when a role checkbox is actually (re)rendered -- its
`data-vars` attribute is a snapshot baked in at the last `GET /roles`/`GET /`, not a live value
-- so **every** action that can create or change an override (the modal's "Save Role
Variables"/"+"/delete, and the Deploy column's own "Save as Default") also calls
`refreshRoleList()` (`index.html`) afterwards: it re-fetches `GET /roles` in place via
`htmx.ajax()`, then re-checks whatever roles were checked and re-applies
`syncRoleVariables()` over whatever was already typed, so an override takes effect the moment
you next check that role (even by unchecking and rechecking the *same* role right away) without
needing a manual Roles-panel refresh or a full page reload first. For the modal specifically,
this is wired generically rather than once per action: a `htmx:afterRequest` listener on
`#settings-modal-body` calls `refreshRoleList()` after any non-GET request that fragment makes.

`routes/settings.py` is the popup's own backend (`GET /settings` renders the modal's body
fragment, `partials/settings_modal_body.html`; `POST /settings/role-variables` and
`DELETE /settings/role-variables/{name}` add/edit or remove one override; `POST
/settings/role-variables/bulk` saves every existing override at once; `POST /settings/host`
saves the whole host-defaults form at once) -- every one of its routes returns that same
fragment afresh (mirroring `routes/runs.py`'s re-fetch-and-re-render pattern for
`run_detail.html`), so the modal reflects whatever was just saved/removed without a page reload;
`base.html`'s cog button issues a plain `hx-get="settings"` into `#settings-modal-body` each
time it's opened (nothing about the modal is server-rendered on initial page load) and calls
`openSettingsModal()` (unhides the overlay, and resets the active tab to Role Variables). The
cog and "Save as Default" icons are inline SVGs (`partials/settings_icon.html`,
`partials/save_icon.html`), following the same `stroke="currentColor"` monochrome-icon
precedent the eyeball button already established (see "Backend & UI" above) rather than a
Unicode emoji glyph, which renders in color and inconsistently across platforms.

Because `#settings-modal-body`'s content is swapped wholesale by htmx on every mutating action,
its tab state (`activeSettingsTab`) has to survive that swap -- `switchSettingsTab()` is
re-applied via a `htmx:afterSwap` listener rather than relying on whatever
`settings_modal_body.html` renders as the default tab each time. All of this tab-switching (and
`openSettingsModal()`, and the `htmx:afterRequest` → `refreshRoleList()` wiring above) lives in
`base.html`'s own trailing `<script>` block, **not** `index.html`'s -- deliberately, and not
just for the "modal chrome belongs with the modal markup" reasoning that already put the
click-outside/Escape handling there. `index.html`'s script runs while parsing `<main>`, which
comes *before* `base.html`'s modal `<div>`s in the document -- a `document.getElementById
("settings-modal-body")` call from `index.html`'s script would find nothing yet and throw
(`Cannot read properties of null`), silently breaking every inline `onclick` on the page after
it, since a script-level exception aborts the rest of that `<script>` block. `refreshRoleList()`
itself stays in `index.html` (it only touches elements already present inside `<main>`, and
`base.html`'s later script calling an earlier-defined global function is the safe direction).

## Data model & routes

### `runs` table (SQLite via SQLAlchemy)

| Column | Type | Notes |
|---|---|---|
| `id` | `String` (UUID), PK | Also used as the `ansible-runner` `ident` / `private_data_dir` name |
| `target_os` | `String`/enum, not null | `linux`, `windows`, or `windows_psrp` — determines the connection method used. Never shown to the user as-is: `inventory.connection_label(target_os, target_port)` (a `connection_label` Jinja filter, registered in `deps.py`) maps it back to whatever port preset produces it -- "SSH"/"WinRM"/"WinRM (Secure)"/"PSRP"/"PSRP (Secure)" -- for display in run history/detail, since that's what the user actually picked (see "Backend & UI" above) |
| `target_host` | `String`, not null | IP address entered by the user |
| `target_port` | `Integer`, not null | Default `22` for `linux`, `5985` for `windows`/`windows_psrp` (chosen by the form/route, not the DB) |
| `target_user` | `String`, not null | |
| `roles` | `JSON` (list[str]), not null | Snapshot of selected role names at submit time (regardless of whether they came from a playbook, manual picks, or both — playbooks themselves aren't tracked, see "Playbooks (role presets)" above) |
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
config (see "Configuration file" below). Submitted role variables (see "Role variables
(argument_specs)" above) get the same treatment and for the same reason — they're used only to
build that one job's ephemeral playbook, never written to a column here.

Roles are recorded as a JSON snapshot rather than a normalized association table — roles are
filesystem-defined, not DB entities, so a run's `roles` column is just an immutable record of
what was selected at submit time, not a live reference. There's no equivalent column for
playbooks: they're a client-side-only convenience for checking roles (see "Playbooks (role
presets)" above), not something a run's history needs to remember.

There's no migration framework in this project (`db.py`'s `init_db()` is a plain
`Base.metadata.create_all()`, which only creates missing *tables*, not missing *columns* on an
already-existing one) — a future column added to a table won't be picked up by an existing
SQLite file without recreating it. A general, pre-existing limitation of this project's
schema-management approach, avoided so far by keeping table schemas stable rather than solved —
the `settings` table below is deliberately designed around this same limitation rather than
risking it again (see "Settings popup" above).

### `settings` table (SQLite via SQLAlchemy)

Backs the Settings popup (see "Settings popup" above) — a single generic key/value table, not
one column/table per override kind.

| Column | Type | Notes |
|---|---|---|
| `key` | `String`, PK | `"role_variable:<name>"` or `"host:<preset>:<field>"` — see `settings_store.py` |
| `value` | `JSON`, not null | Any JSON-serializable value; a role-variable override's type depends on what was saved (an `int`/`bool`/`list`/etc., not always a `str`), a host override is always a plain string |

### Routes

| Method & path | Purpose |
|---|---|
| `GET /` | Main page: role checklist, apply form, recent run history |
| `GET /roles` | HTMX fragment — rescans the roles directory, re-renders the checklist |
| `GET /roles/{name}/files` | HTMX fragment — Viewer tab file list for one role (`partials/file_browser.html`) |
| `GET /roles/{name}/file` | HTMX fragment — one file's read-only content (`path` query param, `partials/file_content.html`) |
| `GET /playbooks` | HTMX fragment — rescans the playbooks directory, re-renders the playbook button list (each button's roles baked in as a data attribute for the client-side check script) |
| `GET /playbooks/{name}/files` | HTMX fragment — Viewer tab file list for one playbook (always one entry, its own file) |
| `GET /playbooks/{name}/file` | HTMX fragment — that file's read-only content (`path` query param) |
| `GET /runs` | HTMX fragment/page — run history list |
| `POST /runs` | Create a run (`roles[]`, `target_os`, `target_host`, `target_port`, `target_user`, `target_password`, `vars[<role>][<var_name>]` for any selected role's declared variables); inserts a `pending` row, launches the ansible-runner job async, returns the new run's detail panel |
| `GET /runs/{job_id}` | Run detail fragment/page — status, target, roles, timestamps, log panel container |
| `GET /runs/{job_id}/stream` | SSE endpoint — live log lines + status transitions for the job; closes when the run ends |
| `GET /runs/{job_id}/log` | Full plain-text log — used for replaying a finished run, or backfilling before SSE attaches |
| `POST /runs/{job_id}/cancel` | Cancel an in-progress run (`ansible-runner` stop) → status becomes `canceled` |
| `GET /target/check-port` | JSON `{"open": bool, "banner": str \| null}` — quick, service-agnostic TCP reachability + banner check for the Deploy column's Status row (`host`/`port` query params) |
| `GET /settings` | HTMX fragment — the Settings popup's body (`partials/settings_modal_body.html`), listing current role-variable-default and host-default overrides |
| `POST /settings/role-variables` | Add or update one role-variable-default override (`name`, `value`); returns the refreshed popup body |
| `POST /settings/role-variables/bulk` | Save every existing role-variable override at once (`value[<name>]` per row, from the Role Variables tab's single "Save Role Variables" button); returns the refreshed popup body |
| `DELETE /settings/role-variables/{name}` | Remove one role-variable-default override; returns the refreshed popup body |
| `POST /settings/host` | Save the whole host-defaults form at once (`{preset}_username`/`{preset}_password` for `ssh`/`winrm`/`psrp`; a blank field clears that override); returns the refreshed popup body |

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
  ssh:
    username: ""
    password: ""
  winrm:
    username: ""
    password: ""
  psrp:
    username: ""
    password: ""
```

`defaults.ssh` / `defaults.winrm` / `defaults.psrp` pre-fill the target form's username/password
fields depending on which port preset the user picks (see "Backend & UI" above), purely as a
convenience — they are never used directly without passing through the form, and the actual
value submitted (default or edited) is the one held in memory for that run (see the
password-persistence note above). Each is independent, with no fallback between them: WinRM and
PSRP are both "Windows" but not necessarily the same account, so leaving `psrp` unset (say)
just leaves that preset's fields blank rather than borrowing `winrm`'s values.

The Settings popup's Host Defaults (see "Settings popup" above) can override any of these
username/password values per preset at runtime, without editing this file or restarting the
process — a DB-saved override always wins over this file's value for that exact preset+field
when both exist; a field left unset in the popup just falls back to whatever's configured here.

Every key is overridable via an environment variable using the `ANSIBLASTER_` prefix with `__` as
the nesting delimiter, e.g.:

- `ANSIBLASTER_SERVER__PORT=9000`
- `ANSIBLASTER_ANSIBLE__ROLES_PATH=/srv/ansible/roles`
- `ANSIBLASTER_ANSIBLE__PLAYBOOKS_PATH=/srv/ansible/playbooks`
- `ANSIBLASTER_DATABASE__PATH=/data/ansiblaster.db`
- `ANSIBLASTER_DEFAULTS__SSH__PASSWORD=...` / `ANSIBLASTER_DEFAULTS__WINRM__PASSWORD=...` /
  `ANSIBLASTER_DEFAULTS__PSRP__PASSWORD=...`

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
├── models.py           # Run ORM model + RunStatus enum, plus the generic Setting(key, value)
│                       # model backing the Settings popup (see settings_store.py)
├── roles.py            # Role discovery: scans settings.roles_path, returns valid role names
├── role_vars.py        # discover_role_variables(roles_path, roles): parses each role's
│                       # meta/argument_specs.yml into {role: {var_name: {type, default,
│                       # required, description}}} -- backs the Deploy column's Variables area
├── settings_store.py   # Settings popup: get/set/delete helpers for the Setting table's two key
│                       # namespaces (role-variable-default overrides, host credential
│                       # overrides), plus apply_role_variable_overrides()/apply_host_overrides()
│                       # to merge them over discover_role_variables()/settings.defaults
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
├── portcheck.py        # check_port(host, port): service-agnostic async TCP connect + a
│                       # best-effort read of whatever banner the target volunteers unprompted
│                       # (works for SSH, naturally yields none for WinRM) backing the Deploy
│                       # column's Status row. Times the connect out with asyncio.wait(), not
│                       # asyncio.wait_for() -- see the docstring for why
├── browse.py           # Viewer tab: list_role_files/read_role_file, list_playbook_files/
│                       # read_playbook_file -- re-validates the role/playbook name and checks
│                       # every resolved path stays inside its expected base directory
├── routes/
│   ├── __init__.py     # aggregates routers for app.py to include
│   ├── pages.py        # GET / -- also threads discover_role_variables() through to index.html
│   │                   # alongside discover_roles(), for the Variables area's data-vars
│   ├── roles.py        # GET /roles fragment (distinct module from top-level roles.py --
│   │                   # that one discovers roles, this one serves the HTTP fragment), plus
│   │                   # the Viewer tab's GET /roles/{name}/files and .../file. Also threads
│   │                   # discover_role_variables() through, same as pages.py above
│   ├── playbooks.py    # GET /playbooks fragment (distinct from top-level playbooks.py, same
│   │                   # naming pattern as roles.py above), plus the Viewer tab's
│   │                   # GET /playbooks/{name}/files and .../file
│   ├── runs.py         # POST /runs, GET /runs, GET /runs/{job_id}, GET /runs/{job_id}/stream,
│   │                   # GET /runs/{job_id}/log, POST /runs/{job_id}/cancel. POST /runs also
│   │                   # parses/validates vars[<role>][<var_name>] fields (see "Role variables
│   │                   # (argument_specs)") -- _parse_role_variables(), _coerce_role_variables()
│   ├── target.py       # GET /target/check-port -- thin JSON wrapper around portcheck.py
│   └── settings.py     # GET /settings, POST /settings/role-variables,
│                       # POST /settings/role-variables/bulk,
│                       # DELETE /settings/role-variables/{name}, POST /settings/host -- see
│                       # "Settings popup". Every route returns the same
│                       # partials/settings_modal_body.html fragment, freshly re-rendered
├── templates/
│   ├── base.html         # Title bar (incl. the Settings popup's cog button) + the modal
│   │                     # overlay shell itself, plus the modal's own tab-switching/
│   │                     # refreshRoleList()-wiring script (see "Settings popup" for why that
│   │                     # script lives here and not in index.html) -- the only template other
│   │                     # than index.html's own content block
│   ├── index.html       # 3-column workspace + bottom panel; owns nearly all client-side JS
│   │                   # (fuzzy filter, playbook->checkbox, run tabs, EventSource management)
│   └── partials/
│       ├── role_list.html
│       ├── playbook_list.html  # playbook buttons, each with its roles baked in as a data
│       │                       # attribute for the client-side check script
│       ├── file_browser.html   # Viewer tab: one role's/playbook's file list
│       ├── file_content.html   # Viewer tab: one file's read-only content
│       ├── eye_icon.html       # shared inline SVG for every eyeball view button
│       ├── save_icon.html      # shared inline SVG for the Deploy column's "Save as Default"
│       │                       # buttons (the Settings popup itself has no per-row save
│       │                       # buttons -- see "Settings popup")
│       ├── settings_icon.html  # the title bar's cog button SVG
│       ├── settings_modal_body.html  # the Settings popup's content -- two tabs (Role
│       │                             # Variables, Host Variables), rendered by GET /settings
│       │                             # and every settings/* route's response (see "Settings
│       │                             # popup")
│       ├── run_list.html
│       ├── run_row.html     # single history-list item; opened via a delegated fetch(),
│       │                   # not hx-get (see "Backend & UI")
│       └── run_detail.html  # one run's status + log; relocated into a run tab client-side
└── static/
    ├── htmx.min.js     # vendored, not CDN — the app must work with no outbound internet access
    └── style.css       # Dracula palette + the 3-column/bottom-panel IDE layout
```

- `tests/` mirrors this layout alongside `src/` (not inside the package): `test_roles.py`,
  `test_role_vars.py`, `test_playbooks.py`, `test_inventory.py`, `test_jobs.py`,
  `test_portcheck.py`, `test_browse.py`, `test_settings_store.py`, `test_routes_pages.py`,
  `test_routes_roles.py`, `test_routes_playbooks.py`, `test_routes_runs.py`,
  `test_routes_target.py`, `test_routes_settings.py`, plus a shared `conftest.py` (the `client`
  fixture — a `TestClient` wired to per-test tmp_path roles/playbooks/artifacts/DB paths — and
  `make_role`/`make_playbook` helpers; `make_role` takes an optional `argument_specs=` dict to
  write a `meta/argument_specs.yml` for it).
- Tests mock `ansible-runner` execution (`monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", ...)`)
  rather than running real playbooks/SSH — no live target host is required to run the test suite.
- **The full suite must pass unattended in GitHub Actions**, not just locally — nothing may depend on
  interactive input, a locally-cached resource, or network behavior that only happens to be fast on a
  given machine. `test_portcheck.py`/`test_routes_target.py` come closest to violating this: they do
  exercise real sockets (a loopback listener the test itself starts, an unused local port, a
  non-routable documentation-range IP, an unresolvable `.invalid` hostname), but only ever against
  `127.0.0.1` or addresses guaranteed to fail — none of it depends on a real remote host answering.
  That's still worth watching if `portcheck.py` changes: `check_port()` uses `asyncio.wait()`
  rather than `asyncio.wait_for()` specifically so `connect_timeout` is enforced even when
  hostname resolution (a blocking `getaddrinfo()` call `asyncio` runs in a worker thread) is slow to
  fail — `wait_for()` waits for a cancelled task to actually unwind before raising, which a
  still-running thread-pool call can't be made to do, so on a run where DNS resolution for a bad
  hostname is unusually slow, `wait_for()` would silently block past its own timeout instead of
  enforcing it. That exact pattern (a CI job hanging indefinitely on "Run tests" with no failure
  and no useful log output, since nothing ever raises) is worth recognizing on sight if it recurs
  elsewhere: any `wait_for()`/`shield()` around a coroutine that bottoms out in a thread-pool call
  (DNS resolution, blocking file I/O via `run_in_executor`, etc.) has the same gap.

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
  functions just work) and `httpx` (for FastAPI's `TestClient`). `pytest-timeout` sets a global
  60s-per-test watchdog (`[tool.pytest.ini_options] timeout` in `pyproject.toml`) purely as a
  CI safety net: the full suite normally runs in a few seconds, so this isn't a tight budget,
  it's there so a hang fails loudly with a full multi-thread traceback (`ansible-runner` and
  its callbacks run on their own background threads, not just the asyncio event loop -- see
  "Job execution model") instead of silently consuming the whole GitHub Actions job the way a
  since-fixed `check_port()` bug once did (20+ minutes stuck on "Run tests" with no output at
  all -- see `portcheck.py`'s docstring). If this timeout ever actually fires in CI, the
  resulting traceback is the way to find out what's really stuck, rather than guessing blind.
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
  `ansible-core`/`ansible-runner`/`pywinrm`/`pypsrp` are just Python deps already in
  `pyproject.toml`, installed into the venv like everything else.
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
