import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

from database import create_document, get_documents
from schemas import RunnerProfile, Session

app = FastAPI(title="Runner Metronome API", version="0.1.0")

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
# This mirrors the spec's approach at a high level.
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
    - pace_value: minutes per unit (e.g., 5.0 = 5:00 pace)
    - pace_unit: min_per_km or min_per_mile
    - run_type: easy/tempo/interval/long/recovery/sprint
    - baseline/target cadence for personalization

    Heuristic baseline mapping:
      3:00 min/km -> ~200 spm
      4:00        -> ~185
      5:00        -> ~170
      6:00        -> ~160
      7:00        -> ~150
    Linear between points. Then apply run type offset and gently bias toward user's target.
    """
    # Normalize to min/km
    pace_min_per_km = pace_value if pace_unit == "min_per_km" else pace_value * 0.621371  # approx conversion

    # Piecewise linear map between key points
    anchors = [
        (3.0, 200),
        (4.0, 185),
        (5.0, 170),
        (6.0, 160),
        (7.0, 150),
        (8.0, 145),
    ]
    # Clamp pace range
    x = max(min(pace_min_per_km, anchors[-1][0]), anchors[0][0])

    # Find segment
    for i in range(len(anchors) - 1):
        x1, y1 = anchors[i]
        x2, y2 = anchors[i + 1]
        if x1 <= x <= x2:
            # linear interpolate
            t = (x - x1) / (x2 - x1)
            bpm = y1 + t * (y2 - y1)
            break
    else:
        bpm = anchors[-1][1]

    # Run type offset
    bpm += RUN_TYPE_OFFSETS.get(run_type, 0)

    # Personalization bias: move 25% toward user's target_cadence if provided
    if target_cadence:
        bpm = 0.75 * bpm + 0.25 * target_cadence

    # If baseline provided, nudge by +/- 2 if far off baseline
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

@app.post("/api/profile")
def create_profile(profile: RunnerProfile):
    profile_id = create_document("runnerprofile", profile)
    return {"id": profile_id}

@app.get("/api/profiles")
def list_profiles(limit: int = 20):
    items = get_documents("runnerprofile", {}, limit)
    # string-ify ObjectId
    for it in items:
        it["_id"] = str(it.get("_id"))
    return {"items": items}

@app.post("/api/sessions")
def create_session(session: Session):
    session_id = create_document("session", session)
    return {"id": session_id}

@app.get("/api/sessions")
def list_sessions(limit: int = 50):
    items = get_documents("session", {}, limit)
    for it in items:
        it["_id"] = str(it.get("_id"))
    return {"items": items}

@app.get("/test")
def test_database():
    from database import db
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
