"""Credential encryption (Fernet) and PII masking."""

from __future__ import annotations

import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

PII_FIELDS = {"insured_name", "insured_phone", "insured_email", "reporter_name", "other_parties", "policy_number"}


class SecretsKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().secrets_key
    if not key:
        raise SecretsKeyMissing(
            "FNOL_SECRETS_KEY is not set. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:  # key rotated or corrupted
        raise SecretsKeyMissing("Stored credential cannot be decrypted with the current FNOL_SECRETS_KEY") from e


# ---------- masking ----------
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?(\d{4})(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-(\d{4})\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){12,15}(\d{4})\b")


def mask_name(name: str | None) -> str | None:
    if not name:
        return name
    return " ".join(p[0] + "***" if p else p for p in str(name).split())


def mask_policy(p: str | None) -> str | None:
    if not p:
        return p
    s = str(p)
    return "*" * max(0, len(s) - 4) + s[-4:]


def mask_text(text: str | None) -> str | None:
    """Mask emails, phones, SSNs and card numbers inside free text."""
    if not text:
        return text
    t = SSN_RE.sub(r"***-**-\1", text)
    t = CARD_RE.sub(r"****-****-****-\1", t)
    t = EMAIL_RE.sub(r"\1***@\2", t)
    t = PHONE_RE.sub(r"***-***-\1", t)
    return t


def mask_value(field: str, value: Any) -> Any:
    if value is None:
        return None
    if field in ("insured_name", "reporter_name"):
        return mask_name(value)
    if field == "policy_number":
        return mask_policy(value)
    if field in ("insured_phone", "insured_email"):
        return mask_text(str(value))
    if field == "other_parties" and isinstance(value, list):
        return [
            {**p, "name": mask_name(p.get("name")), "phone": mask_text(p.get("phone"))} if isinstance(p, dict) else p
            for p in value
        ]
    if isinstance(value, str):
        return mask_text(value)
    return value


def mask_fields(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, f in fields.items():
        if isinstance(f, dict):
            out[k] = {**f, "value": mask_value(k, f.get("value")), "source": mask_text(f.get("source"))}
            if k in ("insured_name", "reporter_name", "other_parties", "policy_number") and f.get("source"):
                out[k]["source"] = "[masked]"
        else:
            out[k] = f
    return out


def mask_obj(obj: Any) -> Any:
    """Deep-mask a JSON-ish structure for the audit log."""
    if isinstance(obj, dict):
        res: dict[str, Any] = {}
        for k, v in obj.items():
            if k in PII_FIELDS and isinstance(v, dict) and "value" in v:
                res[k] = {
                    **mask_obj({kk: vv for kk, vv in v.items() if kk not in ("value", "source")}),
                    "value": mask_value(k, v.get("value")),
                    "source": "[masked]" if v.get("source") else None,
                }
            elif k in PII_FIELDS:
                res[k] = mask_value(k, v)
            elif k in (
                "api_key",
                "client_secret",
                "password",
                "secret",
                "access_token",
                "refresh_token",
                "authorization",
                "Authorization",
            ):
                res[k] = "[redacted]"
            else:
                res[k] = mask_obj(v)
        return res
    if isinstance(obj, list):
        return [mask_obj(v) for v in obj]
    if isinstance(obj, str):
        return mask_text(obj)
    return obj
