---
name: start-dev-server
description: Start a local AnsiBlaster web server with the bundled example roles so a change can be viewed or tested in the browser. Use when asked to run, start, or show the app locally.
---

# Start the dev server

Run `scripts/dev-server.sh` from the repo root. It installs dependencies (`uv sync`), points
AnsiBlaster at the bundled `example/` roles/playbooks, keeps its database and artifacts in the
gitignored `.dev-data/` directory, and serves on http://localhost:8000 (override with `PORT=`).

The script runs in the foreground, so start it in the background:

```bash
scripts/dev-server.sh            # or: scripts/dev-server.sh --reload  (auto-reload on edits)
```

With the Bash tool, use `run_in_background: true`. Then confirm it's up and tell the user the URL:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/   # expect 200
```

Notes:
- If port 8000 is already in use, a previous server is probably still running; stop it first
  (find it with `pgrep -af "[a]nsiblaster"`) rather than starting a second one.
- Run targets need a real host; the example roles can't be applied without one, so the server is
  for inspecting UI/settings behavior, not for completing a run.
- `--reload` restarts on Python changes; template/static edits are picked up either way.
