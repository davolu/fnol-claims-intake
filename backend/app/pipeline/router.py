"""Router: decide which intake path a document takes. Deterministic first (file signature, text layer);
the extraction agent later confirms the document is actually an FNOL (document_kind)."""

from __future__ import annotations

from dataclasses import dataclass, field

from . import ocr
from .emailparse import parse_eml

ROUTES = ("text_pdf", "scanned_form", "free_text_email", "email_with_attachments")


@dataclass
class RoutedSource:
    route: str
    kind: str
    source_text: str
    ocr_engine: str
    ocr_confidence: float | None
    page_count: int
    sections: list[dict] = field(default_factory=list)  # metadata per section for the audit trail
    email_meta: dict | None = None


def route_and_read(data: bytes, filename: str) -> RoutedSource:
    kind = ocr.sniff_kind(data, filename)
    if kind == "eml":
        em = parse_eml(data)
        parts = [f"EMAIL\nFrom: {em.sender}\nDate: {em.date or ''}\nSubject: {em.subject}\n\n{em.body}"]
        sections = [{"section": "email_body", "chars": len(em.body)}]
        confs: list[float] = []
        pages = 0
        for a in em.attachments:
            sub = ocr.sniff_kind(a.data, a.filename)
            res = ocr.extract_text(a.data, sub)
            pages += len(res.pages)
            if res.mean_confidence is not None:
                confs.append(res.mean_confidence)
            parts.append(f"ATTACHMENT {a.filename}\n{res.text}")
            sections.append({"section": f"attachment:{a.filename}", **ocr.describe(res)})
        route = "email_with_attachments" if em.attachments else "free_text_email"
        return RoutedSource(
            route=route,
            kind="eml",
            source_text="\n\n".join(parts),
            ocr_engine="email" + ("+ocr" if em.attachments else ""),
            ocr_confidence=round(min(confs), 3) if confs else None,
            page_count=pages,
            sections=sections,
            email_meta={
                "subject": em.subject,
                "from": em.sender,
                "message_id": em.message_id,
                "attachments": [a.filename for a in em.attachments],
            },
        )
    if kind == "txt":
        res = ocr.extract_text(data, kind)
        return RoutedSource("free_text_email", kind, res.text, res.engine, None, 1, [ocr.describe(res)])
    if kind in ("pdf", "tiff", "png", "jpeg"):
        res = ocr.extract_text(data, kind)
        route = "scanned_form" if res.scanned else "text_pdf"
        return RoutedSource(route, kind, res.text, res.engine, res.mean_confidence, len(res.pages), [ocr.describe(res)])
    raise ValueError(f"Unsupported file '{filename}'. Upload PDF, TIFF, PNG, JPEG, EML or TXT.")
