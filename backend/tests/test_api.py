"""End-to-end through the HTTP API with a scripted LLM (no network) and the in-process ClaimCenter stand-in."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.pipeline import agent
from app.pipeline.llm import LoopResult, Usage
from tests.conftest import SAMPLES

SUP = {"Authorization": "Bearer test-token", "X-User-Role": "supervisor", "X-User-Name": "sam"}
AUD = {"Authorization": "Bearer test-token", "X-User-Role": "auditor", "X-User-Name": "ann"}


class FakeLLM:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}

    def run_tools(self, system, user, tools, final_tool, max_steps):
        if final_tool == "submit_verification":
            return LoopResult({"fields": {}}, Usage(model="fake", calls=1, input_tokens=10, output_tokens=5))
        # exercise one real tool call, like the model would
        lookup = next(t for t in tools if t.name == "lookup_policy")
        lookup.handler({"policy_number": "PA-20481736", "loss_date": "2026-11-14"})
        vals = {
            "policy_number": ("PA-20481736", "PA-20481736"),
            "line_of_business": ("auto", None),
            "loss_date": ("2026-11-14", "11/14/2026"),
            "loss_time": ("17:40", "17:40"),
            "loss_cause": ("auto_collision", None),
            "loss_location": ("Intersection of Elm Ave and 5th St, Springfield, IL", "Elm Ave and 5th St"),
            "description": ("Rear-ended at red light", "other vehicle failed to stop"),
            "insured_name": ("Maria Okafor", "Maria Okafor"),
            "reporter_name": ("Maria Okafor", "Maria Okafor"),
            "injuries": (False, "No"),
            "estimated_amount": (2700.0, "$2,700.00"),
            "currency": ("USD", None),
            "line_items": (
                [
                    {"description": "Rear bumper", "amount": 1450.0},
                    {"description": "Trunk", "amount": 820.0},
                    {"description": "Paint", "amount": 430.0},
                ],
                "Rear bumper replacement $1,450.00",
            ),
        }
        vals.update(self.overrides)
        fields = {k: {"value": v, "confidence": 0.95, "source": s} for k, (v, s) in vals.items()}
        return LoopResult(
            {"document_kind": "fnol", "document_kind_confidence": 0.99, "fields": fields},
            Usage(model="claude-haiku-5-5", provider="anthropic", calls=2, input_tokens=1000, output_tokens=200),
        )


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def _activate(client):
    iid = client.get("/api/integrations", headers=SUP).json()["integrations"][0]["id"]
    r = client.post(f"/api/integrations/{iid}/test", headers=SUP).json()
    assert r["last_test_ok"], r
    assert client.post(f"/api/integrations/{iid}/activate", headers=SUP).json()["is_active"]


def _drain():
    from app.worker import work_once

    while work_once():
        pass


def test_auth_required(client):
    assert client.get("/api/claims").status_code == 401


def test_clean_claim_is_pushed_automatically(client, mock_cc, monkeypatch):
    monkeypatch.setattr(agent, "get_provider", lambda p, m: FakeLLM())
    _activate(client)
    data = (SAMPLES / "c01_auto_typed_pdf.pdf").read_bytes()
    r = client.post("/api/documents", headers=SUP, files=[("files", ("c01.pdf", data, "application/pdf"))]).json()
    cid = r["results"][0]["claim_id"]
    _drain()
    d = client.get(f"/api/claims/{cid}", headers=SUP).json()
    assert d["status"] == "pushed", d
    assert d["external_claim_number"].startswith("000-00-")
    assert d["document"]["route"] == "text_pdf"
    assert d["llm_usage"]["cost_usd"] == pytest.approx(0.0002, abs=1e-6)
    steps = [e["step"] for e in d["events"] if e["event_type"] == "step_completed"]
    assert steps == ["route_and_read", "extract", "ground", "self_check", "validate"]
    assert any(e["event_type"] == "pushed" for e in d["events"])
    # duplicate upload is ignored, not re-pushed
    r2 = client.post("/api/documents", headers=SUP, files=[("files", ("again.pdf", data, "application/pdf"))]).json()
    assert r2["results"][0]["duplicate"] is True
    # auditors see masked PII and cannot open the scan
    a = client.get(f"/api/claims/{cid}", headers=AUD).json()
    assert a["fields"]["insured_name"]["value"] == "M*** O***" and a["pii_masked"]
    assert client.get(f"/api/documents/{d['document']['id']}/file", headers=AUD).status_code == 403
    assert client.post(f"/api/claims/{cid}/approve", headers=AUD).status_code == 403


def test_bad_claim_goes_to_review_then_human_fix_and_approve(client, mock_cc, monkeypatch):
    monkeypatch.setattr(agent, "get_provider", lambda p, m: FakeLLM({"estimated_amount": (3700.0, "$2,700.00")}))
    _activate(client)
    data = (SAMPLES / "c01_auto_typed_pdf.pdf").read_bytes()
    cid = client.post("/api/documents", headers=SUP, files=[("files", ("c01.pdf", data, "application/pdf"))]).json()[
        "results"
    ][0]["claim_id"]
    _drain()
    d = client.get(f"/api/claims/{cid}", headers=SUP).json()
    assert d["status"] == "needs_review"
    codes = {r["code"] for r in d["review_reasons"]}
    assert "rule:amounts_consistent" in codes and "low_confidence" in codes  # quote does not support 3700
    assert client.post(f"/api/claims/{cid}/approve", headers=SUP).status_code == 422  # hard rule blocks
    e = client.patch(f"/api/claims/{cid}/fields", headers=SUP, json={"fields": {"estimated_amount": 2700.0}}).json()
    assert e["fields"]["estimated_amount"]["method"] == "human"
    assert client.post(f"/api/claims/{cid}/approve", headers=SUP, json={"reason": "checked scan"}).status_code == 200
    _drain()
    d = client.get(f"/api/claims/{cid}", headers=SUP).json()
    assert d["status"] == "pushed"
    kinds = [e["event_type"] for e in d["events"]]
    assert kinds.index("fields_edited") < kinds.index("approved") < kinds.index("pushed")


def test_settings_and_integration_secret_never_returned(client):
    r = client.post(
        "/api/integrations",
        headers=SUP,
        json={
            "kind": "webhook",
            "name": "hook",
            "base_url": "http://example.invalid/hook",
            "auth_mode": "hmac",
            "secret": "topsecret",
        },
    ).json()
    assert r["has_secret"] is True and "topsecret" not in str(r)
    assert client.put("/api/settings", headers=AUD, json={"auto_push": False}).status_code == 403
    assert client.put("/api/settings", headers=SUP, json={"auto_push": False}).json()["settings"]["auto_push"] is False
