"""Generate SAMPLE claim documents (fictional people) for demos, tests and evals.

  python samples/generate.py            -> samples/eval/files/*  + samples/eval/labels.json

Formats: typed PDF (text layer), scanned PDF (image only), scanned TIFF (bi-tonal, multi-page),
scanned PNG, plain email (.eml) and email with a scanned TIFF attachment."""

from __future__ import annotations

import io
import json
import random
import sys
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

import pdfplumber
from PIL import Image, ImageFilter
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).parent))
from cases import CARRIER, CASES  # noqa: E402

OUT = Path(__file__).parent / "eval" / "files"
W, H = letter


def form_pdf(fields: dict[str, str], ref: str, pages: int = 1) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    items = list(fields.items())
    split = len(items) if pages == 1 else (len(items) + 1) // 2
    chunks = [items[:split], items[split:]] if pages == 2 else [items]
    for pno, chunk in enumerate(chunks, start=1):
        c.saveState()
        c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.10))
        c.setFont("Helvetica-Bold", 70)
        c.translate(W / 2, H / 2)
        c.rotate(35)
        c.drawCentredString(0, 0, "SAMPLE")
        c.restoreState()
        c.setFillColor(HexColor("#0b3b66"))
        c.rect(0, H - 70, W, 70, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff"))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, H - 38, CARRIER)
        c.setFont("Helvetica", 11)
        c.drawString(40, H - 56, "FIRST NOTICE OF LOSS  -  Property & Casualty Loss Notice")
        c.setFont("Helvetica", 9)
        c.drawRightString(W - 40, H - 38, f"Form FNOL-01   Ref {ref}")
        c.drawRightString(W - 40, H - 56, f"Page {pno} of {len(chunks)}")
        c.setFillColor(HexColor("#b00020"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(40, H - 84, "SAMPLE DOCUMENT - FICTIONAL PEOPLE AND POLICIES - FOR SOFTWARE TESTING ONLY")
        y = H - 110
        c.setFillColor(HexColor("#000000"))
        for label, value in chunk:
            lines = simpleSplit(str(value), "Helvetica", 11, W - 250)
            box_h = 16 + 14 * len(lines)
            c.setStrokeColor(HexColor("#8a99a8"))
            c.rect(36, y - box_h + 10, W - 72, box_h, fill=0, stroke=1)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(44, y - 4, label.upper())
            c.setFont("Helvetica", 11)
            for i, ln in enumerate(lines):
                c.drawString(200, y - 4 - 14 * i, ln)
            y -= box_h + 6
        if pno == len(chunks):
            c.setFont("Helvetica", 9)
            c.drawString(40, 70, "I certify the information above is true to the best of my knowledge.")
            c.drawString(40, 50, "Signature: ______________________      Date: ____________")
        c.showPage()
    c.save()
    return buf.getvalue()


def scan_images(pdf: bytes, seed: int, dpi: int = 200, bitonal: bool = False) -> list[Image.Image]:
    rnd = random.Random(seed)
    imgs = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        for p in doc.pages:
            im = p.to_image(resolution=dpi).original.convert("L")
            im = im.rotate(rnd.uniform(-1.2, 1.2), expand=True, fillcolor=255, resample=Image.BICUBIC)
            im = im.filter(ImageFilter.GaussianBlur(radius=0.6))
            px = im.load()
            w, h = im.size
            for _ in range(w * h // 300):  # speckle noise
                x, y = rnd.randrange(w), rnd.randrange(h)
                px[x, y] = rnd.choice((0, 90, 255))
            if bitonal:
                im = im.point(lambda v: 255 if v > 150 else 0).convert("1")
            imgs.append(im)
    return imgs


def to_pdf(imgs: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    rgb = [i.convert("RGB") for i in imgs]
    rgb[0].save(buf, format="PDF", save_all=True, append_images=rgb[1:], resolution=200)
    return buf.getvalue()


def to_tiff(imgs: list[Image.Image]) -> bytes:
    buf = io.BytesIO()
    imgs[0].save(buf, format="TIFF", save_all=True, append_images=imgs[1:], compression="group4", dpi=(200, 200))
    return buf.getvalue()


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def eml(e: dict, idx: int, attachment: tuple[str, str, bytes] | None = None) -> bytes:
    m = EmailMessage()
    m["From"] = e["from"]
    m["To"] = "claims-intake@example.com"
    m["Subject"] = e["subject"]
    m["Date"] = format_datetime(datetime(2026, 11, 23, 9, idx, tzinfo=UTC))
    m["Message-ID"] = make_msgid(domain="sample.fnol.test")
    m.set_content(e["body"] + "\n\n-- \nSAMPLE EMAIL - fictional sender, generated for software testing.")
    if attachment:
        fn, ct, data = attachment
        mt, st = ct.split("/")
        m.add_attachment(data, maintype=mt, subtype=st, filename=fn)
    return bytes(m)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    labels = []
    for i, case in enumerate(CASES):
        fmt = case["format"]
        ref = f"S-{1000 + i}"
        if fmt == "form_pdf":
            name, data = f"{case['id']}.pdf", form_pdf(case["form"], ref)
        elif fmt == "form_scan_pdf":
            name, data = f"{case['id']}.pdf", to_pdf(scan_images(form_pdf(case["form"], ref), seed=i))
        elif fmt == "form_scan_tiff":
            pdf = form_pdf(case["form"], ref, pages=case.get("pages", 1))
            name, data = f"{case['id']}.tif", to_tiff(scan_images(pdf, seed=i, bitonal=True))
        elif fmt == "form_scan_png":
            name, data = f"{case['id']}.png", to_png(scan_images(form_pdf(case["form"], ref), seed=i)[0])
        elif fmt == "email":
            name, data = f"{case['id']}.eml", eml(case["email"], i)
        elif fmt == "email_attachment":
            tif = to_tiff(scan_images(form_pdf(case["form"], ref), seed=i, bitonal=True))
            name, data = f"{case['id']}.eml", eml(case["email"], i, ("fnol_form_scan.tif", "image/tiff", tif))
        else:
            raise ValueError(fmt)
        (OUT / name).write_bytes(data)
        labels.append(
            {
                "id": case["id"],
                "file": name,
                "format": fmt,
                "expect": case["expect"],
                "expect_kind": case.get("expect_kind", "fnol"),
                "expect_decision": case["expect_decision"],
            }
        )
        print(f"{name:40s} {len(data):>8,d} bytes")
    (OUT.parent / "labels.json").write_text(json.dumps(labels, indent=2))


if __name__ == "__main__":
    main()
