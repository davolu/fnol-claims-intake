"""Claims-system adapter contract. Each system (Guidewire, Duck Creek, Majesco, webhook) implements this."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..models import Integration


@dataclass
class PushResult:
    external_id: str | None
    claim_number: str | None
    state: str  # submitted | draft | accepted
    calls: list[dict[str, Any]] = field(default_factory=list)


class PushError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True, calls: list | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.calls = calls or []


Checkpoint = Callable[[dict[str, Any]], None]


class ClaimsAdapter(ABC):
    kind: str = ""
    label: str = ""

    def __init__(self, integ: Integration, secret: str) -> None:
        self.integ = integ
        self.secret = secret
        self._token: tuple[str, float] | None = None
        self.calls: list[dict[str, Any]] = []

    # ---- auth ----
    def auth_headers(self, client: httpx.Client) -> dict[str, str]:
        mode = self.integ.auth_mode
        if mode == "basic":
            import base64

            raw = f"{self.integ.client_id or ''}:{self.secret}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        if mode == "oauth2":
            if self._token and self._token[1] > time.time() + 30:
                return {"Authorization": f"Bearer {self._token[0]}"}
            if not self.integ.token_url:
                raise PushError("OAuth token URL is not configured", retryable=False)
            data = {
                "grant_type": "client_credentials",
                "client_id": self.integ.client_id or "",
                "client_secret": self.secret,
            }
            if self.integ.scopes:
                data["scope"] = self.integ.scopes
            r = client.post(self.integ.token_url, data=data)
            self._log("POST", self.integ.token_url, r.status_code, None)
            if r.status_code >= 400:
                raise PushError(f"OAuth token request failed ({r.status_code})", retryable=r.status_code >= 500)
            tok = r.json()
            self._token = (tok["access_token"], time.time() + float(tok.get("expires_in", 3600)))
            return {"Authorization": f"Bearer {tok['access_token']}"}
        return {}

    def _log(self, method: str, url: str, status: int, body: Any, response: Any = None) -> None:
        self.calls.append({"method": method, "url": url, "status": status, "request": body, "response": response})

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]: ...

    @abstractmethod
    def build_payload(self, fields: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def push(
        self, fields: dict[str, Any], push_key: str, state: dict[str, Any], checkpoint: Checkpoint, reference: str
    ) -> PushResult: ...


def val(fields: dict[str, Any], k: str) -> Any:
    f = fields.get(k) or {}
    return f.get("value") if isinstance(f, dict) else None


def split_name(name: str | None) -> tuple[str, str]:
    parts = (name or "").strip().split()
    if not parts:
        return "", "Unknown"
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]
