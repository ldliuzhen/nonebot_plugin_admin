from __future__ import annotations

import asyncio
import json as json_module
import urllib.error
import urllib.request
from typing import Any, Optional


class Response:
    def __init__(self, data: bytes, status_code: int = 200, headers: Optional[dict[str, str]] = None) -> None:
        self.content = data
        self.status_code = status_code
        self.headers = headers or {}

    @property
    def text(self) -> str:
        encoding = "utf-8"
        content_type = self.headers.get("Content-Type") or self.headers.get("content-type") or ""
        if "charset=" in content_type:
            encoding = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
        return self.content.decode(encoding, errors="replace")

    def json(self) -> Any:
        return json_module.loads(self.text)


class AsyncClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.timeout = kwargs.get("timeout", 30)

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> Response:
        return await asyncio.to_thread(self._request, "GET", url, None, kwargs)

    async def post(self, url: str, json: Any = None, data: Any = None, **kwargs: Any) -> Response:
        body = data
        headers = dict(kwargs.pop("headers", {}) or {})
        if json is not None:
            body = json_module.dumps(json).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        return await asyncio.to_thread(self._request, "POST", url, body, kwargs, headers)

    def _request(
        self,
        method: str,
        url: str,
        body: Any = None,
        kwargs: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Response:
        timeout = (kwargs or {}).get("timeout", self.timeout)
        request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return Response(resp.read(), getattr(resp, "status", 200), dict(resp.headers.items()))
        except urllib.error.HTTPError as exc:
            return Response(exc.read(), exc.code, dict(exc.headers.items()))
