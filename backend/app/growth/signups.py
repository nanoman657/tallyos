"""
DETECT: who signed up, and which Google Ads campaign brought them in.

Every new-client sign-up (the public "join / book" page, or a webhook from an
external booking tool) lands here with whatever tracking it carried:

  * gclid       -- Google's click id, appended to the ad's landing URL by
                   auto-tagging. Matched against the click_view gclids pulled
                   during SENSE, this ties the person to the exact campaign.
  * utm_*       -- manual tagging fallback (utm_campaign = our campaign id/name).
  * neither     -- organic (walk-by, referral, Instagram...).

A gclid we haven't seen yet stays "pending" and is re-attributed on the next
SENSE pass once the click report catches up (Google reports clicks with a lag).
"""

from datetime import datetime
from typing import Optional

from ..db import Db


def _match_campaign(db: Db, gclid: Optional[str], utm_source: Optional[str],
                    utm_campaign: Optional[str]) -> tuple:
    if gclid:
        hit = db.one("SELECT campaign_id FROM ad_clicks WHERE gclid = %s", [gclid])
        if hit:
            return hit["campaign_id"], "gclid"
    if utm_campaign and (utm_source or "").lower() in ("google", "google_ads", "adwords", ""):
        hit = db.one(
            "SELECT id FROM ad_campaigns WHERE id::text = %s OR external_id = %s OR lower(name) = lower(%s)",
            [utm_campaign, utm_campaign, utm_campaign],
        )
        if hit:
            return hit["id"], "utm"
    if gclid:
        return None, "gclid_pending"
    return None, "organic"


def _find_or_create_client(db: Db, name: str, phone: Optional[str], email: Optional[str],
                           at: datetime, source: str, campaign_id: Optional[int]) -> dict:
    existing = None
    if phone:
        existing = db.one("SELECT * FROM clients WHERE phone = %s", [phone])
    if not existing and email:
        existing = db.one("SELECT * FROM clients WHERE lower(email) = lower(%s)", [email])
    if existing:
        return existing
    return db.insert("clients", {
        "name": name, "phone": phone, "email": email, "created_at": at,
        "source": source, "campaign_id": campaign_id,
    })


def record_signup(db: Db, *, name: str, phone: Optional[str] = None, email: Optional[str] = None,
                  gclid: Optional[str] = None, utm_source: Optional[str] = None,
                  utm_medium: Optional[str] = None, utm_campaign: Optional[str] = None,
                  at: Optional[datetime] = None) -> dict:
    at = at or datetime.now()
    campaign_id, attribution = _match_campaign(db, gclid, utm_source, utm_campaign)
    from_ads = attribution in ("gclid", "utm", "gclid_pending")
    client = _find_or_create_client(db, name, phone, email, at,
                                    "google_ads" if from_ads else "organic", campaign_id)
    return db.insert("signups", {
        "at": at, "name": name, "phone": phone, "email": email, "gclid": gclid,
        "utm_source": utm_source, "utm_medium": utm_medium, "utm_campaign": utm_campaign,
        "campaign_id": campaign_id, "attribution": attribution, "client_id": client["id"],
    })


def reattribute_pending(db: Db) -> int:
    """Resolve gclid sign-ups whose click wasn't in the click report yet."""
    rows = db.all(
        """UPDATE signups s SET campaign_id = c.campaign_id, attribution = 'gclid'
           FROM ad_clicks c
           WHERE s.gclid = c.gclid AND s.attribution = 'gclid_pending'
           RETURNING s.client_id, c.campaign_id""")
    for r in rows:
        db.execute("UPDATE clients SET campaign_id = %s WHERE id = %s AND campaign_id IS NULL",
                   [r["campaign_id"], r["client_id"]])
    return len(rows)


def link_first_appointments(db: Db) -> int:
    """A sign-up 'converts' when that client books their first appointment after signing up."""
    return db.execute(
        """UPDATE signups s SET first_appointment_id = a.id
           FROM LATERAL (
               SELECT id FROM appointments
               WHERE client_id = s.client_id AND created_at >= s.at - interval '1 hour'
                 AND status IN ('booked','completed')
               ORDER BY created_at LIMIT 1) a
           WHERE s.first_appointment_id IS NULL AND s.client_id IS NOT NULL""")
