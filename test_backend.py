import os
import json

# Ensure dev-friendly behavior for tests BEFORE app import
os.environ["DEV_ALLOW_MEMORY"] = "1"
os.environ["DEBUG_AUTH_CODES"] = "1"

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["message"].startswith("Runner Metronome Backend")


def test_pace_to_bpm():
    r = client.post("/api/convert/pace-to-bpm", json={"pace_value": 5.0})
    assert r.status_code == 200
    data = r.json()
    assert 120 <= data["bpm"] <= 220


def test_auth_request_and_verify_dev_mode():
    # request code
    email = "test@example.com"
    r = client.post("/api/auth/request-code", json={"email": email})
    assert r.status_code == 200
    code = r.json()["debug_code"]
    assert code is not None and len(code) == 6

    # verify code
    r2 = client.post("/api/auth/verify-code", json={"email": email, "code": code})
    assert r2.status_code == 200
    j = r2.json()
    assert j["user_id"] == email
    # pro_token may be None if no entitlement yet


def test_claim_without_entitlement():
    r = client.post("/api/pro/claim", json={"email": "nopro@example.com"})
    assert r.status_code == 404


def test_test_endpoint_has_sections():
    r = client.get("/test")
    assert r.status_code == 200
    j = r.json()
    assert "stripe" in j and "jwt" in j and "cors" in j


def test_webhook_entitlement_and_claim_jwt():
    """
    Simulate a Stripe webhook in dev (no secret configured):
    - send a checkout.session.completed payload with an email
    - expect entitlement to be recorded (status ok)
    - claim pro should return a JWT token
    - verify token should confirm pro=True
    """
    email = "protester@example.com"

    # Webhook: checkout.session.completed (dev path accepts unsigned JSON when no secret provided)
    event = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_test_123",
                "payment_intent": "pi_test_123",
                "customer_details": {"email": email},
            }
        },
    }
    r = client.post("/api/stripe/webhook", json=event)
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "already_processed")

    # Claim pro using the email from webhook
    r2 = client.post("/api/pro/claim", json={"email": email})
    assert r2.status_code == 200
    data = r2.json()
    assert data["pro"] is True
    assert isinstance(data["token"], str) and len(data["token"]) > 10

    # Verify token
    r3 = client.post("/api/pro/verify", params={"token": data["token"]})
    assert r3.status_code == 200
    v = r3.json()
    assert v["pro"] is True
    assert v["email"] == email

    # Idempotency: send the same event again → "already_processed"
    r4 = client.post("/api/stripe/webhook", json=event)
    assert r4.status_code == 200
    assert r4.json()["status"] == "already_processed"
