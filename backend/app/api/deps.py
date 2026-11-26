from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException

from ..config import get_settings

ROLES = ("adjuster", "supervisor", "auditor")


@dataclass
class User:
    name: str
    role: str

    @property
    def can_see_pii(self) -> bool:
        return self.role in ("adjuster", "supervisor")

    @property
    def can_edit(self) -> bool:
        return self.role in ("adjuster", "supervisor")

    @property
    def can_admin(self) -> bool:
        return self.role == "supervisor"

    @property
    def actor(self) -> str:
        return f"user:{self.name}({self.role})"


def current_user(
    authorization: str | None = Header(default=None),
    x_user_name: str | None = Header(default=None),
    x_user_role: str | None = Header(default=None),
) -> User:
    token = get_settings().app_api_token
    if token:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given, token):
            raise HTTPException(401, "Missing or invalid API token")
    role = (x_user_role or "adjuster").lower()
    if role not in ROLES:
        raise HTTPException(400, f"Unknown role {role}")
    return User(name=(x_user_name or "demo.adjuster")[:60], role=role)


def require_edit(user: User) -> None:
    if not user.can_edit:
        raise HTTPException(403, "Your role is read-only")


def require_admin(user: User) -> None:
    if not user.can_admin:
        raise HTTPException(403, "Only supervisors can change settings and integrations")
