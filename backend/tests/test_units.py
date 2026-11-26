from __future__ import annotations

from datetime import date

from app.pipeline import tools as T
from app.pipeline.agent import coerce_fields, ground, quote_found
from app.pipeline.orchestrator import decide
from app.pipeline.validate import validate
from app.security import decrypt_secret, encrypt_secret, mask_fields, mask_obj, mask_text
from app.settings_store import defaults

TODAY = date(2026, 11, 26)


def F(**vals):
    base = {
        "policy_number": "PA-20481736",
        "line_of_business": "auto",
        "loss_date": "2026-11-14",
        "loss_cause": "auto_collision",
        "loss_location": "Elm Ave",
        "description": "rear-ended",
        "insured_name": "Maria Okafor",
        "reporter_name": "Maria Okafor",
        "injuries": False,
        "estimated_amount": 2700.0,
        "line_items": [{"description": "a", "amount": 2000.0}, {"description": "b", "amount": 700.0}],
    }
    base.update(vals)
    return {k: {"value": v, "confidence": 0.95, "source": str(v)} for k, v in base.items()}


def test_encrypt_roundtrip():
    tok = encrypt_secret("s3cr3t")
    assert tok != "s3cr3t"
    assert decrypt_secret(tok) == "s3cr3t"


def test_mask_text_and_fields():
    t = mask_text("Call 217-555-0148 or mail maria.okafor@example.com, SSN 123-45-6789")
    assert "555-0148" not in t and "0148" in t
    assert "maria.okafor@" not in t and "@example.com" in t
    assert "123-45" not in t
    m = mask_fields(F())
    assert m["insured_name"]["value"] == "M*** O***"
    assert m["policy_number"]["value"].endswith("1736") and m["policy_number"]["value"].startswith("*")
    assert m["insured_name"]["source"] == "[masked]"
    assert mask_obj({"client_secret": "x", "nested": {"insured_name": "Ann Lee"}}) == {
        "client_secret": "[redacted]",
        "nested": {"insured_name": "A*** L***"},
    }


def test_parse_date_ambiguity_and_future():
    r = T.parse_date("03/11/2026", today=TODAY)
    assert r["ok"] and r["ambiguous"] and r["alternatives"]["day_first"] == "2026-11-03"
    assert T.parse_date("October 29, 2026", today=TODAY)["iso"] == "2026-10-29"
    assert T.parse_date("12/30/2026", today=TODAY)["in_future"] is True


def test_parse_amount():
    assert T.parse_amount("$4,250.00")["amount"] == 4250.0
    assert T.parse_amount("4.2k USD") == {"ok": True, "amount": 4200.0, "currency": "USD"}
    assert T.sum_amounts([0.1, 0.2])["total"] == 0.3


def test_policy_lookup_ocr_correction(db):
    assert T.lookup_policy(db, "PA-2O481736", "2026-11-14")["policy_number"] == "PA-20481736"
    r = T.lookup_policy(db, "PA-55203619", "2026-11-11")
    assert r["found"] and r["in_force_on_loss_date"] is False
    assert T.lookup_policy(db, "PA-00000000")["found"] is False


def test_validate_clean(db):
    assert [i for i in validate(db, F(), defaults(), TODAY) if i["severity"] == "error"] == []


def test_validate_rules(db):
    rules = {
        i["rule"]
        for i in validate(
            db,
            F(loss_date="2026-12-30", estimated_amount=3000.0, injuries=True, policy_number="BAD"),
            defaults(),
            TODAY,
        )
    }
    assert {"loss_date_not_future", "amounts_consistent", "injury_review", "policy_format", "policy_exists"} <= rules
    rules = {i["rule"] for i in validate(db, F(policy_number="PA-55203619", loss_date="2026-11-11"), defaults(), TODAY)}
    assert "policy_in_force" in rules
    rules = {i["rule"] for i in validate(db, F(estimated_amount=42500.0, line_items=None), defaults(), TODAY)}
    assert "amount_authority" in rules


def test_quote_grounding():
    src = "POLICY NUMBER PA-20481736\nINSURED NAME Maria Okafor"
    assert quote_found("PA-20481736", src) == 1.0
    assert quote_found("Insured Name: Maria  Okafor", src) == 1.0
    assert quote_found("John Smith lives here", src) < 0.75
    fields = coerce_fields({"insured_name": {"value": "John Smith", "confidence": 0.99, "source": "John Smith"}})
    changes = ground(fields, src)
    assert fields["insured_name"]["confidence"] == 0.5 and changes[0]["field"] == "insured_name"


def test_decide_routes_low_confidence_and_rules(db):
    cfg = defaults()
    f = F()
    assert decide(f, [], "fnol", 0.99, cfg, True)[0] == "auto_push"
    f["loss_date"]["confidence"] = 0.4
    d, reasons = decide(f, [], "fnol", 0.99, cfg, True)
    assert d == "review" and reasons[0]["field"] == "loss_date"
    assert decide(F(), [{"rule": "x", "severity": "error", "message": "m"}], "fnol", 0.99, cfg, True)[0] == "review"
    assert (
        decide(F(), [{"rule": "x", "severity": "warning", "message": "m"}], "fnol", 0.99, cfg, True)[0] == "auto_push"
    )
    assert decide(F(), [], "not_claim", 0.99, cfg, True)[0] == "review"
    assert decide(F(), [], "fnol", 0.99, cfg, False)[1][0]["code"] == "no_integration"


def test_ambiguous_date_conflicting_with_carrier_locale(db):
    f = F(loss_date="2026-11-03")
    f["loss_date"]["source"] = "03/11/2026"
    rules = {i["rule"] for i in validate(db, f, defaults(), TODAY)}
    assert "loss_date_ambiguous" in rules
    f = F(loss_date="2026-03-11")
    f["loss_date"]["source"] = "03/11/2026"
    assert "loss_date_ambiguous" not in {i["rule"] for i in validate(db, f, defaults(), TODAY)}


def test_optional_low_confidence_field_does_not_block(db):
    f = F(vehicle_or_property="2023 Mazda ???")
    f["vehicle_or_property"]["confidence"] = 0.3
    assert decide(f, [], "fnol", 0.99, defaults(), True)[0] == "auto_push"


def test_unknown_party_role_is_mapped_to_other_with_a_note():
    from app.pipeline.agent import coerce_fields

    raw = {
        "other_parties": {"value": [{"name": "J", "role": "agent"}, {"name": "K", "role": "driver"}], "confidence": 0.9}
    }
    f = coerce_fields(raw)["other_parties"]
    assert [p["role"] for p in f["value"]] == ["other", "driver"]
    assert "agent" in f["notes"][0]


def test_source_hints_find_facts_in_a_free_text_email():
    from app.pipeline import hints as H

    body = (
        "Hi, I'm reporting a car accident. Policy PA-20481736, insured Maria Okafor. "
        "On 11/14/2026 at about 17:40 at Elm Ave and 5th St, Springfield, IL, I was "
        "stopped at a red light and Kevin Lowe (Bluegate Auto) hit my rear bumper. "
        "Police report SPD-26-114502. No injuries. Estimate: rear bumper $1,450, "
        "trunk lid $820, paint and labour $430 – total $2,700. Reported by Maria "
        "Okafor, (217) 555-0148."
    )
    h = H.source_hints(body, known_names=["Maria Okafor"])
    assert {x["amount"] for x in h["estimated_amount"]} >= {1450.0, 820.0, 430.0, 2700.0}
    assert any(x["value"] == "17:40" for x in h["loss_time"])
    assert any("555-0148" in x["value"] for x in h["insured_phone"])
    assert any(x["value"] == "SPD-26-114502" for x in h["police_report_number"])
    assert any(x["name"] == "Kevin Lowe" and x["org"] == "Bluegate Auto" for x in h["other_parties"])
    empty = {
        k: {"value": None, "confidence": 0.0}
        for k in ("estimated_amount", "other_parties", "loss_time", "police_report_number", "insured_phone")
    }
    empty["insured_name"] = {"value": "Maria Okafor", "confidence": 0.9}
    empty["reporter_name"] = {"value": "Maria Okafor", "confidence": 0.9}
    names = [n for n, _ in H.unfilled_mention_fields(empty, body)]
    assert "estimated_amount" in names and "other_parties" in names
    assert "loss_time" in names and "police_report_number" in names and "insured_phone" in names
    rec = H.fields_to_recheck(empty, body, 0.85, ["policy_number"])
    assert "estimated_amount" in rec and "other_parties" in rec


def test_unfilled_mention_guardrail_routes_to_review(db):
    body = (
        "Kevin Lowe (Bluegate Auto) hit my bumper. Estimate total $2,700. "
        "Reported by Maria Okafor."
    )
    f = F(estimated_amount=None, other_parties=None, insured_name="Maria Okafor")
    cfg = defaults()
    assert cfg["review_if_unfilled_mentions"] is True
    rules = {i["rule"] for i in validate(db, f, cfg, TODAY, source_text=body)}
    assert "unfilled_amount_in_source" in rules
    assert "unfilled_party_in_source" in rules
    cfg = {**cfg, "review_if_unfilled_mentions": False}
    rules = {i["rule"] for i in validate(db, f, cfg, TODAY, source_text=body)}
    assert "unfilled_amount_in_source" not in rules
    assert "unfilled_party_in_source" not in rules


def test_email_sender_and_insured_are_not_kept_as_other_parties():
    from app.pipeline import hints as H

    src = (
        "EMAIL\nFrom: David Oluyale <sender@example.com>\nSubject: FNOL\n\n"
        "Insured Maria Okafor. Kevin Lowe (Bluegate Auto) hit my rear bumper."
    )
    assert H.names_from_headers(src) == ["David Oluyale"]
    fields = {
        "insured_name": {"value": "Maria Okafor", "confidence": 0.9, "notes": []},
        "reporter_name": {"value": "Maria Okafor", "confidence": 0.9, "notes": []},
        "other_parties": {
            "value": [
                {"name": "Kevin Lowe", "role": "driver", "insurer": "Bluegate Auto"},
                {"name": "David Oluyale", "role": "third_party"},
                {"name": "Maria Okafor", "role": "insured"},
            ],
            "confidence": 0.7,
            "notes": [],
        },
    }
    dropped = H.drop_self_parties(fields, src)
    assert "David Oluyale" in dropped and "Maria Okafor" in dropped
    assert [p["name"] for p in fields["other_parties"]["value"]] == ["Kevin Lowe"]
