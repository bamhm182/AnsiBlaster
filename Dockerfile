# syntax=docker/dockerfile:1

########################################
# Builder: resolve deps + build the app into a self-contained venv.
# Nothing from this stage except /app/.venv makes it into the runtime image.
########################################
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies before copying source, so editing application code doesn't bust the
# (much slower) dependency-resolution layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

########################################
# Runtime: lean image with just the venv + what Ansible needs to connect out to targets.
########################################
FROM python:3.11-slim AS runtime

# sshpass + openssh-client: Ansible's ssh connection plugin needs both to authenticate to
# Linux targets with a password (see CLAUDE.md's "Ansible execution" section -- sshpass
# alone doesn't provide the ssh binary itself). gosu drops privileges from root to the app
# user after the entrypoint's PUID/PGID remap below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends sshpass openssh-client gosu \
    && rm -rf /var/lib/apt/lists/*

# Non-root by default. docker-entrypoint.sh remaps this user's uid/gid to PUID/PGID (default
# 1000/1000, a no-op at those values) at container start, so a bind-mounted host directory
# doesn't need pre-matching ownership -- the common self-hosted-tool PUID/PGID convention.
RUN groupadd --gid 1000 ansiblaster \
    && useradd --uid 1000 --gid ansiblaster --create-home --shell /usr/sbin/nologin ansiblaster

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Matches settings.py's defaults exactly (ansible.roles_path, ansible.playbooks_path,
# ansible.artifacts_path, database.path's parent dir), so the image works out of the box once
# you bind-mount your own roles at /opt/ansible/roles -- no config file or env vars required
# for a basic setup.
RUN mkdir -p /opt/ansible/roles /opt/ansible/playbooks /opt/ansiblaster/artifacts \
    && chown -R ansiblaster:ansiblaster /opt/ansiblaster

VOLUME ["/opt/ansible/roles", "/opt/ansible/playbooks", "/opt/ansiblaster"]

ENV PUID=1000 PGID=1000

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/')" || exit 1

# Starts as root (required to do the PUID/PGID remap below) and drops to the ansiblaster
# user via gosu before actually running the app -- see docker-entrypoint.sh.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["ansiblaster"]
