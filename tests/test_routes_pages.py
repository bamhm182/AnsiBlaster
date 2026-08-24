from __future__ import annotations

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
