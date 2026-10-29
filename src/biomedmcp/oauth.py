"""CLI OAuth using the SDK's callback handling with BioMed presentation."""

import anyio
from fastmcp.client.auth import OAuth
from fastmcp.client.oauth_callback import OAuthCallbackResult, create_oauth_callback_server
from mcp.shared.auth import AuthorizationCodeResult

from .auth_branding import AuthBranding


class BioMedOAuth(OAuth):
    async def callback_handler(self) -> AuthorizationCodeResult:
        # The pinned SDK owns callback parsing, first-response handling, HTML
        # escaping, and later state/issuer/PKCE verification. Decorate its app.
        result, ready = OAuthCallbackResult(), anyio.Event()
        server = create_oauth_callback_server(
            port=self.redirect_port, host=self._callback_host, server_url=self.mcp_url,
            result_container=result, result_ready=ready,
        )
        server.config.app = AuthBranding(server.config.app)
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(server.serve)
            try:
                with anyio.fail_after(self._callback_timeout):
                    await ready.wait()
                    if result.error:
                        raise result.error
                    return AuthorizationCodeResult(code=result.code, state=result.state, iss=result.iss)
            finally:
                server.should_exit = True
                await anyio.sleep(0.1)
                tasks.cancel_scope.cancel()
