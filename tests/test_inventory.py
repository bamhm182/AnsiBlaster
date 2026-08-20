from __future__ import annotations

from ansiblaster.inventory import (
    HOST_ALIAS,
    WINDOWS_HTTPS_PORT,
    build_inventory,
    connection_label,
    default_port,
)
from ansiblaster.models import TargetOS


def test_default_port_linux():
    assert default_port(TargetOS.LINUX) == 22


def test_default_port_windows():
    assert default_port(TargetOS.WINDOWS) == 5985


def test_default_port_windows_psrp():
    assert default_port(TargetOS.WINDOWS_PSRP) == 5985


def test_connection_label_ssh():
    assert connection_label(TargetOS.LINUX, 22) == "SSH"


def test_connection_label_ssh_on_a_custom_port_is_still_just_ssh():
    # Linux/SSH has no "(Secure)" concept -- WINDOWS_HTTPS_PORT is only meaningful for the two
    # Windows connection types.
    assert connection_label(TargetOS.LINUX, WINDOWS_HTTPS_PORT) == "SSH"


def test_connection_label_winrm():
    assert connection_label(TargetOS.WINDOWS, 5985) == "WinRM"


def test_connection_label_winrm_secure():
    assert connection_label(TargetOS.WINDOWS, WINDOWS_HTTPS_PORT) == "WinRM (Secure)"


def test_connection_label_psrp():
    assert connection_label(TargetOS.WINDOWS_PSRP, 5985) == "PSRP"


def test_connection_label_psrp_secure():
    assert connection_label(TargetOS.WINDOWS_PSRP, WINDOWS_HTTPS_PORT) == "PSRP (Secure)"


def test_build_inventory_uses_single_host_alias():
    inventory = build_inventory(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
    )

    hosts = inventory["all"]["hosts"]
    assert list(hosts.keys()) == [HOST_ALIAS]


def test_build_inventory_linux_sets_ssh_connection_vars():
    inventory = build_inventory(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=2222,
        target_user="root",
        target_password="hunter2",
    )

    host_vars = inventory["all"]["hosts"][HOST_ALIAS]
    assert host_vars["ansible_connection"] == "ssh"
    assert host_vars["ansible_host"] == "192.168.1.10"
    assert host_vars["ansible_port"] == 2222
    assert host_vars["ansible_user"] == "root"
    assert host_vars["ansible_password"] == "hunter2"


def test_build_inventory_linux_reuses_login_password_for_become():
    inventory = build_inventory(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="deploy",
        target_password="hunter2",
    )

    host_vars = inventory["all"]["hosts"][HOST_ALIAS]
    assert host_vars["ansible_become_password"] == "hunter2"


def test_build_inventory_linux_disables_strict_host_key_checking():
    inventory = build_inventory(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
    )

    host_vars = inventory["all"]["hosts"][HOST_ALIAS]
    assert "StrictHostKeyChecking=no" in host_vars["ansible_ssh_common_args"]
    assert "UserKnownHostsFile=/dev/null" in host_vars["ansible_ssh_common_args"]


def test_build_inventory_windows_sets_winrm_connection_vars_with_ntlm():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS,
        target_host="10.0.0.5",
        target_port=5985,
        target_user="Administrator",
        target_password="hunter2",
    )

    host_vars = inventory["all"]["hosts"][HOST_ALIAS]
    assert host_vars["ansible_connection"] == "winrm"
    assert host_vars["ansible_winrm_transport"] == "ntlm"
    assert host_vars["ansible_host"] == "10.0.0.5"
    assert host_vars["ansible_port"] == 5985
    assert host_vars["ansible_user"] == "Administrator"
    assert host_vars["ansible_password"] == "hunter2"


def test_build_inventory_windows_scheme_is_http_for_default_port():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS,
        target_host="10.0.0.5",
        target_port=5985,
        target_user="Administrator",
        target_password="hunter2",
    )

    assert inventory["all"]["hosts"][HOST_ALIAS]["ansible_winrm_scheme"] == "http"


def test_build_inventory_windows_scheme_is_https_for_5986():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS,
        target_host="10.0.0.5",
        target_port=5986,
        target_user="Administrator",
        target_password="hunter2",
    )

    assert inventory["all"]["hosts"][HOST_ALIAS]["ansible_winrm_scheme"] == "https"


def test_build_inventory_windows_ignores_cert_validation():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS,
        target_host="10.0.0.5",
        target_port=5986,
        target_user="Administrator",
        target_password="hunter2",
    )

    assert inventory["all"]["hosts"][HOST_ALIAS]["ansible_winrm_server_cert_validation"] == "ignore"


def test_build_inventory_windows_psrp_sets_psrp_connection_vars_with_ntlm():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS_PSRP,
        target_host="10.0.0.5",
        target_port=5985,
        target_user="Administrator",
        target_password="hunter2",
    )

    host_vars = inventory["all"]["hosts"][HOST_ALIAS]
    assert host_vars["ansible_connection"] == "psrp"
    assert host_vars["ansible_psrp_auth"] == "ntlm"
    assert host_vars["ansible_host"] == "10.0.0.5"
    assert host_vars["ansible_port"] == 5985
    assert host_vars["ansible_user"] == "Administrator"
    assert host_vars["ansible_password"] == "hunter2"


def test_build_inventory_windows_psrp_protocol_is_http_for_default_port():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS_PSRP,
        target_host="10.0.0.5",
        target_port=5985,
        target_user="Administrator",
        target_password="hunter2",
    )

    assert inventory["all"]["hosts"][HOST_ALIAS]["ansible_psrp_protocol"] == "http"


def test_build_inventory_windows_psrp_protocol_is_https_for_5986():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS_PSRP,
        target_host="10.0.0.5",
        target_port=5986,
        target_user="Administrator",
        target_password="hunter2",
    )

    assert inventory["all"]["hosts"][HOST_ALIAS]["ansible_psrp_protocol"] == "https"


def test_build_inventory_windows_psrp_ignores_cert_validation():
    inventory = build_inventory(
        target_os=TargetOS.WINDOWS_PSRP,
        target_host="10.0.0.5",
        target_port=5986,
        target_user="Administrator",
        target_password="hunter2",
    )

    assert inventory["all"]["hosts"][HOST_ALIAS]["ansible_psrp_cert_validation"] == "ignore"
