"""REST client for dkncloudna.com.

Mirrors ``api.service.js`` + ``user.service.js`` + ``installation.service.js``:
JWT bearer auth with a refresh-token retry on 401.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import aiohttp

from .const import (
    BASE_URL,
    DEFAULT_TIMEOUT,
    ROUTE_INSTALLATIONS,
    ROUTE_IS_LOGGED_IN,
    ROUTE_LOGIN,
    ROUTE_LOGOUT,
    ROUTE_REFRESH,
)
from .exceptions import DknApiError, DknAuthError, DknConnectionError
from .models import Installation, parse_installations

_LOGGER = logging.getLogger(__name__)

#: The refresh token is passed as a path segment (auth/refreshToken/<token>/dknUsa).
#: Mask it before any route string is logged or put in an exception message.
_REFRESH_TOKEN_IN_ROUTE = re.compile(r"(refreshToken/)[^/]+")
_REDACTED = "<redacted>"


def _safe_route(route: str, secret: Optional[str] = None) -> str:
    """Return ``route`` with the refresh token masked, for logs/exceptions."""
    masked = _REFRESH_TOKEN_IN_ROUTE.sub(rf"\g<1>{_REDACTED}", route)
    if secret:
        masked = masked.replace(secret, _REDACTED)
    return masked


class DknCloudNaClient:
    """Async REST client. Holds the access + refresh tokens for a session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        base_url: str = BASE_URL,
        token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self._session = session
        self._base = base_url.rstrip("/") + "/"
        self.token = token
        self.refresh_token_value = refresh_token
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # -- low-level ----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(self, method: str, route: str, *, json: Any = None,
                       _retry: bool = True) -> Any:
        url = self._base + route.lstrip("/")
        safe_route = _safe_route(route, self.refresh_token_value)
        try:
            async with self._session.request(
                method, url, json=json, headers=self._headers(), timeout=self._timeout
            ) as resp:
                body: Any = None
                if resp.content_type and "json" in resp.content_type:
                    body = await resp.json(content_type=None)
                else:
                    text = await resp.text()
                    body = text or None

                if resp.status == 401 and _retry and self.refresh_token_value:
                    # Session expired -> refresh and replay once (api.service.js).
                    _LOGGER.debug("401 on %s; refreshing token", safe_route)
                    await self.refresh()
                    return await self._request(method, route, json=json, _retry=False)

                if resp.status >= 400:
                    error_id = body.get("_id") if isinstance(body, dict) else None
                    raise DknApiError(
                        f"{method} {safe_route} -> HTTP {resp.status} ({error_id or resp.reason})",
                        status=resp.status,
                        error_id=error_id,
                    )
                return body
        except aiohttp.ClientError as err:
            raise DknConnectionError(f"{method} {safe_route} failed: {err}") from err

    # -- auth ---------------------------------------------------------------
    async def login(self, email: str, password: str) -> dict:
        """POST auth/login/dknUsa -> stores token + refresh token."""
        data = await self._request(
            "POST", ROUTE_LOGIN, json={"email": email, "password": password}, _retry=False
        )
        if not isinstance(data, dict) or not data.get("token"):
            raise DknAuthError("Login response missing token")
        self.token = str(data["token"])
        self.refresh_token_value = str(data.get("refreshToken") or "") or None
        return data

    async def refresh(self) -> str:
        """GET auth/refreshToken/{refreshToken}/dknUsa -> new access token."""
        if not self.refresh_token_value:
            raise DknAuthError("No refresh token available")
        route = ROUTE_REFRESH.format(refresh_token=self.refresh_token_value)
        data = await self._request("GET", route, _retry=False)
        if not isinstance(data, dict) or not data.get("token"):
            raise DknAuthError("Refresh response missing token")
        self.token = str(data["token"])
        # The app saves response.data.newRefreshToken here.
        new_refresh = data.get("newRefreshToken") or data.get("refreshToken")
        if new_refresh:
            self.refresh_token_value = str(new_refresh)
        return self.token

    async def is_logged_in(self) -> dict:
        """GET users/isLoggedin/dknUsa -> current user (refreshes tokens)."""
        data = await self._request("GET", ROUTE_IS_LOGGED_IN)
        if isinstance(data, dict) and data.get("token"):
            self.token = str(data["token"])
            if data.get("refreshToken"):
                self.refresh_token_value = str(data["refreshToken"])
        return data

    async def logout(self) -> None:
        await self._request("GET", ROUTE_LOGOUT)
        self.token = None
        self.refresh_token_value = None

    # -- data ---------------------------------------------------------------
    async def get_installations(self, sender=None) -> list[Installation]:
        """GET installations/dknUsa -> parsed Installation objects."""
        data = await self._request("GET", ROUTE_INSTALLATIONS)
        return parse_installations(data, sender=sender)
