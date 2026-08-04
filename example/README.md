# example/

Sample content for `docker-compose.yml`'s default `HOST_ROLES_DIR`/`HOST_PLAYBOOKS_DIR` (see
`.env.example`), so `docker compose up` has something real to show on first run instead of an
empty checklist.

- `roles/apache`, `roles/mysql`, `roles/php` — a minimal LAMP stack for an **Ubuntu/Debian**
  target (they use `ansible.builtin.apt`; nothing more exotic than `ansible-core` itself is
  required — no extra collections to install).
- `playbooks/lamp.yml` — the preset that selects all three roles at once (see CLAUDE.md's
  "Playbooks (role presets)" section).
- `roles/common-cli` — installs a few everyday CLI tools (`zip`/`unzip`, `curl`, `tmux`). No
  playbook preset; standalone roles like this are meant to be checked individually.
- `roles/docker-host` — installs Docker (Ubuntu's own `docker.io` package, not Docker's
  upstream repo, to keep this example free of an extra apt key/repo step), enables the
  service, and adds the connecting user to the `docker` group (skipped for `root`, which
  already has full access; takes effect on that user's next login).

This is demo content, not production-ready: no firewall rules, no TLS, MySQL is left with its
package-default (unset/prompt-based) root credentials, and Docker/CLI tools are installed with
no further hardening — set those up yourself before using this against anything real. Point
`HOST_ROLES_DIR`/`HOST_PLAYBOOKS_DIR` (or the equivalent `ansible.roles_path`/
`ansible.playbooks_path` config keys) at your own directory once you have real roles to run.
