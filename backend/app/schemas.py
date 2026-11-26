"""The FNOL extraction contract. Every field carries a value, a confidence and the source quote it came from."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

LossCause = Literal[
    "auto_collision",
    "auto_theft",
    "glass_damage",
    "fire",
    "water_damage",
    "wind_hail",
    "theft_burglary",
    "vandalism",
    "liability_injury",
    "other",
]

LineOfBusiness = Literal["auto", "property", "liability", "other"]


class Party(BaseModel):
    name: str
    role: Literal["insured", "claimant", "third_party", "witness", "driver", "other"] = "other"
    phone: str | None = None
    insurer: str | None = None


class LineItem(BaseModel):
    description: str
    amount: float


class ExtractedField(BaseModel):
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    source: str | None = Field(default=None, description="Verbatim quote from the document supporting the value")
    method: str = "llm"  # llm | tool | self_check | human
    notes: list[str] = Field(default_factory=list)


# name -> (python type description for the LLM, required for submission?)
FIELD_SPECS: dict[str, dict[str, Any]] = {
    "policy_number": {"type": "string", "required": True, "desc": "Policy number exactly as written"},
    "line_of_business": {
        "type": "string",
        "enum": list(get_args(LineOfBusiness)),
        "required": True,
        "desc": "auto, property, liability or other",
    },
    "loss_date": {"type": "string", "required": True, "desc": "Date of loss, ISO YYYY-MM-DD"},
    "loss_time": {"type": "string", "required": False, "desc": "Time of loss HH:MM 24h if given"},
    "loss_cause": {"type": "string", "enum": list(get_args(LossCause)), "required": True, "desc": "Cause of loss"},
    "loss_location": {"type": "string", "required": True, "desc": "Where the loss happened (address or place)"},
    "description": {"type": "string", "required": True, "desc": "Short factual description of what happened"},
    "insured_name": {"type": "string", "required": True, "desc": "Named insured / policyholder"},
    "insured_phone": {"type": "string", "required": False, "desc": "Insured phone"},
    "insured_email": {"type": "string", "required": False, "desc": "Insured email"},
    "reporter_name": {"type": "string", "required": True, "desc": "Person reporting the loss"},
    "reporter_relationship": {
        "type": "string",
        "required": False,
        "desc": "Reporter relation to insured (self, spouse, agent...)",
    },
    "other_parties": {
        "type": "array",
        "required": False,
        "desc": "Other people involved: list of {name, role, phone, insurer}",
    },
    "vehicle_or_property": {
        "type": "string",
        "required": False,
        "desc": "Vehicle (year make model, plate) or property damaged",
    },
    "police_report_number": {"type": "string", "required": False, "desc": "Police / fire report number if any"},
    "injuries": {"type": "boolean", "required": True, "desc": "true if anyone was injured"},
    "estimated_amount": {
        "type": "number",
        "required": False,
        "desc": "Total estimated damage amount (number, no symbols)",
    },
    "currency": {"type": "string", "required": False, "desc": "ISO currency code, e.g. USD"},
    "line_items": {"type": "array", "required": False, "desc": "Itemised damages: list of {description, amount}"},
}

REQUIRED_FIELDS = [k for k, v in FIELD_SPECS.items() if v["required"]]


def field_json_schema() -> dict[str, Any]:
    """JSON schema for the submit_extraction tool: {field: {value, confidence, source}}."""
    props: dict[str, Any] = {}
    for name, spec in FIELD_SPECS.items():
        if spec["type"] == "array" and name == "other_parties":
            value_schema: dict[str, Any] = {
                "type": ["array", "null"],
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {
                            "type": "string",
                            "enum": ["insured", "claimant", "third_party", "witness", "driver", "other"],
                        },
                        "phone": {"type": ["string", "null"]},
                        "insurer": {"type": ["string", "null"]},
                    },
                    "required": ["name", "role"],
                },
            }
        elif spec["type"] == "array":
            value_schema = {
                "type": ["array", "null"],
                "items": {
                    "type": "object",
                    "properties": {"description": {"type": "string"}, "amount": {"type": "number"}},
                    "required": ["description", "amount"],
                },
            }
        else:
            value_schema = {"type": [spec["type"], "null"]}
            if "enum" in spec:
                value_schema["enum"] = [*spec["enum"], None]
        props[name] = {
            "type": "object",
            "description": spec["desc"],
            "properties": {
                "value": value_schema,
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Your calibrated probability the value is correct",
                },
                "source": {
                    "type": ["string", "null"],
                    "description": "Exact quote copied from the document that supports the value",
                },
            },
            "required": ["value", "confidence", "source"],
        }
    return {"type": "object", "properties": props, "required": list(FIELD_SPECS.keys())}


class ValidationIssue(BaseModel):
    rule: str
    field: str | None = None
    severity: Literal["error", "warning"] = "error"
    message: str


class ClaimOut(BaseModel):
    id: str
    reference: str
    status: str
    decision: str | None
    fields: dict[str, Any]
    validation: list[Any]
    review_reasons: list[Any]
    llm_usage: dict[str, Any]
    timings_ms: dict[str, Any]
    external_system: str | None
    external_claim_number: str | None
    external_claim_id: str | None
    created_at: str
    updated_at: str
    document: dict[str, Any]
    error: str | None = None
    reviewed_by: str | None = None
    reject_reason: str | None = None
