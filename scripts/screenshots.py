"""Capture UI screenshots with headless Chromium. Usage: python scripts_shots.py"""
import time
from playwright.sync_api import sync_playwright

WEB, MOCK, OUT = "http://localhost:3100", "http://localhost:8090", "/workspace/fnol-claims-intake-shots"
import json

IDS = json.load(open("logs/e2e_result.json"))["ids"]
PUSHED, REVIEW, EDITED = IDS["c01_auto_typed_pdf"], IDS["c07_glass_ambiguous_date"], IDS["c04_fire_items_mismatch"]


def shot(page, name, url=None, click=None, wait=1500, full=False):
    if url:
        page.goto(url, wait_until="networkidle")
    if click:
        page.get_by_role("button", name=click).first.click()
    page.wait_for_timeout(wait)
    page.screenshot(path=f"{OUT}/{name}.png", full_page=full)
    print("saved", name)


with sync_playwright() as p:
    b = p.chromium.launch()
    for role in ("supervisor", "auditor"):
        ctx = b.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1.5)
        ctx.add_cookies([{"name": "fnol_role", "value": role, "url": WEB}, {"name": "fnol_user", "value": "david", "url": WEB}])
        page = ctx.new_page()
        page.on("pageerror", lambda e: print("pageerror", str(e)[:500]))
        if role == "supervisor":
            shot(page, "01_dashboard", WEB + "/")
            shot(page, "02_intake_upload", WEB + "/intake")
            shot(page, "03_review_queue", WEB + "/review")
            shot(page, "04_claims_list", WEB + "/claims")
            shot(page, "05_claim_fields", WEB + f"/claims/{PUSHED}", wait=2500)
            shot(page, "06_claim_trace_audit", click="Trace")
            shot(page, "07_claim_payload", click="Payload")
            shot(page, "08_review_claim_ambiguous_date", WEB + f"/claims/{REVIEW}", wait=2500)
            shot(page, "08b_review_claim_edited_and_approved_trace", WEB + f"/claims/{EDITED}", wait=2500)
            shot(page, "08c_edited_claim_audit_trail", click="Trace")
            shot(page, "09_settings_claims_system", WEB + "/settings", full=True)
            shot(page, "10_settings_email_intake", click="Email intake", full=True)
            shot(page, "11_settings_ai_rules", click="AI & rules", full=True)
            shot(page, "12_evals", WEB + "/evals", full=True)
            shot(page, "13_audit_log", WEB + "/audit")
            shot(page, "15_mock_claimcenter_standin", MOCK + "/", full=True)
            page.add_init_script("localStorage.setItem('fnol_theme','dark')")
            shot(page, "16_dark_dashboard", WEB + "/")
            shot(page, "17_dark_review_claim", WEB + f"/claims/{REVIEW}", wait=2500)
        else:
            shot(page, "14_claim_auditor_masked", WEB + f"/claims/{PUSHED}", wait=2500)
        ctx.close()
    b.close()
