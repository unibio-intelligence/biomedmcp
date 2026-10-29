"""BioMed MCP presentation for SDK-owned consent and CLI callback pages."""

import base64
import re
from importlib.resources import files

from fastmcp.utilities.ui import FASTMCP_LOGO_URL

DISPLAY_NAME = "BioMed MCP"
LOGO_SVG = files("biomedmcp").joinpath("assets/logo.svg").read_bytes()
LOGO_URL = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG).decode("ascii")
_LOGO = re.compile(
    rb'<img src="(?:' + re.escape(FASTMCP_LOGO_URL.encode()) + b"|" + re.escape(LOGO_URL.encode())
    + rb')" alt="[^"]*" class="logo" />'
)
_WORDMARK = (
    f'<div class="biomed-brand"><img src="{LOGO_URL}" alt="" />'
    f'<span>{DISPLAY_NAME}</span></div>'
).encode()
_THEME = b"""
<style id="biomed-auth-theme">
body { background: #f7f9f8; color: #253430; }
.container { border-color: #dce3e0; box-shadow: 0 8px 32px #2534300a; }
.biomed-brand { display: flex; align-items: center; justify-content: center;
  gap: 12px; margin-bottom: 28px; color: #253430; font-size: 24px; font-weight: 600; }
.biomed-brand img { width: 42px; height: 48px; object-fit: contain; }
.info-box, .redirect-section, .cimd-badge, .warning-box {
  background: #f7f9f8; border-color: #dce3e0; color: #42534c; }
.info-box strong, .info-box .server-name-link, .warning-box strong,
.warning-box a, .cimd-check { color: #237b74; }
.btn-approve, .btn-primary { background: #237b74; color: #fff; }
.btn-deny, .btn-secondary { background: #edf1ef; color: #42534c; border: 1px solid #dce3e0; }
.status-icon.success { background: #eaf3f0; color: #237b74; }
.info-box.error, .info-box-mono.error { background: #fef2f2; border-color: #fecaca; color: #991b1b; }
button:focus-visible, summary:focus-visible, a:focus-visible { outline: 2px solid #237b74; outline-offset: 3px; }
</style>
"""


def brand_auth_html(body: bytes) -> bytes:
    """Change known SDK presentation only; leave authorization content intact."""
    if not _LOGO.search(body):
        return body
    body = _LOGO.sub(lambda _: _WORDMARK, body, count=1)
    body = re.sub(rb"<title>[^<]*</title>", b"<title>BioMed MCP</title>", body, count=1)
    return body.replace(b"</head>", _THEME + b"</head>", 1)


class AuthBranding:
    """Bounded HTML decoration preserving status, cookies and security headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        start, buffered, size = None, [], 0

        async def branded_send(message):
            nonlocal start, size
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if headers.get(b"content-type", b"").startswith(b"text/html"):
                    start = message
                    return
            elif message["type"] == "http.response.body" and start is not None:
                buffered.append(message)
                size += len(message.get("body", b""))
                if size > 256 * 1024:
                    await send(start)
                    start = None
                    for chunk in buffered:
                        await send(chunk)
                    buffered.clear()
                    return
                if message.get("more_body", False):
                    return
                body = brand_auth_html(b"".join(chunk.get("body", b"") for chunk in buffered))
                headers = [(key, value) for key, value in start.get("headers", []) if key != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                start = None
                buffered.clear()
                return
            await send(message)

        await self.app(scope, receive, branded_send)
