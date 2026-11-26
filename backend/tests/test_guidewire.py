from __future__ import annotations

import pytest

from app.integrations.base import PushError
from app.integrations.registry import get_adapter
from app.models import Integration
from app.security import encrypt_secret
from tests.test_units import F


def _integ():
    return Integration(
        kind="guidewire",
        name="t",
        base_url="http://mock-cc/cc/rest",
        auth_mode="oauth2",
        token_url="http://mock-cc/oauth2/token",
        client_id="fnol-intake-demo",
        secret_encrypted=encrypt_secret("stand-in-secret"),
        options={},
    )


def test_payload_shape():
    body = get_adapter(_integ()).build_payload(F())
    a = body["data"]["attributes"]
    assert a["policyNumber"] == "PA-20481736"
    assert a["lossDate"] == "2026-11-14T12:00:00.000Z"
    assert a["lossCause"] == {"code": "vehcollision"}


def test_connection_and_full_fnol_flow(mock_cc):
    ad = get_adapter(_integ())
    ok, msg = ad.test_connection()
    assert ok, msg
    state: dict = {}
    res = ad.push(F(other_parties=[{"name": "Kevin Lowe", "role": "driver"}]), "k1", state, lambda s: None, "R1")
    assert res.claim_number.startswith("000-00-") and res.state == "submitted"
    paths = [(c["method"], c["url"].split("/cc/rest")[-1]) for c in res.calls if "/cc/rest" in c["url"]]
    assert paths[0] == ("POST", "/claim/v1/claims")
    assert paths[-1][1].endswith("/submit")
    claim = mock_cc.CLAIMS[res.external_id]
    assert claim["state"]["code"] == "open" and claim["reporter"]["displayName"] == "Maria Okafor"
    assert len(claim["contacts"]) == 2


def test_resume_does_not_duplicate(mock_cc):
    ad = get_adapter(_integ())
    state: dict = {}
    ad.push(F(), "k2", state, lambda s: None, "R2")
    n = len(mock_cc.CLAIMS)
    state.pop("submitted")  # pretend the process crashed before the submit checkpoint
    with pytest.raises(PushError):  # submit replays with the same GW-DBTransaction-ID -> rejected, no new claim
        get_adapter(_integ()).push(F(), "k2", state, lambda s: None, "R2")
    assert len(mock_cc.CLAIMS) == n


def test_bad_credentials_and_policy_errors(mock_cc):
    i = _integ()
    i.secret_encrypted = encrypt_secret("wrong")
    ok, msg = get_adapter(i).test_connection()
    assert not ok
    with pytest.raises(PushError) as e:
        get_adapter(_integ()).push(
            F(policy_number="PA-55203619", loss_date="2026-11-11"), "k3", {}, lambda s: None, "R3"
        )
    assert not e.value.retryable and "No policy was found" in str(e.value)
