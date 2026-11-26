from __future__ import annotations

import shutil

import pytest

from app.pipeline.router import route_and_read
from tests.conftest import SAMPLES

needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")


def test_typed_pdf_uses_text_layer():
    r = route_and_read((SAMPLES / "c01_auto_typed_pdf.pdf").read_bytes(), "c01.pdf")
    assert r.route == "text_pdf" and "PA-20481736" in r.source_text


def test_free_text_email():
    r = route_and_read((SAMPLES / "c05_burglary_email.eml").read_bytes(), "c05.eml")
    assert r.route == "free_text_email" and "HO-72599107" in r.source_text


@needs_tesseract
def test_scanned_tiff_ocr():
    r = route_and_read((SAMPLES / "c03_water_tiff_2pages.tif").read_bytes(), "c03.tif")
    assert r.route == "scanned_form" and r.page_count == 2
    assert "HO-70245519" in r.source_text


@needs_tesseract
def test_email_with_scanned_attachment():
    r = route_and_read((SAMPLES / "c06_email_with_tiff_attachment.eml").read_bytes(), "c06.eml")
    assert r.route == "email_with_attachments"
    assert "HO-73412850" in r.source_text.replace(" ", "")


def test_unsupported_file():
    with pytest.raises(ValueError):
        route_and_read(b"\x00\x01garbage", "x.bin")
