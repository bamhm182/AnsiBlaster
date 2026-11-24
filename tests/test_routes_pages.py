from __future__ import annotations

import pytest

from tests.conftest import make_playbook, make_role


def test_index_lists_discovered_roles_and_playbooks(client, tmp_path):
    make_role(tmp_path, "docker-host")
    make_playbook(tmp_path, "lamp", ["apache", "mysql", "php"])

    response = client.get("/")

    assert response.status_code == 200
    assert "docker-host" in response.text
    assert "lamp" in response.text
    assert 'name="target_os"' in response.text


def test_index_bakes_data_vars_attribute_from_argument_specs(client, tmp_path):
    make_role(tmp_path, "apache", argument_specs={"apache_listen_port": {"type": "int"}})

    response = client.get("/")

    assert response.status_code == 200
    assert "data-vars=" in response.text
    assert "apache_listen_port" in response.text


def test_index_shows_empty_hints_when_nothing_configured(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "No roles found" in response.text
    assert "No playbooks found" in response.text
    assert "No runs yet" in response.text


def test_index_has_trailing_slash_self_heal_script_before_relative_assets(client):
    """Regression test: base.html's inline redirect script (window.location.replace() when
    window.location.pathname doesn't end in "/") must appear -- and, critically, must appear
    *before* -- the relative static/style.css and static/htmx.min.js tags, or the browser's
    preload scanner/parser can dispatch those fetches (against the wrong base, when reverse-
    proxied at a subpath with no trailing slash -- e.g. Coder OSS's path-based workspace-app
    proxying) before the redirect has a chance to run. See CLAUDE.md's "Backend & UI" section.
    """
    response = client.get("/")

    assert response.status_code == 200
    redirect_index = response.text.index("window.location.replace")
    style_index = response.text.index('href="static/style.css"')
    htmx_index = response.text.index('src="static/htmx.min.js"')
    assert redirect_index < style_index
    assert redirect_index < htmx_index


def test_index_embeds_os_defaults_as_raw_js_not_html_escaped(make_client):
    """Regression test: index.html's inline <script> embeds defaults.*.username/password via
    a filter that must NOT run through Jinja's normal HTML-autoescaping -- that would turn
    `"deploy"` into `&#34;deploy&#34;`, which is a JS syntax error (breaks every
    OS-default-prefill and playbook-click-to-check interaction on the page). Caught by
    actually loading the rendered page in a browser and seeing `Unexpected token '&'`.
    """
    with make_client(ANSIBLASTER_DEFAULTS__SSH__USERNAME="deploy") as client:
        response = client.get("/")

    assert response.status_code == 200
    assert '"deploy"' in response.text
    assert "&#34;deploy&#34;" not in response.text
    assert "&#34;" not in response.text.split("<script>", 1)[1]


def test_static_files_must_be_revalidated(client):
    response = client.get("/static/style.css")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_index_exposes_url_parameter_hooks(client):
    """applyUrlParams() (client-side) selects port presets by data-preset -- both must ship."""
    response = client.get("/")

    assert response.status_code == 200
    assert "applyUrlParams" in response.text
    for preset in ("ssh", "winrm", "winrm-secure", "psrp", "psrp-secure"):
        assert f'data-preset="{preset}"' in response.text


# ---- ?execute=1 (server-side, so curl/scripts work) --------------------------------------


class _FakeRunner:
    status = "successful"
    rc = 0


def _fake_run_async(calls):
    def _fake(**kwargs):
        calls.append(kwargs)
        kwargs["status_handler"]({"status": "running"}, runner_config=None)
        kwargs["finished_callback"](_FakeRunner())
        return (None, _FakeRunner())

    return _fake


@pytest.fixture
def execute_client(make_client):
    with make_client(ANSIBLASTER_SERVER__ALLOW_URL_EXECUTE="true") as c:
        yield c


def _exec(client, monkeypatch, query, headers=None):
    calls: list[dict] = []
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async(calls))
    response = client.get(f"/?{query}", headers=headers or {}, follow_redirects=False)
    return response, calls


def test_execute_with_curl_returns_json_and_starts_run(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache")
    response, calls = _exec(
        execute_client, monkeypatch, "role=apache&host=10.0.0.5&user=root&password=x&execute=1"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["roles"] == ["apache"]
    assert body["target"] == "root@10.0.0.5:22"
    assert body["log"] == f"runs/{body['id']}/log"
    assert calls[0]["playbook"][0]["roles"] == ["apache"]
    host_vars = calls[0]["inventory"]["all"]["hosts"]["target"]
    assert host_vars["ansible_password"] == "x"


def test_execute_from_browser_redirects_to_page_with_run_open(
    execute_client, tmp_path, monkeypatch
):
    make_role(tmp_path, "apache")
    response, calls = _exec(
        execute_client,
        monkeypatch,
        "role=apache&host=10.0.0.5&user=root&execute=1",
        headers={"accept": "text/html,application/xhtml+xml", "sec-fetch-mode": "navigate"},
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("?")  # relative, proxy-safe
    assert "execute" not in location and "run=" in location and "role=apache" in location
    assert len(calls) == 1


def test_execute_playbook_union_with_roles_and_vars(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"port": {"type": "int", "default": 80}})
    make_role(tmp_path, "mysql", argument_specs={"port": {"type": "int", "default": 3306}})
    make_role(tmp_path, "php")
    make_playbook(tmp_path, "lamp", ["apache", "mysql"])
    response, calls = _exec(
        execute_client,
        monkeypatch,
        "playbook=lamp&role=php&host=h&user=u&vars[port]=1&vars[mysql][port]=3307&execute=1",
    )

    assert response.status_code == 201
    roles = calls[0]["playbook"][0]["roles"]
    assert roles == [
        {"role": "apache", "vars": {"port": 1}},
        {"role": "mysql", "vars": {"port": 3307}},  # per-role beats global
        "php",
    ]


def test_execute_unspecified_variables_use_declared_defaults(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"port": {"type": "int", "default": 80}})
    _, calls = _exec(execute_client, monkeypatch, "role=apache&host=h&user=u&execute=1")

    assert calls[0]["playbook"][0]["roles"] == [{"role": "apache", "vars": {"port": 80}}]


def test_execute_uses_preset_defaults_for_credentials_and_port(
    execute_client, tmp_path, monkeypatch
):
    make_role(tmp_path, "iis")
    execute_client.post("/settings/host", data={"winrm_username": "Admin", "winrm_password": "pw"})
    _, calls = _exec(execute_client, monkeypatch, "role=iis&preset=winrm-secure&host=h&execute=1")

    host_vars = calls[0]["inventory"]["all"]["hosts"]["target"]
    assert host_vars["ansible_port"] == 5986
    assert host_vars["ansible_user"] == "Admin"
    assert host_vars["ansible_password"] == "pw"
    assert host_vars["ansible_connection"] == "winrm"


def test_execute_refused_when_anything_does_not_resolve(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache")
    for query, fragment in (
        ("role=nope&host=h&user=u", 'unknown role "nope"'),
        ("playbook=nope&role=apache&host=h&user=u", 'unknown playbook "nope"'),
        ("role=apache&preset=bogus&host=h&user=u", 'unknown preset "bogus"'),
        ("role=apache&user=u", "host is required"),
        ("host=h&user=u", "no roles selected"),
        ("role=apache&host=h&user=u&vars[apache][x]=1", 'has no variable "x"'),
        ("role=apache&host=h", "required"),  # no user and no configured default
    ):
        response, calls = _exec(execute_client, monkeypatch, query + "&execute=1")
        assert response.status_code == 400, query
        assert fragment in response.json()["error"], query
        assert calls == [], query


def test_execute_required_variable_missing_is_refused(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"secret": {"type": "str", "required": True}})
    response, calls = _exec(execute_client, monkeypatch, "role=apache&host=h&user=u&execute=1")

    assert response.status_code == 400
    assert "'secret' is required" in response.json()["error"]
    assert calls == []


def test_execute_refused_for_cross_site_subresource_requests(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache")
    response, calls = _exec(
        execute_client,
        monkeypatch,
        "role=apache&host=h&user=u&execute=1",
        headers={"sec-fetch-mode": "no-cors", "sec-fetch-dest": "image"},
    )

    assert response.status_code == 400
    assert calls == []


def test_execute_refusal_in_browser_renders_page_with_error(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache")
    response, calls = _exec(
        execute_client,
        monkeypatch,
        "role=nope&host=h&user=u&execute=1",
        headers={"accept": "text/html", "sec-fetch-mode": "navigate"},
    )

    assert response.status_code == 200
    assert "unknown role" in response.text
    assert calls == []


def test_without_execute_nothing_is_launched(execute_client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache")
    response, calls = _exec(execute_client, monkeypatch, "role=apache&host=h&user=u")

    assert response.status_code == 200
    assert calls == []


def test_execute_is_disabled_by_default(client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache")
    response, calls = _exec(client, monkeypatch, "role=apache&host=h&user=u&execute=1")

    assert response.status_code == 403
    assert "ANSIBLASTER_SERVER__ALLOW_URL_EXECUTE" in response.json()["error"]
    assert calls == []


def test_disabled_execute_in_browser_still_renders_and_prefill_is_unaffected(
    client, tmp_path, monkeypatch
):
    make_role(tmp_path, "apache")
    response, calls = _exec(
        client,
        monkeypatch,
        "role=apache&host=h&user=u&execute=1",
        headers={"accept": "text/html", "sec-fetch-mode": "navigate"},
    )

    assert response.status_code == 200
    assert "is disabled" in response.text
    assert calls == []


def test_allow_url_execute_can_be_enabled_in_config_file(make_client, tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("server:\n  allow_url_execute: true\n")
    make_role(tmp_path, "apache")
    with make_client() as c:
        response, calls = _exec(c, monkeypatch, "role=apache&host=h&user=u&execute=1")

    assert response.status_code == 201
    assert len(calls) == 1
