import os
import hmac
import hashlib
import json
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from database import create_document, get_documents, db
from schemas import RunnerProfile, Session, ProEntitlement

app = FastAPI(title="Runner Metronome API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Runner Metronome Backend is running"}

# ---------------------------------------------------------------------
# Utility: simple pace->BPM conversion based on run type and personalization
# ---------------------------------------------------------------------

RUN_TYPE_OFFSETS = {
    "easy": -5,
    "recovery": -8,
    "long": -3,
    "tempo": 0,
    "interval": +5,
    "sprint": +8,
}


def pace_to_bpm(pace_value: float, pace_unit: str = "min_per_km", run_type: str = "easy", baseline_cadence: Optional[int] = None, target_cadence: Optional[int] = None) -> int:
    """
    Convert pace to target cadence (BPM = steps/minute).
    Heuristic + personalization.
    """
    pace_min_per_km = pace_value if pace_unit == "min_per_km" else pace_value * 0.621371
    anchors = [
        (3.0, 200), (4.0, 185), (5.0, 170), (6.0, 160), (7.0, 150), (8.0, 145)
    ]
    x = max(min(pace_min_per_km, anchors[-1][0]), anchors[0][0])
    for i in range(len(anchors)-1):
        x1, y1 = anchors[i]; x2, y2 = anchors[i+1]
        if x1 <= x <= x2:
            t = (x - x1) / (x2 - x1)
            bpm = y1 + t * (y2 - y1)
            break
    else:
        bpm = anchors[-1][1]
    bpm += RUN_TYPE_OFFSETS.get(run_type, 0)
    if target_cadence:
        bpm = 0.75 * bpm + 0.25 * target_cadence
    if baseline_cadence:
        diff = bpm - baseline_cadence
        if abs(diff) > 10:
            bpm -= 2 if diff > 0 else -2
    bpm_int = int(round(bpm))
    return max(120, min(220, bpm_int))

# ---------------------------------------------------------------------
# API Models
# ---------------------------------------------------------------------

class BPMRequest(BaseModel):
    pace_value: float
    pace_unit: str = "min_per_km"
    run_type: str = "easy"
    baseline_cadence: Optional[int] = None
    target_cadence: Optional[int] = None

class ProClaimRequest(BaseModel):
    email: Optional[str] = None
    user_id: Optional[str] = None

class CheckoutCreateRequest(BaseModel):
    email: Optional[str] = None

# ---------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------

@app.post("/api/convert/pace-to-bpm")
def convert_pace_to_bpm(req: BPMRequest):
    bpm = pace_to_bpm(
        pace_value=req.pace_value,
        pace_unit=req.pace_unit,
        run_type=req.run_type,
        baseline_cadence=req.baseline_cadence,
        target_cadence=req.target_cadence,
    )
    return {"bpm": bpm}

# Profile CRUD-light
@app.put("/api/profile")
def upsert_profile(profile: RunnerProfile):
    # simple upsert semantics: store a new document; client can load latest by user_id
    profile_id = create_document("runnerprofile", profile)
    return {"id": profile_id}

@app.get("/api/profile")
def get_profile(user_id: str):
    items = get_documents("runnerprofile", {"user_id": user_id}, limit=1)
    if not items:
        raise HTTPException(status_code=404, detail="Profile not found")
    it = items[0]
    it["_id"] = str(it.get("_id"))
    return it

@app.get("/api/profiles")
def list_profiles(limit: int = 20):
    items = get_documents("runnerprofile", {}, limit)
    for it in items:
        it["_id"] = str(it.get("_id"))
    return {"items": items}

@app.post("/api/sessions")
def create_session(session: Session):
    session_id = create_document("session", session)
    return {"id": session_id}

@app.get("/api/sessions")
def list_sessions(request: Request, user_id: Optional[str] = None, limit: Optional[int] = None, authorization: Optional[str] = Header(None)):
    # Determine pro access from JWT in Authorization: Bearer <token>
    is_pro = False
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience=JWT_AUDIENCE, issuer=JWT_ISSUER)
            is_pro = bool(payload.get("pro"))
        except Exception:
            is_pro = False
    # Cap results for non-pro
    effective_limit = limit or (50 if is_pro else 5)
    query = {}
    if user_id:
        query["user_id"] = user_id
    items = get_documents("session", query, effective_limit)
    for it in items:
        it["_id"] = str(it.get("_id"))
    return {"items": items, "pro": is_pro}

# ---------------------------------------------------------------------
# Pro entitlement: webhook + verification + JWT minting
# ---------------------------------------------------------------------

JWT_SECRET = os.getenv("JWT_SECRET", "dev_secret_change_me")
JWT_ISSUER = os.getenv("JWT_ISSUER", "runner-metronome")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "runner-metronome-app")
JWT_EXP_HOURS = int(os.getenv("JWT_EXP_HOURS", "720"))  # 30 days default

STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "http://localhost:3000/?pro=1")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "http://localhost:3000/")

class StripeEvent(BaseModel):
    id: str
    type: str
    data: dict

@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    if STRIPE_WEBHOOK_SECRET:
        sig = request.headers.get("Stripe-Signature")
        payload = await request.body()
        try:
            import stripe
            stripe.Webhook.construct_event(payload=payload, sig_header=sig, secret=STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)[:80]}")
        event = json.loads(payload.decode("utf-8"))
    else:
        # Fallback: accept raw JSON in dev if secret not configured
        event = await request.json()

    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {})

    # Handle successful one-time payment or checkout completion
    if event_type in ("checkout.session.completed", "payment_intent.succeeded"):
        email = obj.get("customer_details", {}).get("email") or obj.get("receipt_email") or obj.get("customer_email")
        customer_id = obj.get("customer")
        checkout_session_id = obj.get("id") if event_type == "checkout.session.completed" else None
        payment_intent_id = obj.get("payment_intent") if event_type == "checkout.session.completed" else obj.get("id")

        if not email and not customer_id:
            # Nothing to bind entitlement to
            return {"status": "ignored"}

        ent = ProEntitlement(
            email=email,
            pro_active=True,
            source="stripe",
            stripe_customer_id=customer_id,
            stripe_checkout_session_id=checkout_session_id,
            stripe_payment_intent_id=payment_intent_id,
        )
        try:
            create_document("proentitlement", ent)
        except Exception:
            # best-effort; ignore if duplicates
            pass
        return {"status": "ok"}

    return {"status": "unhandled"}


def mint_jwt(user_id: Optional[str] = None, email: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id or email or "anon",
        "email": email,
        "pro": True,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXP_HOURS)).timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return token

@app.post("/api/pro/claim")
def claim_pro(req: ProClaimRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Try to locate a prior Stripe-based entitlement by email or user_id
    query = {}
    if req.email:
        query["email"] = req.email
    if req.user_id:
        query["user_id"] = req.user_id

    items = get_documents("proentitlement", query or {}, limit=1)
    if items:
        token = mint_jwt(user_id=req.user_id, email=req.email)
        return {"pro": True, "token": token}
    raise HTTPException(status_code=404, detail="No entitlement found")

@app.post("/api/pro/verify")
def verify_pro(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience=JWT_AUDIENCE, issuer=JWT_ISSUER)
        return {"pro": bool(payload.get("pro")), "exp": payload.get("exp"), "email": payload.get("email")}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)[:80]}")

@app.post("/api/checkout/create")
def create_checkout_session(req: CheckoutCreateRequest):
    if not STRIPE_PRICE_ID:
        raise HTTPException(status_code=500, detail="Stripe price not configured")
    try:
        import stripe
        stripe.api_key = os.getenv("STRIPE_API_KEY")
        if not stripe.api_key:
            raise HTTPException(status_code=500, detail="Stripe API key not configured")
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
            customer_email=req.email if req.email else None,
            allow_promotion_codes=False,
        )
        return {"url": session.get("url")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)[:120]}")

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
