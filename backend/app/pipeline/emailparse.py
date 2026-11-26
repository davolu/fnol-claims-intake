"""Parse RFC 822 emails (.eml) into body text + attachments, and build .eml bytes from connector payloads."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

CLAIM_ATTACHMENT_TYPES = ("application/pdf", "image/tiff", "image/png", "image/jpeg")


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class ParsedEmail:
    message_id: str | None
    subject: str
    sender: str
    date: str | None
    body: str
    attachments: list[Attachment] = field(default_factory=list)


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def parse_eml(data: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = ""
    if body_part is not None:
        content = body_part.get_content()
        body = html_to_text(content) if body_part.get_content_type() == "text/html" else content
    atts: list[Attachment] = []
    for part in msg.iter_attachments():
        ct = part.get_content_type()
        fn = part.get_filename() or "attachment"
        if ct == "application/octet-stream":
            low = fn.lower()
            ct = "application/pdf" if low.endswith(".pdf") else "image/tiff" if low.endswith((".tif", ".tiff")) else ct
        if ct in CLAIM_ATTACHMENT_TYPES:
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                atts.append(Attachment(filename=fn, content_type=ct, data=payload))
    return ParsedEmail(
        message_id=(msg.get("Message-ID") or "").strip() or None,
        subject=str(msg.get("Subject") or ""),
        sender=str(msg.get("From") or ""),
        date=str(msg.get("Date") or "") or None,
        body=body.strip(),
        attachments=atts,
    )


def build_eml(
    *, message_id: str, subject: str, sender: str, date: str | None, body: str, attachments: list[Attachment]
) -> bytes:
    m = EmailMessage()
    m["Message-ID"] = message_id
    m["Subject"] = subject
    m["From"] = sender
    if date:
        m["Date"] = date
    m.set_content(body or "")
    for a in attachments:
        maintype, subtype = a.content_type.split("/", 1)
        m.add_attachment(a.data, maintype=maintype, subtype=subtype, filename=a.filename)
    return bytes(m)
