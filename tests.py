import os
import json
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
    os.environ["DEBUG_AUTH_CODES"] = "1"
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
    assert "stripe" in j and "jwt" in j

