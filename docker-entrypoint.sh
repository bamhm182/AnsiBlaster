#!/bin/sh
# Remaps the built-in `ansiblaster` user/group to PUID/PGID (default 1000/1000, a no-op at
# those defaults), then drops from root to that user to actually run the app. This lets a
# bind-mounted host directory (roles, playbooks, artifacts, db) just work without needing its
# ownership pre-matched to some fixed in-image uid -- set PUID/PGID to match the host user
# that owns those directories instead. See CLAUDE.md's Distribution section.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -g ansiblaster)" != "$PGID" ]; then
    groupmod -o -g "$PGID" ansiblaster
fi

if [ "$(id -u ansiblaster)" != "$PUID" ]; then
    usermod -o -u "$PUID" ansiblaster
fi

# Only /opt/ansiblaster (artifacts + the default sqlite db location) is ever written by the
# app itself, so it's the only path safe to chown here -- and non-recursively, since anything
# the app creates under it from here on is already created by the correctly-mapped user.
# /opt/ansible/roles and /opt/ansible/playbooks are expected to be a read-only bind mount of
# the user's own existing Ansible content: chown'ing a bind mount changes ownership on the
# *host* filesystem too, which those paths deliberately avoid.
chown ansiblaster:ansiblaster /opt/ansiblaster

exec gosu ansiblaster "$@"
