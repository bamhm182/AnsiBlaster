"""Builds the ephemeral, single-host inventory ansible-runner needs for a run.

Every run targets exactly one host, so there is no static inventory file to maintain --
build_inventory() produces the in-memory Ansible inventory structure directly from a run's
target fields. The password is taken as a plain argument here, never read off a Run row: it
is never persisted (see CLAUDE.md's password-persistence note), only ever held in memory for
the life of the request/job.

Which connection variables get set depends entirely on the target's OS: Linux goes over SSH
(authenticated via sshpass), Windows over WinRM or PSRP (both HTTP/SOAP-family protocols
speaking to the same WinRM listener on the target, just via different Ansible connection
plugins/Python libraries -- pywinrm for one, pypsrp for the other).
"""

from __future__ import annotations

from typing import Any

from ansiblaster.models import TargetOS

# The single generic host alias used in every generated inventory -- there's only ever one
# host per run, so it doesn't need a meaningful name.
HOST_ALIAS = "target"

DEFAULT_PORTS: dict[TargetOS, int] = {
    TargetOS.LINUX: 22,
    TargetOS.WINDOWS: 5985,
    TargetOS.WINDOWS_PSRP: 5985,
}

# Ad hoc onboarding of an arbitrary IP the control host has likely never talked to before is
# the whole point of this app, so all three connection types deliberately skip the trust
# verification that would otherwise require a manual step (adding to known_hosts / trusting a
# WinRM cert) before the very first run against a new target.
_SSH_COMMON_ARGS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
# Shared by both Windows connection types: they're both just talking to the same WinRM
# listener, whose default HTTPS port is 5986 regardless of which client library connects to it.
_WINDOWS_HTTPS_PORT = 5986


def default_port(target_os: TargetOS) -> int:
    """Return the default connection port for a target OS (used to pre-fill the apply form)."""
    return DEFAULT_PORTS[target_os]


def build_inventory(
    *,
    target_os: TargetOS,
    target_host: str,
    target_port: int,
    target_user: str,
    target_password: str,
) -> dict[str, Any]:
    """Build the single-host Ansible inventory dict for one run."""
    if target_os is TargetOS.LINUX:
        host_vars = _linux_host_vars(target_host, target_port, target_user, target_password)
    elif target_os is TargetOS.WINDOWS:
        host_vars = _windows_host_vars(target_host, target_port, target_user, target_password)
    elif target_os is TargetOS.WINDOWS_PSRP:
        host_vars = _windows_psrp_host_vars(target_host, target_port, target_user, target_password)
    else:  # pragma: no cover - defensive, TargetOS is a closed enum
        raise ValueError(f"Unsupported target OS: {target_os!r}")

    return {"all": {"hosts": {HOST_ALIAS: host_vars}}}


def _linux_host_vars(
    target_host: str, target_port: int, target_user: str, target_password: str
) -> dict[str, Any]:
    return {
        "ansible_connection": "ssh",
        "ansible_host": target_host,
        "ansible_port": target_port,
        "ansible_user": target_user,
        "ansible_password": target_password,
        "ansible_ssh_common_args": _SSH_COMMON_ARGS,
        # jobs.py's generated playbook runs with become: true so roles can install system
        # packages; the app only ever collects one password, so the become/sudo password is
        # deliberately assumed to be the same as the login password (harmless no-op if
        # target_user is already root).
        "ansible_become_password": target_password,
    }


def _windows_host_vars(
    target_host: str, target_port: int, target_user: str, target_password: str
) -> dict[str, Any]:
    return {
        "ansible_connection": "winrm",
        "ansible_host": target_host,
        "ansible_port": target_port,
        "ansible_user": target_user,
        "ansible_password": target_password,
        "ansible_winrm_transport": "ntlm",
        "ansible_winrm_scheme": "https" if target_port == _WINDOWS_HTTPS_PORT else "http",
        # Only load-bearing over https, but harmless to always set -- avoids a manual
        # cert-trust step against a target's self-signed/default WinRM cert.
        "ansible_winrm_server_cert_validation": "ignore",
    }


def _windows_psrp_host_vars(
    target_host: str, target_port: int, target_user: str, target_password: str
) -> dict[str, Any]:
    return {
        "ansible_connection": "psrp",
        "ansible_host": target_host,
        "ansible_port": target_port,
        "ansible_user": target_user,
        "ansible_password": target_password,
        # Mirrors _windows_host_vars' choices above -- same reasoning, just PSRP's own var
        # names (ansible-core's builtin psrp connection plugin, backed by pypsrp).
        "ansible_psrp_auth": "ntlm",
        "ansible_psrp_protocol": "https" if target_port == _WINDOWS_HTTPS_PORT else "http",
        "ansible_psrp_cert_validation": "ignore",
    }
