"""External links use a separate credential-free, bounded live CI gate."""

import importlib.util
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("public_links", ROOT / "scripts/check-public-links.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response(status=200, location=None):
    return lambda _: (status, location)


@pytest.mark.parametrize("status", [200, 204, 206, 299])
def test_success_is_only_http_reachability(checker, status):
    result = checker.check_url("https://docs.example.org/guide#heading", request=response(status))
    assert result == {
        "status": "reachable",
        "chain": [{"url": "https://docs.example.org/guide", "http_status": status}],
    }


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 429, 500, 503])
def test_broken_or_unqualified_http_status_fails(checker, status):
    result = checker.check_url("https://docs.example.org/guide", request=response(status))
    assert result["status"] == "http_failure" and result["chain"][0]["http_status"] == status


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/doc",
        "http://[::1]/doc",
        "http://169.254.169.254/meta",
        "http://10.0.0.1/doc",
        "http://localhost/doc",
        "http://local.local/doc",
        "http://224.0.0.1/doc",
        "http://[ff02::1]/doc",
        "http://[fec0::1]/doc",
        "https://name:synthetic-password@docs.example.org/",
        "https://docs.example.org/?api_key=synthetic-secret",
        "https://docs.example.org/?access_token=synthetic-secret",
        "https://docs.example.org:70000/",
        "file:///private/path",
        "https://docs.example.org/\nunsafe",
    ],
)
def test_unsafe_url_never_reaches_request_or_exposes_secret(checker, url):
    def forbidden(_):
        raise AssertionError("Unsafe URL reached transport")

    result = checker.check_url(url, request=forbidden)
    assert result["status"] in {"unsafe_url", "nonpublic_address"} and result["chain"] == []
    assert "synthetic" not in json.dumps(result)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fd00::1", "224.0.0.1", "ff02::1", "fec0::1"],
)
def test_dns_resolution_to_private_addresses_is_rejected(checker, monkeypatch, address):
    monkeypatch.setattr(
        checker.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(checker.LinkError, match="nonpublic_address"):
        checker.public_addresses("public.example.org", 443)


def test_tcp_connection_uses_vetted_sockaddr_without_a_second_dns_lookup(checker, monkeypatch):
    calls = []

    class Socket:
        def settimeout(self, timeout):
            calls.append(("timeout", timeout))

        def connect(self, address):
            calls.append(("connect", address))

    monkeypatch.setattr(checker.socket, "socket", lambda *args: Socket())
    monkeypatch.setattr(checker.socket, "getaddrinfo", lambda *args: pytest.fail("Second DNS lookup"))
    checker.pinned_connect([(socket.AF_INET, socket.SOCK_STREAM, 6, ("9.9.9.9", 443))], 5)
    assert calls == [("timeout", 5), ("connect", ("9.9.9.9", 443))]


def test_failed_socket_is_closed_before_trying_next_vetted_address(checker, monkeypatch):
    sockets = []

    class Socket:
        closed = False

        def settimeout(self, timeout):
            pass

        def connect(self, address):
            if address[0] == "9.9.9.9":
                raise OSError("synthetic connection failure")

        def close(self):
            self.closed = True

    def factory(*args):
        item = Socket()
        sockets.append(item)
        return item

    monkeypatch.setattr(checker.socket, "socket", factory)
    result = checker.pinned_connect(
        [(socket.AF_INET, socket.SOCK_STREAM, 6, (address, 443)) for address in ["9.9.9.9", "8.8.8.8"]], 5
    )
    assert sockets[0].closed and result is sockets[1] and not result.closed


@pytest.mark.parametrize(
    "location,status",
    [
        ("http://127.0.0.1/", "nonpublic_address"),
        ("https://user:synthetic-secret@docs.example.org/", "unsafe_url"),
        ("http://docs.example.org/plain", "https_downgrade"),
    ],
)
def test_redirects_are_checked_before_next_request(checker, location, status):
    calls = []

    def request(url):
        calls.append(url)
        return 302, location

    result = checker.check_url("https://docs.example.org/start", request=request)
    assert result["status"] == status and calls == ["https://docs.example.org/start"]
    assert "synthetic" not in json.dumps(result)


def test_relative_redirect_and_ignored_cookie_state(checker):
    calls = []

    def request(url):
        calls.append(url)
        return (302, "/guide") if len(calls) == 1 else (200, None)

    assert checker.check_url("https://docs.example.org/start", request=request)["status"] == "reachable"
    assert calls == ["https://docs.example.org/start", "https://docs.example.org/guide"]


@pytest.mark.parametrize(
    "mode,expected",
    [("cycle", "redirect_cycle"), ("limit", "redirect_limit"), ("missing", "missing_redirect_location")],
)
def test_unbounded_or_invalid_redirects_fail(checker, mode, expected):
    def request(url):
        return 302, None if mode == "missing" else url if mode == "cycle" else url + "next"

    result = checker.check_url("https://docs.example.org/start", request=request)
    assert result["status"] == expected and len(result["chain"]) <= checker.MAX_REDIRECTS + 1


def test_request_closes_connection_preserves_tls_hostname_and_uses_no_credentials(checker, monkeypatch):
    captured = {}
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-private-proxy:8000")
    monkeypatch.setenv("API_KEY", "synthetic-secret")
    monkeypatch.setattr(
        checker,
        "public_addresses",
        lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, ("9.9.9.9", port))],
    )

    class Connection:
        def __init__(self, host, port, **kwargs):
            captured.update(host=host, port=port, options=kwargs)

        def request(self, method, path, headers):
            captured.update(method=method, path=path, headers=headers)

        def getresponse(self):
            return type("Response", (), {"status": 200, "getheader": lambda self, name: None})()

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(checker.http.client, "HTTPSConnection", Connection)
    assert checker.request_once("https://docs.example.org/guide") == (200, None)
    assert captured["host"] == "docs.example.org" and captured["port"] == 443 and captured["closed"]
    assert set(captured["headers"]) == {"User-Agent", "Accept"}
    assert "synthetic" not in json.dumps(captured)


def test_actual_http_request_with_injected_trusted_resolver(checker, monkeypatch):
    # Loopback is admitted only by this injected test resolver. Default URL and
    # DNS private-address rejection are tested independently above.
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append((self.path, dict(self.headers)))
            self.send_response(404)
            self.send_header("Set-Cookie", "synthetic-cookie")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        checker,
        "public_addresses",
        lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, server.server_address)],
    )
    try:
        assert checker.request_once("http://docs.example.org/missing") == (404, None)
        assert observed[0][0] == "/missing" and observed[0][1]["Host"] == "docs.example.org"
        assert "Cookie" not in observed[0][1] and "Authorization" not in observed[0][1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_markdown_reference_html_and_fragment_links_are_deduplicated(checker, tmp_path):
    (tmp_path / "README.md").write_text(
        '[One][x]\n\n[x]: https://docs.example.org/guide#one\n\n<a href="https://docs.example.org/guide#two">two</a>\n\n```md\n[code](https://unrequested.example.org/)\n```\n'
    )
    links, inputs, errors = checker.inventory(tmp_path)
    assert list(links) == ["https://docs.example.org/guide"] and len(links[next(iter(links))]) == 2
    assert all(ref["remote_fragment_present"] for ref in links[next(iter(links))])
    assert list(inputs) == ["README.md"] and errors == []


def test_symlinks_and_sensitive_links_are_never_read_or_reported(checker, tmp_path):
    secret = tmp_path.parent / "private-link-secret.md"
    secret.write_text("synthetic private document")
    (tmp_path / "private.md").symlink_to(secret)
    (tmp_path / "README.md").write_text(
        '<a href="https://user:synthetic-secret@docs.example.org/">unsafe</a>'
    )
    links, inputs, errors = checker.inventory(tmp_path)
    assert not links and list(inputs) == ["README.md"] and len(errors) == 2
    assert "synthetic" not in json.dumps(errors)


def test_whole_tree_and_network_failures_remain_in_failed_report(checker, tmp_path):
    (tmp_path / "README.md").write_text(
        "[OK](https://docs.example.org/ok) [Bad](https://docs.example.org/bad)"
    )
    report = checker.qualify(
        tmp_path,
        run=lambda url, timeout: checker.check_url(
            url, request=response(404 if url.endswith("bad") else 200)
        ),
    )
    assert report["result"] == "failed" and [x["status"] for x in report["links"]] == [
        "reachable",
        "http_failure",
    ]
    assert "no remote-anchor" in report["scope"] and report["inputs_sha256"]


def test_changed_documents_fail_instead_of_binding_wrong_inputs(checker, tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("[link](https://docs.example.org/guide)")

    def mutate(url, timeout):
        doc.write_text("changed")
        return {"status": "reachable", "chain": []}

    report = checker.qualify(tmp_path, run=mutate)
    assert report["result"] == "failed" and report["inputs_changed"]
    assert report["links"][0]["status"] == "reachable"


def test_parser_change_invalidates_otherwise_successful_observations(checker, tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("[link](https://docs.example.org/guide)")
    (tmp_path / "scripts").mkdir()
    parser = tmp_path / "scripts/check-governance.py"
    parser.write_bytes((ROOT / "scripts/check-governance.py").read_bytes())
    monkeypatch.setattr(checker, "ROOT", tmp_path)

    def mutate(url, timeout):
        parser.write_bytes(parser.read_bytes() + b"\n# changed during qualification\n")
        return checker.check_url(url, request=response())

    report = checker.qualify(tmp_path, run=mutate)
    assert report["result"] == "failed" and report["inputs_changed"]
    assert report["links"][0]["status"] == "reachable"


def test_query_variants_have_distinct_identity_without_query_disclosure(checker, tmp_path):
    (tmp_path / "README.md").write_text(
        "[One](https://docs.example.org/?version=one) [Two](https://docs.example.org/?version=two)"
    )
    report = checker.qualify(tmp_path, run=lambda url, timeout: checker.check_url(url, request=response()))
    assert report["result"] == "passed" and len(report["links"]) == 2
    assert len({row["request_sha256"] for row in report["links"]}) == 2
    assert all(row["url"] == "https://docs.example.org/" for row in report["links"])
    assert "version=" not in json.dumps(report)


@pytest.mark.parametrize("name,job", [("ci.yml", "contracts"), ("release.yml", "release")])
def test_public_workflows_gate_later_work_and_retain_failed_link_evidence(name, job):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
    steps = workflow["jobs"][job]["steps"]
    link = next(step for step in steps if step.get("id") == "public_links")
    scope = link["run"]
    command = next(line for line in scope.splitlines() if "docker run" in line and "check-public-links.py" in line)
    assert "--env UV_CACHE_DIR=/tmp/uv-cache" in command and command.count("--env ") == 1
    assert "continue-on-error" not in link
    assert "--read-only --cap-drop ALL --security-opt no-new-privileges" in command
    assert "--tmpfs /tmp:rw,size=64m" in command and "--output /output/report.json" in command
    assert '"$UBI_TEST_IMAGE" uv run --frozen --no-sync python scripts/check-public-links.py' in command
    assert "-e " not in command and "--network none" not in command and "env" not in link
    retained = next(step for step in steps if step.get("with", {}).get("name") == "public-link-evidence")
    assert retained["if"] == "always() && steps.public_links.outcome != 'skipped'"
    assert retained["with"]["if-no-files-found"] == "error"
    assert steps.index(link) < steps.index(retained)
    assert scope.index("./scripts/test-local.sh") < scope.index("check-public-links.py")
    assert '--report-dir "$RUNNER_TEMP/ubi-cleanup-report" -- bash -euo pipefail -c' in scope
    assert scope.index("check-public-links.py") < scope.index("scan-security.py")
    assert all(
        steps.index(link) < index
        for index, step in enumerate(steps)
        if " publish " in step.get("run", "")
    )


def test_timeout_worker_does_not_store_subprocess_exception_or_url_credentials(checker, monkeypatch):
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(["python"], 1)),
    )
    assert checker.worker("https://docs.example.org/guide", 1) == {
        "status": "timeout",
        "chain": [],
        "attempts": [],
    }


def test_cli_failed_check_is_nonzero_and_existing_evidence_is_not_overwritten(checker, tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("[link](https://docs.example.org/missing)")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/check-governance.py").write_bytes(
        (ROOT / "scripts/check-governance.py").read_bytes()
    )
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(
        checker,
        "worker",
        lambda *args: {
            "status": "http_failure",
            "chain": [{"url": "https://docs.example.org/missing", "http_status": 404}],
        },
    )
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["check-public-links.py", "--output", str(output)])
    assert checker.main() == 1 and json.loads(output.read_text())["result"] == "failed"
    original = output.read_bytes()
    with pytest.raises(SystemExit):
        checker.main()
    assert output.read_bytes() == original


def test_public_custom_ports_are_qualified_without_private_address_exceptions(checker):
    assert checker.checked_url("https://docs.example.org:8443/guide") == "https://docs.example.org:8443/guide"


@pytest.mark.parametrize(
    "status,expected", [(404, False), (401, False), (429, True), (502, True), (503, True), (504, True)]
)
def test_only_transient_http_failures_are_retried(checker, status, expected):
    result = checker.check_url("https://docs.example.org/guide", request=response(status))
    assert checker.retryable(result) is expected


def test_certificate_validation_failure_is_not_retried_or_exposed(checker):
    import ssl

    def fail(_):
        raise ssl.SSLCertVerificationError("synthetic-sensitive-validation-detail")

    result = checker.check_url("https://docs.example.org/guide", request=fail)
    assert result["status"] == "tls_validation_failed" and not checker.retryable(result)
    assert "synthetic" not in json.dumps(result)


def test_recovered_transient_attempt_is_retained_in_worker_report(checker, monkeypatch):
    attempts = [
        checker.check_url("https://docs.example.org/guide", request=response(503)),
        checker.check_url("https://docs.example.org/guide", request=response(200)),
    ]
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": "\n".join(json.dumps(x) for x in attempts),
                "stderr": "synthetic-secret",
            },
        )(),
    )
    result = checker.worker("https://docs.example.org/guide", 1)
    assert result["status"] == "reachable" and result["attempts"] == attempts
    assert "synthetic" not in json.dumps(result)


def test_timeout_preserves_prior_http_attempt(checker, monkeypatch):
    attempt = checker.check_url("https://docs.example.org/guide", request=response(503))

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(["python"], 1, output=(json.dumps(attempt) + "\n").encode())

    monkeypatch.setattr(checker.subprocess, "run", fail)
    result = checker.worker("https://docs.example.org/guide", 1)
    assert result["status"] == "timeout" and result["attempts"] == [attempt]


@pytest.mark.parametrize(
    "row",
    [
        {"status": "reachable", "chain": []},
        {"status": "reachable", "chain": [{"url": "https://docs.example.org/", "http_status": 404}]},
        {"status": "reachable", "chain": [{"url": "https://docs.example.org/", "http_status": True}]},
        {"status": "reachable", "chain": [{"url": "http://127.0.0.1/", "http_status": 200}]},
    ],
)
def test_malformed_worker_success_does_not_pass(checker, monkeypatch, row):
    monkeypatch.setattr(
        checker.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"returncode": 0, "stdout": json.dumps(row)})(),
    )
    assert checker.worker("https://docs.example.org/guide", 1)["status"] == "worker_failure"


def test_global_deadline_marks_unattempted_links_without_network_io(checker, tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("[link](https://docs.example.org/guide)")
    ticks = iter([0, checker.RUN_TIMEOUT + 1])
    monkeypatch.setattr(checker.time, "monotonic", lambda: next(ticks))
    report = checker.qualify(tmp_path, run=lambda *args: pytest.fail("Deadline still started network"))
    assert report["result"] == "failed" and report["links"][0]["status"] == "run_deadline"


@pytest.mark.parametrize(
    "workflow_name,link_status,security_status",
    [
        ("ci.yml", 0, 0),
        ("ci.yml", 1, 0),
        ("ci.yml", 0, 1),
        ("ci.yml", 1, 1),
        ("release.yml", 1, 0),
        ("release.yml", 0, 1),
        ("release.yml", 1, 1),
    ],
)
def test_ci_links_are_advisory_but_security_and_release_checks_remain_required(
    tmp_path, workflow_name, link_status, security_status
):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / workflow_name).read_text())
    job = "contracts" if workflow_name == "ci.yml" else "release"
    step = next(s for s in workflow["jobs"][job]["steps"] if s.get("id") == "public_links")
    callback = shlex.split(step["run"].split("-- bash ", 1)[1])[-1]
    calls = tmp_path / "calls"
    stubs = r'''
    docker() { printf 'links\n' >> "$CALLS"; return "$LINK_STATUS"; }
    python() { printf 'security\n' >> "$CALLS"; return "$SECURITY_STATUS"; }
    export -f docker python
    exec bash -euo pipefail -c "$CALLBACK"
    '''
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", stubs],
        env={**os.environ, "CALLS": str(calls), "CALLBACK": callback,
             "LINK_STATUS": str(link_status), "SECURITY_STATUS": str(security_status),
             "RUNNER_TEMP": str(tmp_path), "UBI_TEST_RUN_LABEL": "synthetic-run",
             "UBI_TEST_IMAGE": "synthetic-test", "UBI_RUNTIME_IMAGE": "synthetic-runtime"},
        capture_output=True, text=True, timeout=10,
    )
    assert calls.read_text().splitlines() == ["links", "security"]
    expected_success = security_status == 0 and (workflow_name == "ci.yml" or link_status == 0)
    assert (result.returncode == 0) is expected_success, result.stderr
    assert ("::warning title=External documentation links::" in result.stdout) is (
        workflow_name == "ci.yml" and link_status != 0
    )
