"""Schema bootstrap + seed data (policy registry, stand-in ClaimCenter integration, Composio connector)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path

from .db import Base, get_engine, session_scope
from .models import EmailConnector, Integration, Policy
from .security import SecretsKeyMissing, encrypt_secret

log = logging.getLogger("fnol.seed")
ROOT = Path(__file__).resolve().parents[2]


def ensure_schema_and_seed() -> None:
    engine = get_engine()
    if engine.dialect.name == "sqlite" or os.getenv("AUTO_CREATE_SCHEMA", "").lower() in ("1", "true"):
        Base.metadata.create_all(engine)
    seed()


def seed() -> None:
    policy_file = Path(os.getenv("POLICY_SEED_FILE", str(ROOT / "samples" / "policies.json")))
    with session_scope() as db:
        if policy_file.exists() and db.query(Policy).count() == 0:
            for p in json.loads(policy_file.read_text()):
                db.add(
                    Policy(
                        policy_number=p["policy_number"],
                        insured_name=p["insured_name"],
                        policy_type=p["policy_type"],
                        effective_date=date.fromisoformat(p["effective_date"]),
                        expiration_date=date.fromisoformat(p["expiration_date"]),
                        status=p["status"],
                    )
                )
            log.info("seeded policies from %s", policy_file)

        mock = os.getenv("MOCK_CLAIMCENTER_URL")
        if mock and db.query(Integration).count() == 0:
            try:
                secret = encrypt_secret(os.getenv("MOCK_CLAIMCENTER_CLIENT_SECRET", "stand-in-secret"))
            except SecretsKeyMissing:
                secret = None
            db.add(
                Integration(
                    kind="guidewire",
                    name="ClaimCenter stand-in (mock, not real Guidewire)",
                    base_url=mock.rstrip("/") + "/cc/rest",
                    auth_mode="oauth2",
                    token_url=mock.rstrip("/") + "/oauth2/token",
                    client_id="fnol-intake-demo",
                    secret_encrypted=secret,
                    scopes="cc.claims.write tenant.demo",
                    is_stand_in=True,
                )
            )
            log.info("seeded stand-in ClaimCenter integration")

        uid = os.getenv("SEED_COMPOSIO_USER_ID")
        if uid and db.query(EmailConnector).filter(EmailConnector.kind == "composio_gmail").count() == 0:
            db.add(
                EmailConnector(
                    kind="composio_gmail",
                    name="Claims inbox (Gmail via Composio)",
                    config={
                        "user_id": uid,
                        "query": os.getenv("SEED_COMPOSIO_QUERY", "subject:FNOL newer_than:30d"),
                        "max_results": 10,
                    },
                )
            )
