"""
Stripe pass-through billing.

Vicky's customer (California Fruit, Inc.) has a payment method on file. Each
verified packet emits a usage record at cost (Anthropic vision OCR ~$0.04 per
average packet). We do NOT mark up — this is pass-through. The Stripe price
is configured as a metered price in the dashboard.

If STRIPE_ENABLED=false, billing is logged to the audit trail only.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from .config import SETTINGS
from .models import AuditLog, BillingEvent


def _stripe_client():
    import stripe       # type: ignore
    if not SETTINGS.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY not set")
    stripe.api_key = SETTINGS.stripe_secret_key
    return stripe


def report_usage(db: Session, billing_event_id: str,
                  customer_subscription_item: Optional[str] = None) -> None:
    """
    Push a Stripe usage record for one BillingEvent. Idempotent — re-runs no-op
    once stripe_usage_record_id is populated.
    """
    ev = db.get(BillingEvent, billing_event_id)
    if ev is None or ev.stripe_status == "succeeded":
        return

    if not SETTINGS.stripe_enabled:
        ev.stripe_status = "skipped"
        db.add(AuditLog(
            action="billing.skipped",
            target_type="billing_event", target_id=ev.id,
            details_json={"reason": "STRIPE_ENABLED=false",
                          "amount_cents": ev.cost_usd_cents,
                          "n_pages": ev.n_pages},
        ))
        db.commit(); return

    try:
        stripe = _stripe_client()
        # We bill in 1¢ "ticks": ev.cost_usd_cents is float cents at cost.
        # Stripe usage records take integer quantity, so we round up to ¢.
        qty = max(1, int(round(ev.cost_usd_cents)))
        if not customer_subscription_item:
            raise RuntimeError(
                "subscription_item_id required for usage_record creation")
        rec = stripe.SubscriptionItem.create_usage_record(
            customer_subscription_item,
            quantity=qty,
            timestamp="now",
            action="increment",
        )
        ev.stripe_usage_record_id = rec.id
        ev.stripe_status = "succeeded"
        ev.error_message = None
        db.add(AuditLog(
            action="billing.recorded",
            target_type="billing_event", target_id=ev.id,
            details_json={"qty_cents": qty, "stripe_id": rec.id},
        ))
    except Exception as e:
        ev.stripe_status = "failed"
        ev.error_message = str(e)
        db.add(AuditLog(action="billing.error", target_type="billing_event",
                        target_id=ev.id, details_json={"error": str(e)}))
    db.commit()
