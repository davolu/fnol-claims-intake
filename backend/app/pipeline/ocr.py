"""Text extraction: text-layer PDFs via pdfplumber, scans (image PDFs, TIFF, PNG/JPEG) via Tesseract.
Azure Document Intelligence is an optional drop-in engine (OCR_ENGINE=azure_di)."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import pdfplumber
import pytesseract
from PIL import Image, ImageFilter, ImageOps

from ..config import get_settings

MIN_TEXT_CHARS_PER_PAGE = 40
PSM = "--psm 6"  # uniform block: keeps form label and value on the same line


@dataclass
class PageText:
    page: int
    text: str
    method: str  # text_layer | tesseract | azure_di
    confidence: float | None = None


@dataclass
class OCRResult:
    pages: list[PageText] = field(default_factory=list)
    engine: str = ""

    @property
    def text(self) -> str:
        return "\n\n".join(f"[page {p.page}]\n{p.text.strip()}" for p in self.pages)

    @property
    def mean_confidence(self) -> float | None:
        vals = [p.confidence for p in self.pages if p.confidence is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    @property
    def scanned(self) -> bool:
        return any(p.method != "text_layer" for p in self.pages)


def sniff_kind(data: bytes, filename: str = "") -> str:
    head = data[:8]
    name = filename.lower()
    if head.startswith(b"%PDF"):
        return "pdf"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head.startswith(b"\x89PNG"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if (
        name.endswith(".eml")
        or b"\nSubject:" in data[:4000]
        or data[:5000].lower().startswith(b"from:")
        or (b"MIME-Version:" in data[:4000])
    ):
        return "eml"
    if name.endswith(".txt"):
        return "txt"
    return "unknown"


def _orient(g: Image.Image) -> Image.Image:
    try:  # auto-rotate pages scanned sideways/upside down (Tesseract orientation detection)
        osd = pytesseract.image_to_osd(g, output_type=pytesseract.Output.DICT)
        rot = int(osd.get("rotate", 0))
        if rot in (90, 180, 270) and float(osd.get("orientation_conf", 0)) > 3:
            g = g.rotate(-rot, expand=True, fillcolor=255)
    except pytesseract.TesseractError:
        pass
    return g


def _ocr_once(g: Image.Image, psm: str) -> tuple[str, float | None]:
    data = pytesseract.image_to_data(g, output_type=pytesseract.Output.DICT, config=psm)
    words = [
        (str(w), float(c)) for c, w in zip(data["conf"], data["text"], strict=False) if str(w).strip() and float(c) >= 0
    ]
    conf = round(sum(c for _, c in words) / len(words) / 100, 3) if words else None
    return pytesseract.image_to_string(g, config=psm), conf


GOOD_ENOUGH = 0.80


def tesseract_image(img: Image.Image) -> tuple[str, float | None]:
    """OCR with a small strategy search: denoised block layout first, then alternatives if the page reads
    poorly. The pass with the highest mean word confidence wins."""
    base = _orient(ImageOps.autocontrast(ImageOps.grayscale(img)))
    denoised = base.filter(ImageFilter.MedianFilter(3))  # remove scanner speckle
    best: tuple[str, float | None] = ("", None)
    for g, psm in ((denoised, PSM), (denoised, "--psm 4"), (base, PSM), (base, "--psm 3")):
        text, conf = _ocr_once(g, psm)
        if best[1] is None or (conf or 0) > (best[1] or 0):
            best = (text, conf)
        if (conf or 0) >= GOOD_ENOUGH:
            break
    return best


def _azure_di(data: bytes, content_type: str) -> OCRResult:
    s = get_settings()
    if not (s.azure_di_endpoint and s.azure_di_key):
        raise RuntimeError("Azure Document Intelligence selected but AZURE_DI_ENDPOINT/AZURE_DI_KEY are not set")
    url = f"{s.azure_di_endpoint.rstrip('/')}/documentintelligence/documentModels/prebuilt-read:analyze"
    with httpx.Client(timeout=60) as c:
        r = c.post(
            url,
            params={"api-version": "2024-11-30"},
            content=data,
            headers={"Ocp-Apim-Subscription-Key": s.azure_di_key, "Content-Type": content_type},
        )
        r.raise_for_status()
        op = r.headers["Operation-Location"]
        for _ in range(60):
            res = c.get(op, headers={"Ocp-Apim-Subscription-Key": s.azure_di_key}).json()
            if res.get("status") in ("succeeded", "failed"):
                break
            time.sleep(1)
    if res.get("status") != "succeeded":
        raise RuntimeError(f"Azure DI analyze failed: {res.get('error')}")
    out = OCRResult(engine="azure_di")
    for p in res["analyzeResult"]["pages"]:
        words = p.get("words", [])
        text = "\n".join(line["content"] for line in p.get("lines", []))
        conf = round(sum(w["confidence"] for w in words) / len(words), 3) if words else None
        out.pages.append(PageText(page=p["pageNumber"], text=text, method="azure_di", confidence=conf))
    return out


def extract_text(data: bytes, kind: str) -> OCRResult:
    s = get_settings()
    if s.ocr_engine == "azure_di" and kind in ("pdf", "tiff", "png", "jpeg"):
        ct = {"pdf": "application/pdf", "tiff": "image/tiff", "png": "image/png", "jpeg": "image/jpeg"}[kind]
        return _azure_di(data, ct)

    if kind == "pdf":
        res = OCRResult(engine="pdfplumber+tesseract")
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                txt = page.extract_text() or ""
                if len(txt.strip()) >= MIN_TEXT_CHARS_PER_PAGE:
                    res.pages.append(PageText(page=i, text=txt, method="text_layer", confidence=1.0))
                else:
                    img = page.to_image(resolution=300).original
                    t, conf = tesseract_image(img)
                    res.pages.append(PageText(page=i, text=t, method="tesseract", confidence=conf))
        if all(p.method == "text_layer" for p in res.pages):
            res.engine = "pdfplumber"
        return res

    if kind in ("tiff", "png", "jpeg"):
        res = OCRResult(engine="tesseract")
        img = Image.open(io.BytesIO(data))
        n = getattr(img, "n_frames", 1)
        for i in range(n):
            img.seek(i)
            t, conf = tesseract_image(img.copy())
            res.pages.append(PageText(page=i + 1, text=t, method="tesseract", confidence=conf))
        return res

    if kind == "txt":
        return OCRResult(
            pages=[PageText(page=1, text=data.decode("utf-8", "replace"), method="text_layer", confidence=1.0)],
            engine="plain",
        )
    raise ValueError(f"Unsupported document type: {kind}")


def render_page_png(data: bytes, kind: str, page: int, width: int = 1100) -> bytes:
    """Render one page of a PDF/TIFF/image as PNG for the review screen."""
    if kind == "pdf":
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            img = pdf.pages[page - 1].to_image(resolution=150).original
    else:
        img = Image.open(io.BytesIO(data))
        img.seek(page - 1)
        img = img.convert("RGB")
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def page_count(data: bytes, kind: str) -> int:
    if kind == "pdf":
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return len(pdf.pages)
    if kind in ("tiff", "png", "jpeg"):
        return int(getattr(Image.open(io.BytesIO(data)), "n_frames", 1))
    return 0


def describe(res: OCRResult) -> dict[str, Any]:
    return {
        "engine": res.engine,
        "pages": [
            {"page": p.page, "method": p.method, "chars": len(p.text), "confidence": p.confidence} for p in res.pages
        ],
        "mean_confidence": res.mean_confidence,
    }
