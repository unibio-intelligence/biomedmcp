"""One bounded HTTP boundary for native biomedical providers."""

import os
from urllib.parse import quote, urlsplit

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .. import transport as httpx
from ..errors import ResearchError


def segment(value):
    return quote(str(value), safe="")


class ProviderHTTP:
    async def request(
        self,
        method,
        url,
        *,
        params=None,
        body=None,
        headers=None,
        text=False,
        binary=False,
        response_meta=False,
    ):
        try:
            # Local single-user BYOK only. These copies stay at the wire boundary,
            # outside scientific requests, cache keys and reproduction receipts.
            # Do not use process environment to switch users on a hosted server.
            parsed = urlsplit(url)
            if parsed.scheme == "https" and not parsed.username and not parsed.password:
                setting = (
                    "NCBI_API_KEY"
                    if parsed.netloc == "eutils.ncbi.nlm.nih.gov"
                    and parsed.path.startswith("/entrez/eutils/")
                    else "OPENFDA_API_KEY"
                    if parsed.netloc == "api.fda.gov"
                    else None
                )
                if setting and os.getenv(setting):
                    params = {**(params or {}), "api_key": os.environ[setting]}
            if (
                parsed.scheme == "https"
                and parsed.netloc == "api.openalex.org"
                and os.getenv("OPENALEX_API_KEY")
            ):
                headers = {**(headers or {}), "Authorization": "Bearer " + os.environ["OPENALEX_API_KEY"]}
            async with httpx.AsyncClient() as client:
                response = await client.request(method, url, params=params, json=body, headers=headers)
                response.raise_for_status()
                if response_meta and response.status_code == 204:
                    if response.content:
                        raise ResearchError(
                            "invalid_source_response", "Provider returned a nonempty no-content response."
                        )
                    return {
                        "status": 204,
                        "headers": {"interpro-version": response.headers.get("InterPro-Version")},
                        "body": None,
                    }
                if binary:
                    return response.content
                if text:
                    if (
                        parsed.netloc == "thegencc.org"
                        and parsed.path == "/download/action/submissions-export-csv"
                    ):
                        if response.status_code != 200:
                            raise ResearchError(
                                "invalid_source_response", "GenCC export response is not a complete download."
                            )
                        try:
                            return response.content.decode("utf-8")
                        except UnicodeError:
                            raise ResearchError(
                                "invalid_source_response", "GenCC export is not valid UTF-8."
                            ) from None
                    return response.text
                value = response.json()
                if isinstance(value, dict) and (value.get("error") or value.get("errors")):
                    raise ResearchError(
                        "upstream_error", "Provider returned an application error.", retryable=True
                    )
                return (
                    {
                        "status": response.status_code,
                        "headers": {"interpro-version": response.headers.get("InterPro-Version")},
                        "body": value,
                    }
                    if response_meta
                    else value
                )
        except ResearchError:
            raise
        except httpx.RejectedConnection:
            raise ResearchError(
                "source_connection_rejected",
                "Provider DNS/TLS policy could not be verified; choose another qualified source.",
            ) from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            code = {
                401: "source_authentication_failed",
                403: "source_access_denied",
                404: "source_not_found",
                429: "source_rate_limited",
            }.get(status, "source_unavailable")
            raise ResearchError(
                code,
                "The provider could not complete the request; no absence can be inferred.",
                retryable=status == 429 or status >= 500,
            ) from None
        except ValueError:
            raise ResearchError(
                "invalid_source_response", "Provider JSON could not be parsed safely."
            ) from None
        except httpx.HTTPError:
            raise ResearchError(
                "source_unavailable",
                "Provider request failed or returned an invalid response.",
                retryable=True,
            ) from None

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def post(self, url, body, **kwargs):
        return await self.request("POST", url, body=body, **kwargs)

    async def xml(self, url, **kwargs):
        value = await self.get(url, text=True, **kwargs)
        if len(value.encode()) > 4_000_000:
            raise ResearchError("response_too_large", "XML exceeded its 4 MB budget.")
        try:
            root = ElementTree.fromstring(value)
        except (ElementTree.ParseError, ValueError, DefusedXmlException) as exc:
            raise ResearchError(
                "invalid_source_response", "Provider XML could not be parsed safely."
            ) from exc
        if root.find(".//ERROR") is not None:
            raise ResearchError("upstream_error", "Provider XML reports an error.")
        return root
