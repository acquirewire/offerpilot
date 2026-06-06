"""Stripe payments for OfferPilot (self-serve upgrade to Pro).

Uses Stripe Checkout + verify-on-redirect (no webhook server needed), which is
enough for a small launch: the user pays on Stripe, gets redirected back with a
session id, and we confirm payment via the Stripe API and flip them to Pro.

Needs two env vars (Stripe dashboard -> Developers -> API keys / a recurring Price):
  STRIPE_SECRET_KEY   sk_test_... (or sk_live_...)
  STRIPE_PRICE_ID     price_...   (your Pro subscription price)

Everything degrades gracefully: if Stripe isn't configured, configured() is
False and the app simply hides the pay button (admin can still upgrade users
for free). No webhook = a rare edge case if a user closes the tab mid-redirect;
the admin toggle is the backstop.
"""
from __future__ import annotations

import os


def configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY") and os.environ.get("STRIPE_PRICE_ID"))


def _stripe():
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def create_checkout_url(email: str, base_url: str) -> str | None:
    """Create a Stripe Checkout session and return its URL (or None if unconfigured)."""
    if not configured():
        return None
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        customer_email=email,
        success_url=f"{base_url}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=base_url,
        metadata={"email": email},
        allow_promotion_codes=True,
    )
    return session.url


def verify_session(session_id: str) -> tuple[bool, str | None]:
    """Return (paid, email) for a completed Checkout session."""
    if not configured():
        return False, None
    try:
        stripe = _stripe()
        s = stripe.checkout.Session.retrieve(session_id)
        email = (s.get("metadata") or {}).get("email") or s.get("customer_email")
        return (s.get("payment_status") == "paid", email)
    except Exception:
        return False, None
