Runner Metronome Backend — Setup Guide (DB + Stripe)

Overview
This service powers auth, Pro access, metronome session logging, pace→BPM conversion, and Stripe payments. It supports two storage modes:
- Production: MongoDB (persistent)
- Development: In-memory fallback when explicitly allowed

What’s configured now
- Passwordless sign-in with one-time codes
- Pro entitlement via Stripe Checkout + webhook
- JWT minting for Pro access
- Session caps: 5 for Free, 50 for Pro
- Webhook verification when a secret is provided

Environment variables
Backend
- DATABASE_URL: MongoDB connection string (e.g., mongodb+srv://...)
- DATABASE_NAME: Database name (e.g., runner_metronome)
- DEV_ALLOW_MEMORY: Set to 1 only for local/dev to use in-memory fallback; unset/0 in production
- JWT_SECRET: Strong random string for HS256
- JWT_ISSUER: e.g., runner-metronome
- JWT_AUDIENCE: e.g., runner-metronome-app
- JWT_EXP_HOURS: e.g., 720 (30 days)
- STRIPE_API_KEY: Your Stripe secret key (e.g., sk_test_...)
- STRIPE_PRICE_ID: Price ID for one-time Pro (e.g., price_123)
- STRIPE_SUCCESS_URL: Where to send users after purchase (frontend URL)
- STRIPE_CANCEL_URL: Where to send users if they cancel checkout
- STRIPE_WEBHOOK_SECRET: Your endpoint’s signing secret (from Stripe dashboard or CLI)
- DEBUG_AUTH_CODES: 1 only in dev to return magic codes in API responses

Frontend
- VITE_BACKEND_URL: Base URL of this service (e.g., https://your-backend.host)
- VITE_PRO_CHECKOUT_URL: Static Payment Link used as fallback if dynamic checkout is unavailable

Production checklist
1) Database (persistent storage)
   - Set DATABASE_URL and DATABASE_NAME.
   - Ensure DEV_ALLOW_MEMORY is not set or set to 0.
   - Verify at /test → should show Connected & Working and list collections as they are created.

2) Stripe (payments + webhook)
   - Set STRIPE_API_KEY and STRIPE_PRICE_ID.
   - Set STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL to your frontend.
   - Configure the webhook endpoint to POST /api/stripe/webhook.
   - Copy the signing secret into STRIPE_WEBHOOK_SECRET.
   - Test in dev using the Stripe CLI (example):
     stripe listen --forward-to http://localhost:8000/api/stripe/webhook
     # Use the printed signing secret as STRIPE_WEBHOOK_SECRET

3) JWT (Pro entitlement)
   - Set a strong JWT_SECRET.
   - Keep JWT_ISSUER and JWT_AUDIENCE consistent across backend and frontend verification paths.

4) Frontend integration
   - On app launch, if a pro token exists locally, call /api/pro/verify and set the Pro flag accordingly.
   - Use Authorization: Bearer <token> for endpoints like /api/sessions to unlock Pro caps.
   - Provide both dynamic checkout (call /api/checkout/create) and Payment Link fallback.

Operational notes
- Webhook behavior
  • If STRIPE_WEBHOOK_SECRET is set, signatures are verified and invalid requests are rejected.
  • If not set (dev mode), raw JSON events are accepted to simplify local testing.

- Entitlements
  • Webhook stores an entitlement record for the buyer’s email/customer.
  • Users claim Pro via /api/pro/claim { email, user_id? } → returns { pro, token }.
  • /api/auth/verify-code also returns a token immediately if the email already has an entitlement.

- Sessions
  • GET /api/sessions?user_id=... respects JWT-based caps (5 free, 50 pro).
  • POST /api/sessions stores session data for the user.

Quick verification
- Visit /test
  • Database: shows whether MongoDB is connected.
  • Stripe: shows whether keys are present.
  • JWT: shows configured issuer/audience/expiry hours.

Troubleshooting
- Cannot connect to database: ensure both DATABASE_URL and DATABASE_NAME are set and reachable from the deployment environment.
- Dynamic checkout failing: check STRIPE_API_KEY and STRIPE_PRICE_ID; see API error details.
- Webhook invalid signature: confirm STRIPE_WEBHOOK_SECRET matches your Stripe endpoint or CLI output.
- Token rejected: ensure frontend and backend agree on JWT_ISSUER/AUDIENCE and token is not expired.

Security guidance
- Never expose STRIPE_API_KEY or JWT_SECRET to the frontend.
- Use real email delivery for auth codes in production; DEBUG_AUTH_CODES must be disabled.
- Rate limit auth endpoints and webhook endpoint.

