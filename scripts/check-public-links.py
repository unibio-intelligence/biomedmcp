#!/usr/bin/env python3
"""Separate live HTTP qualification for links in the public documentation tree.

No provider credentials, cookies, environment proxies or source response bodies
are used. Remote fragment/page semantics remain outside this HTTP gate.
"""

import argparse
import hashlib
import http.client
import ipaddress
import json
import re
import runpy
import socket
import ssl
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
MAX_LINKS = 256
MAX_DOCUMENT_BYTES = 2_000_000
MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3
LINK_TIMEOUT = 12
RUN_TIMEOUT = 240
AUTH_KEYS = {
    "apikey",
    "key",
    "token",
    "accesstoken",
    "auth",
    "authorization",
    "password",
    "secret",
    "clientsecret",
    "signature",
    "credential",
}


class LinkError(ValueError):
    pass


def public_address(value):
    address = ipaddress.ip_address(value)
    return address.is_global and not address.is_multicast and not getattr(address, "is_site_local", False)


def checked_url(value):
    if not isinstance(value, str) or len(value) > 8192 or re.search(r"[\x00-\x20\x7f]", value):
        raise LinkError("unsafe_url")
    try:
        target = urlsplit(value)
        if (
            target.scheme not in {"http", "https"}
            or not target.hostname
            or target.username is not None
            or target.password is not None
            or target.port == 0
            or any(re.sub(r"[^a-z]", "", key.lower()) in AUTH_KEYS for key, _ in parse_qsl(target.query))
        ):
            raise LinkError("unsafe_url")
        host = target.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise LinkError("nonpublic_address")
        try:
            if not public_address(host):
                raise LinkError("nonpublic_address")
        except ValueError as error:
            if isinstance(error, LinkError):
                raise
        return urlunsplit((target.scheme, target.netloc, target.path or "/", target.query, ""))
    except (UnicodeError, ValueError) as error:
        if isinstance(error, LinkError):
            raise
        raise LinkError("unsafe_url") from None


def public_addresses(host, port):
    results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = []
    for family, kind, protocol, _, address in results:
        if family not in {socket.AF_INET, socket.AF_INET6} or not public_address(address[0]):
            raise LinkError("nonpublic_address")
        row = (family, kind, protocol, address)
        if row not in addresses:
            addresses.append(row)
    if not addresses or len(addresses) > 16:
        raise LinkError("invalid_dns_response")
    return sorted(addresses, key=lambda row: row[0] != socket.AF_INET)


def pinned_connect(addresses, timeout):
    # Connect to the already-vetted sockaddr; never resolve the host a second
    # time. HTTPSConnection still verifies the original hostname and TLS SNI.
    for family, kind, protocol, address in addresses:
        connection = socket.socket(family, kind, protocol)
        try:
            connection.settimeout(timeout)
            connection.connect(address)
            return connection
        except OSError:
            connection.close()
    raise LinkError("connection_failed")


def request_once(url):
    target = urlsplit(checked_url(url))
    port = target.port or (443 if target.scheme == "https" else 80)
    addresses = public_addresses(target.hostname, port)
    cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = cls(target.hostname, port, timeout=5)
    connection._create_connection = lambda *args: pinned_connect(addresses, 5)
    try:
        path = urlunsplit(("", "", target.path or "/", target.query, ""))
        connection.request(
            "GET", path, headers={"User-Agent": "UBI-public-documentation-check/1.0", "Accept": "*/*"}
        )
        response = connection.getresponse()
        # Close immediately after bounded stdlib header parsing. Never ingest
        # arbitrary document bodies, send auth or replay Set-Cookie headers.
        return response.status, response.getheader("Location")
    finally:
        connection.close()


def check_url(url, *, request=request_once):
    chain = []
    try:
        current = checked_url(url)
        seen = set()
        for _ in range(MAX_REDIRECTS + 1):
            if current in seen:
                raise LinkError("redirect_cycle")
            seen.add(current)
            status, location = request(current)
            chain.append({"url": display_url(current), "http_status": status})
            if status in {301, 302, 303, 307, 308}:
                if not location:
                    raise LinkError("missing_redirect_location")
                candidate = checked_url(urljoin(current, location))
                if current.startswith("https:") and candidate.startswith("http:"):
                    raise LinkError("https_downgrade")
                current = candidate
                continue
            return {"status": "reachable" if 200 <= status < 300 else "http_failure", "chain": chain}
        raise LinkError("redirect_limit")
    except (OSError, ValueError, http.client.HTTPException):
        error = sys.exception()
        status = (
            str(error)
            if isinstance(error, LinkError)
            else "tls_validation_failed"
            if isinstance(error, ssl.SSLCertVerificationError)
            else "dns_failure"
            if isinstance(error, socket.gaierror)
            else "request_timeout"
            if isinstance(error, TimeoutError)
            else "network_failure"
        )
        return {"status": status, "chain": chain}


def retryable(result):
    return result["status"] in {"dns_failure", "request_timeout", "network_failure", "connection_failed"} or (
        result["status"] == "http_failure" and result["chain"][-1]["http_status"] in {429, 502, 503, 504}
    )


def attempt_rows(text):
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    rows = [json.loads(line) for line in (text or "").splitlines()]
    if not 1 <= len(rows) <= MAX_ATTEMPTS or any(
        not isinstance(row, dict)
        or set(row) != {"status", "chain"}
        or not isinstance(row["status"], str)
        or not isinstance(row["chain"], list)
        for row in rows
    ):
        raise ValueError("Invalid worker observations")
    for row in rows:
        chain = row["chain"]
        if len(chain) > MAX_REDIRECTS + 1:
            raise ValueError("Invalid worker observations")
        for hop in chain:
            if (
                not isinstance(hop, dict)
                or set(hop) != {"url", "http_status"}
                or type(hop["http_status"]) is not int
                or not 100 <= hop["http_status"] <= 599
                or checked_url(hop["url"]) != hop["url"]
                or urlsplit(hop["url"]).query
            ):
                raise ValueError("Invalid worker observations")
        if row["status"] == "reachable" and (not chain or not 200 <= chain[-1]["http_status"] < 300):
            raise ValueError("Invalid worker observations")
    return rows


def display_url(value):
    target = urlsplit(value)
    return urlunsplit((target.scheme, target.netloc, target.path, "", ""))


def inventory(root):
    root = root.resolve()
    parser = runpy.run_path(str(ROOT / "scripts/check-governance.py"))
    links, inputs, errors = {}, {}, []
    for path in sorted(root.rglob("*.md")):
        if any(part in parser["SKIP"] for part in path.relative_to(root).parts):
            continue
        name = path.relative_to(root).as_posix()
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or path.stat().st_size > MAX_DOCUMENT_BYTES
        ):
            errors.append({"document": name, "status": "unsafe_document"})
            continue
        raw = path.read_bytes()
        inputs[name] = hashlib.sha256(raw).hexdigest()
        for ordinal, value in enumerate(parser["markdown"](raw.decode("utf-8"))[0]):
            target = urlsplit(value)
            if target.scheme not in {"http", "https"}:
                continue
            ref = {
                "document": name,
                "link_ordinal": ordinal,
                "remote_fragment_present": bool(target.fragment),
            }
            try:
                url = checked_url(value)
                links.setdefault(url, []).append(ref)
            except LinkError as error:
                errors.append({**ref, "status": str(error)})
    if len(links) > MAX_LINKS:
        raise LinkError("documentation_link_budget_exceeded")
    return links, inputs, errors


def worker(url, timeout):
    try:
        process = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker"],
            input=json.dumps({"url": url}),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        rows = attempt_rows(process.stdout)
        if process.returncode:
            raise ValueError()
        return {**rows[-1], "attempts": rows}
    except subprocess.TimeoutExpired as error:
        try:
            rows = attempt_rows(error.stdout)
        except ValueError:
            rows = []
        return {"status": "timeout", "chain": rows[-1]["chain"] if rows else [], "attempts": rows}
    except (OSError, ValueError):
        return {"status": "worker_failure", "chain": [], "attempts": []}


def qualify(root, *, run=None):
    run = run or worker
    start = time.monotonic()
    script_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    parser_path = ROOT / "scripts/check-governance.py"
    parser_before = hashlib.sha256(parser_path.read_bytes()).hexdigest()
    links, inputs, errors = inventory(root)
    results = []
    for url, references in links.items():
        remaining = RUN_TIMEOUT - (time.monotonic() - start)
        result = (
            run(url, min(LINK_TIMEOUT, remaining))
            if remaining > 0
            else {"status": "run_deadline", "chain": []}
        )
        results.append(
            {
                "url": display_url(url),
                "request_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "references": references,
                **result,
            }
        )
    _, after, after_errors = inventory(root)
    changed = (
        inputs != after
        or errors != after_errors
        or script_before != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        or parser_before != hashlib.sha256(parser_path.read_bytes()).hexdigest()
    )
    return {
        "schema_version": 1,
        "qualified_at": datetime.now(UTC).isoformat(),
        "result": "passed"
        if not changed and not errors and results and all(x["status"] == "reachable" for x in results)
        else "failed",
        "scope": "Live unauthenticated HTTP reachability of parsed public Markdown/HTML links; no remote-anchor/page semantics, provider health or client/model qualification.",
        "inputs_sha256": inputs,
        "script_sha256": script_before,
        "parser_sha256": parser_before,
        "limits": {
            "links": MAX_LINKS,
            "redirects": MAX_REDIRECTS,
            "attempts": MAX_ATTEMPTS,
            "per_link_seconds": LINK_TIMEOUT,
            "run_seconds": RUN_TIMEOUT,
        },
        "errors": errors,
        "links": results,
        "inputs_changed": changed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        url = json.load(sys.stdin)["url"]
        for attempt in range(MAX_ATTEMPTS):
            result = check_url(url)
            print(json.dumps(result), flush=True)
            if not retryable(result) or attempt + 1 == MAX_ATTEMPTS:
                break
            time.sleep(0.5)
        return 0
    if args.output is None or args.output.exists():
        parser.error("Choose a fresh --output report path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = qualify(ROOT)
    except (OSError, ValueError):
        report = {
            "schema_version": 1,
            "result": "failed",
            "error": "Public link qualification could not establish complete evidence.",
        }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "result": report["result"],
                "links": len(report.get("links", [])),
                "failures": sum(x["status"] != "reachable" for x in report.get("links", [])),
            }
        )
    )
    return int(report["result"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
