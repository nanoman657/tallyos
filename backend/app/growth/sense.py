"""
SENSE: gather what happened since the last cycle.

  * Google Ads daily metrics (impressions, clicks, cost) per campaign
  * Google Ads click ids (gclids) -> lets sign-ups be tied to a campaign
  * Sign-ups: re-attribute pending gclids, link sign-ups to first bookings
  * Per-campaign funnel: clicks -> sign-ups -> booked first appointments
  * Lift: average daily sign-ups on days with ad spend vs. days without
"""

from datetime import date, timedelta
from typing import Dict, List

from ..ads.base import AdsPlatform
from ..config import GrowthConfig
from ..db import Db
from .signups import link_first_appointments, reattribute_pending


def _campaign_id_map(db: Db) -> Dict[str, int]:
    return {r["external_id"]: r["id"] for r in db.all("SELECT id, external_id FROM ad_campaigns WHERE external_id IS NOT NULL")}


def _ensure_campaign(db: Db, ids: Dict[str, int], external_id: str) -> int:
    """Campaigns created outside TallyOS still get tracked (but never managed by the loop)."""
    if external_id not in ids:
        row = db.insert("ad_campaigns", {
            "external_id": external_id, "name": f"External campaign {external_id}", "purpose": "external",
            "status": "ENABLED", "daily_budget": 0, "managed_by_loop": False,
        })
        ids[external_id] = row["id"]
    return ids[external_id]


def sync_platform(db: Db, platform: AdsPlatform, start: date, end: date) -> dict:
    ids = _campaign_id_map(db)
    metrics = platform.fetch_daily_metrics(start, end)
    for m in metrics:
        cid = _ensure_campaign(db, ids, m.external_id)
        db.execute(
            """INSERT INTO ad_metrics_daily (campaign_id, date, impressions, clicks, cost, platform_conversions)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (campaign_id, date) DO UPDATE SET impressions = EXCLUDED.impressions,
                 clicks = EXCLUDED.clicks, cost = EXCLUDED.cost, platform_conversions = EXCLUDED.platform_conversions""",
            [cid, m.date, m.impressions, m.clicks, round(m.cost, 2), m.conversions],
        )
    clicks = platform.fetch_clicks(start, end)
    for c in clicks:
        cid = _ensure_campaign(db, ids, c.external_id)
        db.execute("INSERT INTO ad_clicks (gclid, campaign_id, clicked_on) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                   [c.gclid, cid, c.date])
    return {"metric_rows": len(metrics), "clicks": len(clicks)}


def campaign_stats(db: Db, start: date, end: date) -> List[dict]:
    return db.all(
        """SELECT c.id AS campaign_id, c.name, c.status, c.daily_budget, c.managed_by_loop,
                  coalesce(m.impressions,0) AS impressions, coalesce(m.clicks,0) AS clicks,
                  coalesce(m.cost,0) AS cost, coalesce(s.signups,0) AS signups, coalesce(s.booked,0) AS booked
           FROM ad_campaigns c
           LEFT JOIN (SELECT campaign_id, sum(impressions) AS impressions, sum(clicks) AS clicks, sum(cost) AS cost
                      FROM ad_metrics_daily WHERE date >= %s AND date < %s GROUP BY 1) m ON m.campaign_id = c.id
           LEFT JOIN (SELECT campaign_id, count(*) AS signups, count(first_appointment_id) AS booked
                      FROM signups WHERE at >= %s AND at < %s AND campaign_id IS NOT NULL GROUP BY 1) s
                  ON s.campaign_id = c.id
           WHERE c.status <> 'REMOVED' OR m.clicks > 0
           ORDER BY c.id""",
        [start, end, start, end],
    )


def signup_summary(db: Db, start: date, end: date) -> dict:
    by_attr = db.all(
        """SELECT CASE WHEN attribution IN ('gclid','utm','gclid_pending') THEN 'google_ads' ELSE 'organic' END AS source,
                  count(*) AS signups, count(first_appointment_id) AS booked
           FROM signups WHERE at >= %s AND at < %s GROUP BY 1""",
        [start, end],
    )
    daily = db.all(
        """SELECT d::date AS date,
                  coalesce((SELECT sum(cost) FROM ad_metrics_daily WHERE date = d::date), 0) AS ad_cost,
                  (SELECT count(*) FROM signups WHERE at::date = d::date) AS signups,
                  (SELECT count(*) FROM signups WHERE at::date = d::date
                      AND attribution IN ('gclid','utm','gclid_pending')) AS ad_signups
           FROM generate_series(%s::date, %s::date - 1, interval '1 day') d ORDER BY 1""",
        [start, end],
    )
    on = [d["signups"] for d in daily if d["ad_cost"] > 0]
    off = [d["signups"] for d in daily if d["ad_cost"] == 0]
    totals = {r["source"]: r for r in by_attr}
    ads = totals.get("google_ads", {"signups": 0, "booked": 0})
    org = totals.get("organic", {"signups": 0, "booked": 0})
    lift = None
    if len(on) >= 3 and len(off) >= 3:
        lift = round(sum(on) / len(on) - sum(off) / len(off), 3)
    return {
        "window_start": start, "window_end": end,
        "google_ads_signups": ads["signups"], "google_ads_booked": ads["booked"],
        "organic_signups": org["signups"], "organic_booked": org["booked"],
        "pending_attribution": db.scalar(
            "SELECT count(*) FROM signups WHERE attribution = 'gclid_pending' AND at >= %s AND at < %s", [start, end]),
        "avg_daily_signups_with_ads": round(sum(on) / len(on), 3) if on else None,
        "avg_daily_signups_without_ads": round(sum(off) / len(off), 3) if off else None,
        "incremental_signups_per_ad_day": lift,
        "daily": daily,
    }


def sense(db: Db, platform: AdsPlatform, as_of: date, cfg: GrowthConfig) -> dict:
    start = as_of - timedelta(days=cfg.lookback_days)
    synced = sync_platform(db, platform, start, as_of - timedelta(days=1))
    reattributed = reattribute_pending(db)
    linked = link_first_appointments(db)
    return {
        "as_of": as_of, "window_start": start,
        "synced": synced, "reattributed_signups": reattributed, "newly_linked_bookings": linked,
        "campaigns": campaign_stats(db, start, as_of),
        "signups": signup_summary(db, start, as_of),
    }
