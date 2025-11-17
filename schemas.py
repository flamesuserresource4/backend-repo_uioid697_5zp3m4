"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List

# ---------------------------------------------------------------------
# Runner Metronome App Schemas
# ---------------------------------------------------------------------

class RunnerProfile(BaseModel):
    """User preferences and personalization for cadence and pacing."""
    user_id: str = Field(..., description="External auth user id or email")
    display_name: Optional[str] = Field(None, description="Name to show in UI")
    preferred_unit: str = Field("min_per_km", description="min_per_km or min_per_mile")
    baseline_cadence: Optional[int] = Field(None, ge=120, le=210, description="User's natural cadence in spm")
    target_cadence: Optional[int] = Field(None, ge=120, le=210, description="Preferred target cadence in spm")
    run_type: Optional[str] = Field(None, description="easy, tempo, interval, long, recovery, sprint")

class Session(BaseModel):
    """A recorded metronome session/workout summary."""
    user_id: Optional[str] = Field(None, description="External auth user id or email")
    pace_value: float = Field(..., gt=0, description="Pace numeric value (e.g., 5.0 meaning 5:00)")
    pace_unit: str = Field("min_per_km", description="min_per_km or min_per_mile")
    run_type: str = Field("easy", description="easy, tempo, interval, long, recovery, sprint")
    target_bpm: int = Field(..., ge=120, le=220, description="Cadence in steps per minute")
    duration_seconds: int = Field(..., ge=1, description="How long the metronome ran")
    notes: Optional[str] = Field(None, description="Optional notes")

class ProEntitlement(BaseModel):
    """Represents Pro access for a user, typically granted after successful payment."""
    user_id: Optional[str] = Field(None, description="Your internal user identifier")
    email: Optional[str] = Field(None, description="Email used at checkout")
    pro_active: bool = Field(True, description="Whether Pro is active for this user")
    source: str = Field("stripe", description="Entitlement source, e.g. stripe")
    stripe_customer_id: Optional[str] = Field(None, description="Stripe customer id")
    stripe_checkout_session_id: Optional[str] = Field(None, description="Stripe checkout session id")
    stripe_payment_intent_id: Optional[str] = Field(None, description="Stripe payment intent id")

class AuthCode(BaseModel):
    """One-time verification code for passwordless sign-in."""
    email: str = Field(..., description="Email to verify")
    code: str = Field(..., description="One-time code as plain text (demo)")
    expires_in_minutes: int = Field(10, description="Validity window in minutes")

# Example schemas retained for reference (not used by app directly)
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")
