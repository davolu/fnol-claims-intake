"""Email intake connectors (all READ-ONLY): Composio Gmail, direct Gmail (OAuth refresh token), Microsoft 365
(Graph, app-only). Each returns ParsedEmail objects; the app never sends, deletes, moves or labels mail."""

from __future__ import annotations

import base64
import os
from abc import ABC, abstractmethod
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings
from ..models import EmailConnector
from ..pipeline.emailparse import CLAIM_ATTACHMENT_TYPES, Attachment, ParsedEmail
from ..security import decrypt_secret

DEFAULT_QUERY = 'subject:(FNOL OR "first notice of loss" OR "claim report") newer_than:30d'

# Hard allow-list: only read tools can ever be executed through Composio.
COMPOSIO_READ_TOOLS = ("GMAIL_FETCH_EMAILS", "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID", "GMAIL_GET_ATTACHMENT")


class ConnectorError(RuntimeError):
    pass


class EmailSource(ABC):
    def __init__(self, conn: EmailConnector) -> None:
        self.conn = conn
        self.cfg = conn.config or {}
        self.secret = decrypt_secret(conn.secret_encrypted) if conn.secret_encrypted else ""

    @abstractmethod
    def fetch(self, max_results: int = 10) -> list[ParsedEmail]: ...

    def test(self) -> tuple[bool, str]:
        try:
            msgs = self.fetch(max_results=3)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"[:400]
        return True, f"Connected. {len(msgs)} message(s) match the intake filter right now."


class ComposioGmail(EmailSource):
    def _client(self) -> Any:
        from composio import Composio

        key = self.secret or get_settings().composio_api_key
        if not key:
            raise ConnectorError("COMPOSIO_API_KEY is not set")
        return Composio(api_key=key)

    def _exec(self, c: Any, slug: str, args: dict[str, Any]) -> dict[str, Any]:
        if slug not in COMPOSIO_READ_TOOLS:
            raise ConnectorError(f"Blocked non-read Gmail tool {slug}")
        r = c.tools.execute(
            slug, user_id=self.cfg.get("user_id") or "default", arguments=args, dangerously_skip_version_check=True
        )
        if not r.get("successful", False):
            raise ConnectorError(f"{slug} failed: {r.get('error')}")
        return r.get("data") or {}

    def fetch(self, max_results: int = 10) -> list[ParsedEmail]:
        c = self._client()
        data = self._exec(
            c,
            "GMAIL_FETCH_EMAILS",
            {
                "user_id": "me",
                "query": self.cfg.get("query") or DEFAULT_QUERY,
                "max_results": max_results,
                "include_payload": True,
                "verbose": True,
                "include_spam_trash": False,
                "ids_only": False,
            },
        )
        out = []
        for m in data.get("messages", []):
            atts: list[Attachment] = []
            for a in m.get("attachmentList") or []:
                mime = a.get("mimeType") or ""
                fn = a.get("filename") or "attachment"
                if mime not in CLAIM_ATTACHMENT_TYPES and not fn.lower().endswith((".pdf", ".tif", ".tiff")):
                    continue
                blob = self._attachment(c, m["messageId"], a.get("attachmentId"), fn)
                if blob:
                    atts.append(Attachment(fn, mime or "application/pdf", blob))
            out.append(
                ParsedEmail(
                    message_id=f"gmail:{m.get('messageId')}",
                    subject=m.get("subject") or "",
                    sender=m.get("sender") or "",
                    date=m.get("messageTimestamp"),
                    body=m.get("messageText") or "",
                    attachments=atts,
                )
            )
        return out

    def _attachment(self, c: Any, message_id: str, attachment_id: str | None, filename: str) -> bytes | None:
        if not attachment_id:
            return None
        d = self._exec(
            c,
            "GMAIL_GET_ATTACHMENT",
            {"user_id": "me", "message_id": message_id, "attachment_id": attachment_id, "file_name": filename},
        )
        f = d.get("file") or d.get("attachment") or d
        if isinstance(f, str) and os.path.exists(f):
            return Path(f).read_bytes()
        if isinstance(f, dict):
            for k in ("uri", "file_path", "path", "local_path"):
                if isinstance(f.get(k), str) and os.path.exists(f[k]):
                    return Path(f[k]).read_bytes()
            url = f.get("s3url") or f.get("url")
            if url:
                return httpx.get(url, timeout=60).content
            if f.get("data"):
                return base64.urlsafe_b64decode(f["data"] + "==")
        return None


class GmailOAuth(EmailSource):
    """Direct Gmail API with the gmail.readonly scope. Secret = refresh token; config has client_id and
    client_secret_ref (client secret stored in the same encrypted blob as 'client_secret|refresh_token')."""

    def _token(self) -> str:
        client_secret, _, refresh = self.secret.partition("|")
        r = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.cfg.get("client_id", ""),
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        if r.status_code != 200:
            raise ConnectorError(f"Google token refresh failed ({r.status_code})")
        return r.json()["access_token"]

    def fetch(self, max_results: int = 10) -> list[ParsedEmail]:
        from ..pipeline.emailparse import parse_eml

        h = {"Authorization": f"Bearer {self._token()}"}
        base = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        with httpx.Client(timeout=30, headers=h) as c:
            r = c.get(base, params={"q": self.cfg.get("query") or DEFAULT_QUERY, "maxResults": max_results})
            r.raise_for_status()
            out = []
            for m in r.json().get("messages", []):
                raw = c.get(f"{base}/{m['id']}", params={"format": "raw"}).json()["raw"]
                pe = parse_eml(base64.urlsafe_b64decode(raw + "=="))
                pe.message_id = f"gmail:{m['id']}"
                out.append(pe)
        return out


class Microsoft365(EmailSource):
    """Microsoft Graph, app-only (client credentials) with Mail.Read on one mailbox.
    Secret = client secret; config has tenant_id, client_id, mailbox, subject_filter."""

    def _token(self) -> str:
        t = self.cfg.get("tenant_id", "")
        r = httpx.post(
            f"https://login.microsoftonline.com/{t}/oauth2/v2.0/token",
            data={
                "client_id": self.cfg.get("client_id", ""),
                "client_secret": self.secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
            timeout=20,
        )
        if r.status_code != 200:
            raise ConnectorError(f"Microsoft token request failed ({r.status_code})")
        return r.json()["access_token"]

    def fetch(self, max_results: int = 10) -> list[ParsedEmail]:
        mailbox = self.cfg.get("mailbox", "")
        word = self.cfg.get("subject_filter") or "FNOL"
        h = {"Authorization": f"Bearer {self._token()}"}
        base = f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages"
        with httpx.Client(timeout=30, headers=h) as c:
            r = c.get(
                base,
                params={
                    "$search": f'"subject:{word}"',
                    "$top": max_results,
                    "$select": "id,subject,from,receivedDateTime,body,hasAttachments",
                },
            )
            r.raise_for_status()
            out = []
            for m in r.json().get("value", []):
                atts: list[Attachment] = []
                if m.get("hasAttachments"):
                    ar = c.get(f"{base}/{m['id']}/attachments").json()
                    for a in ar.get("value", []):
                        if a.get("contentType") in CLAIM_ATTACHMENT_TYPES and a.get("contentBytes"):
                            atts.append(Attachment(a["name"], a["contentType"], base64.b64decode(a["contentBytes"])))
                body = m.get("body", {})
                text = body.get("content", "")
                if body.get("contentType") == "html":
                    from ..pipeline.emailparse import html_to_text

                    text = html_to_text(text)
                out.append(
                    ParsedEmail(
                        message_id=f"m365:{m['id']}",
                        subject=m.get("subject") or "",
                        sender=(m.get("from") or {}).get("emailAddress", {}).get("address", ""),
                        date=m.get("receivedDateTime"),
                        body=text,
                        attachments=atts,
                    )
                )
        return out


def get_source(conn: EmailConnector) -> EmailSource:
    if conn.kind == "composio_gmail":
        return ComposioGmail(conn)
    if conn.kind == "gmail_oauth":
        return GmailOAuth(conn)
    if conn.kind == "m365":
        return Microsoft365(conn)
    raise ValueError(f"Unknown email connector {conn.kind}")


CATALOG = [
    {
        "kind": "composio_gmail",
        "label": "Gmail via Composio",
        "fields": ["user_id", "query"],
        "secret": "Composio API key (optional if COMPOSIO_API_KEY env is set)",
        "notes": "Quickest setup. Uses the Gmail account connected under this Composio user id. Read-only tools.",
    },
    {
        "kind": "gmail_oauth",
        "label": "Gmail (direct OAuth)",
        "fields": ["client_id", "query"],
        "secret": "client_secret|refresh_token (gmail.readonly scope)",
        "notes": "Your own Google Cloud OAuth client; no third party touches claim emails.",
    },
    {
        "kind": "m365",
        "label": "Microsoft 365 / Outlook (Graph)",
        "fields": ["tenant_id", "client_id", "mailbox", "subject_filter"],
        "secret": "Client secret",
        "notes": "Entra ID app registration with Mail.Read application permission, scoped to the claims mailbox.",
    },
]


def to_rfc2822(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        from datetime import datetime

        return format_datetime(datetime.fromisoformat(ts.replace("Z", "+00:00")))
    except ValueError:
        return ts
