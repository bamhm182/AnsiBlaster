# example/

Sample content for `docker-compose.yml`'s default `HOST_ROLES_DIR`/`HOST_PLAYBOOKS_DIR` (see
`.env.example`), so `docker compose up` has something real to show on first run instead of an
empty checklist.

- `roles/apache`, `roles/mysql`, `roles/php` — a minimal LAMP stack for an **Ubuntu/Debian**
  target (they use `ansible.builtin.apt`; nothing more exotic than `ansible-core` itself is
  required — no extra collections to install).
- `playbooks/lamp.yml` — the preset that selects all three roles at once (see CLAUDE.md's
  "Playbooks (role presets)" section).

This is demo content, not a production-ready LAMP setup: no firewall rules, no TLS, and MySQL
is left with its package-default (unset/prompt-based) root credentials — set those yourself
before using this against anything real. Point `HOST_ROLES_DIR`/`HOST_PLAYBOOKS_DIR` (or the
equivalent `ansible.roles_path`/`ansible.playbooks_path` config keys) at your own directory
once you have real roles to run.
