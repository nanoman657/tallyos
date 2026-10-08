"""
ACT: carry out THINK's decisions on Google Ads, and close the loop by
uploading offline conversions (ad sign-ups that booked a first cut) so
Google's bidding optimizes for real clients, not just clicks.

Safety rails
  * Total daily budget across loop-managed campaigns never exceeds
    GrowthConfig.max_total_daily_budget.
  * On a live Google Ads account (ads_backend="google") new or re-enabled
    campaigns are left PAUSED for the owner to approve in the app, unless
    TALLYOS_ADS_AUTO_ENABLE=true.
  * dry_run executes nothing -- it only reports what would happen.
"""

from datetime import datetime
from typing import List, Optional
from urllib.parse import urlencode

from ..ads.base import AdsPlatform, CampaignSpec, OfflineConversion
from ..config import Settings
from ..db import Db
from .think import WEEKDAY_NAMES, Decision

BASE_KEYWORDS = ["barber near me", "barbershop near me", "mens haircut near me",
                 "fade haircut near me", "beard trim near me"]


def _days_phrase(weekdays: List[int]) -> str:
    if not weekdays or len(weekdays) >= 6:
        return "This Week"
    names = [WEEKDAY_NAMES[w] for w in sorted(weekdays)]
    return " & ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + " & " + names[-1]


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def generate_ad_copy(db: Db, weekdays: List[int]) -> dict:
    """Responsive search ad assets built from the live service menu and the gap days."""
    shop = db.one("SELECT name FROM shop WHERE id = 1")
    services = db.all("SELECT name, price FROM services WHERE active ORDER BY price")
    days = _days_phrase(weekdays)
    cheapest = services[0] if services else {"name": "Haircut", "price": 35}
    headlines = [
        _fit(shop["name"], 30),
        _fit(f"Open Chairs {days}", 30),
        _fit(f"{cheapest['name']} ${cheapest['price']:.0f}", 30),
        "Book Online In 30 Seconds",
        "Top-Rated Local Barber",
    ]
    headlines += [_fit(f"{s['name']} ${s['price']:.0f}", 30) for s in services[1:4]]
    descriptions = [
        _fit(f"Appointments open {days.lower() if days == 'This Week' else 'on ' + days}. "
             f"Pick your barber and time online.", 90),
        _fit(f"{len(services)} services from ${cheapest['price']:.0f}. New clients welcome - "
             f"book your first cut today.", 90),
    ]
    keywords = BASE_KEYWORDS + [f"{s['name'].lower()} near me" for s in services[:3]]
    return {"headlines": list(dict.fromkeys(headlines))[:15], "descriptions": descriptions,
            "keywords": list(dict.fromkeys(keywords))}


def _landing_url(settings: Settings, campaign_id: int) -> str:
    sep = "&" if "?" in settings.booking_url else "?"
    # gclid is appended automatically by Google auto-tagging; UTMs are the fallback.
    return settings.booking_url + sep + urlencode(
        {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": str(campaign_id)})


def _enabled_loop_budget(db: Db, exclude_id: Optional[int] = None) -> float:
    return float(db.scalar(
        "SELECT coalesce(sum(daily_budget),0) FROM ad_campaigns WHERE managed_by_loop AND status = 'ENABLED' AND id <> %s",
        [exclude_id or 0]) or 0.0)


def _clamp_budget(db: Db, settings: Settings, budget: float, campaign_id: Optional[int] = None) -> float:
    headroom = settings.growth.max_total_daily_budget - _enabled_loop_budget(db, campaign_id)
    return round(max(0.0, min(budget, headroom)), 2)


def execute(db: Db, platform: AdsPlatform, decisions: List[Decision], settings: Settings,
            as_of: datetime, dry_run: bool = False) -> List[dict]:
    live_needs_approval = settings.ads_backend == "google" and not settings.ads_auto_enable
    results = []
    for d in decisions:
        result = {"action": d.action, "reason": d.reason, "campaign_id": d.campaign_id, "executed": False}
        try:
            if d.action == "hold":
                result["executed"] = True
            elif dry_run:
                result.update(daily_budget=d.daily_budget, target_weekdays=d.target_weekdays, note="dry run")
            elif d.action == "create":
                result.update(_create(db, platform, d, settings, as_of, live_needs_approval))
            else:
                result.update(_modify(db, platform, d, settings, as_of, live_needs_approval))
        except Exception as exc:   # one failed API call must not abort the rest of the cycle
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    if not dry_run:
        results.append(upload_conversions(db, platform))
    return results


def _create(db: Db, platform: AdsPlatform, d: Decision, settings: Settings, now: datetime,
            needs_approval: bool) -> dict:
    budget = _clamp_budget(db, settings, d.daily_budget or settings.growth.min_campaign_daily_budget)
    if budget < settings.growth.min_campaign_daily_budget:
        return {"note": "skipped: total daily budget guardrail reached"}
    copy = generate_ad_copy(db, d.target_weekdays or [])
    status = "PAUSED" if needs_approval else "ENABLED"
    name = f"TallyOS fill {_days_phrase(d.target_weekdays or [])} {now:%Y-%m-%d}"
    row = db.insert("ad_campaigns", {
        "name": name, "purpose": "fill_capacity", "status": status, "daily_budget": budget,
        "target_weekdays": d.target_weekdays or [], "created_at": now, "updated_at": now, **copy,
    })
    external_id = platform.create_campaign(CampaignSpec(
        name=name, daily_budget=budget, target_weekdays=d.target_weekdays or [], final_url=_landing_url(settings, row["id"]),
        latitude=settings.shop_latitude, longitude=settings.shop_longitude, radius_miles=settings.ad_radius_miles,
        enabled=status == "ENABLED", **copy,
    ))
    db.update("ad_campaigns", row["id"], {"external_id": external_id})
    return {"executed": True, "campaign_id": row["id"], "external_id": external_id, "daily_budget": budget,
            "status": status, "headlines": copy["headlines"][:3],
            **({"note": "created PAUSED - approve it in Growth > Campaigns"} if needs_approval else {})}


def _modify(db: Db, platform: AdsPlatform, d: Decision, settings: Settings, now: datetime,
            needs_approval: bool) -> dict:
    c = db.one("SELECT * FROM ad_campaigns WHERE id = %s", [d.campaign_id])
    if not c or not c["external_id"]:
        return {"error": "campaign not found on the ad platform"}
    changes, out = {}, {}
    if d.action == "pause":
        platform.set_status(c["external_id"], "PAUSED")
        changes["status"] = "PAUSED"
    if d.daily_budget is not None:
        budget = _clamp_budget(db, settings, d.daily_budget, c["id"])
        if budget >= settings.growth.min_campaign_daily_budget and budget != c["daily_budget"]:
            platform.update_budget(c["external_id"], budget)
            changes["daily_budget"] = budget
            out["daily_budget"] = budget
    if d.target_weekdays is not None and sorted(d.target_weekdays) != sorted(c["target_weekdays"]):
        platform.update_schedule(c["external_id"], d.target_weekdays)
        changes["target_weekdays"] = d.target_weekdays
    if d.action == "enable":
        if needs_approval:
            out["note"] = "budget/schedule updated; left PAUSED for owner approval"
        else:
            platform.set_status(c["external_id"], "ENABLED")
            changes["status"] = "ENABLED"
    if changes:
        changes["updated_at"] = now
        db.update("ad_campaigns", c["id"], changes)
    return {"executed": bool(changes), **out, **({"status": changes["status"]} if "status" in changes else {})}


def upload_conversions(db: Db, platform: AdsPlatform) -> dict:
    """Report ad sign-ups that booked a first appointment back to Google Ads."""
    rows = db.all(
        """SELECT s.id, s.gclid, s.at, a.price FROM signups s JOIN appointments a ON a.id = s.first_appointment_id
           WHERE s.gclid IS NOT NULL AND s.attribution = 'gclid' AND NOT s.conversion_uploaded""")
    if not rows:
        return {"action": "upload_conversions", "executed": True, "uploaded": 0}
    result = platform.upload_conversions([OfflineConversion(gclid=r["gclid"], at=r["at"], value=r["price"]) for r in rows])
    failed = set(result.failed)
    ok_ids = [r["id"] for r in rows if r["gclid"] not in failed]
    if ok_ids:
        db.execute("UPDATE signups SET conversion_uploaded = TRUE WHERE id = ANY(%s)", [ok_ids])
    return {"action": "upload_conversions", "executed": True, "uploaded": result.uploaded, "failed": len(failed),
            "reason": "feed booked sign-ups back to Google so bidding optimizes for real clients"}
