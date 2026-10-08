"""Growth-loop endpoints: forecast, run the loop, campaigns, sign-up detection, public join form."""

from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import erp
from ..ads import get_platform
from ..config import get_settings, shop_today
from ..db import Db, get_db
from ..growth import act
from ..growth.forecast import backtest, build_forecast
from ..growth.loop import run_cycle
from ..growth.sense import campaign_stats, signup_summary
from ..growth.signups import record_signup

router = APIRouter(prefix="/api")


@router.get("/growth/forecast")
def forecast(days: int = 14, as_of: Optional[date] = None, db: Db = Depends(get_db)):
    fc = build_forecast(db, as_of or shop_today(), days, include_clients=True)
    out = asdict(fc)
    out["clients"] = out["clients"][:40]
    out["backtest"] = backtest(db, as_of or shop_today(), days)
    return out


@router.post("/growth/run")
def run_loop(dry_run: bool = False, db: Db = Depends(get_db)):
    settings = get_settings()
    result = run_cycle(db, get_platform(db, settings), settings, dry_run=dry_run)
    return {"run_id": result["run_id"], "dry_run": dry_run, "think": result["think"], "act": result["act"]}


@router.get("/growth/runs")
def list_runs(limit: int = 30, db: Db = Depends(get_db)):
    return db.all("SELECT id, as_of, ran_at, dry_run, think, act FROM loop_runs ORDER BY id DESC LIMIT %s", [limit])


@router.get("/growth/runs/{run_id}")
def get_run(run_id: int, db: Db = Depends(get_db)):
    run = db.one("SELECT * FROM loop_runs WHERE id = %s", [run_id])
    if not run:
        raise HTTPException(404, "Run not found")
    run["forecast"] = db.all("SELECT * FROM forecasts WHERE run_id = %s ORDER BY date", [run_id])
    return run


@router.get("/growth/campaigns")
def campaigns(days: int = 28, db: Db = Depends(get_db)):
    today = shop_today()
    stats = {s["campaign_id"]: s for s in campaign_stats(db, today - timedelta(days=days), today + timedelta(days=1))}
    rows = db.all("SELECT * FROM ad_campaigns ORDER BY status = 'ENABLED' DESC, id DESC")
    for r in rows:
        s = stats.get(r["id"], {})
        r.update({k: s.get(k, 0) for k in ("impressions", "clicks", "cost", "signups", "booked")})
        r["cpa"] = round(r["cost"] / r["booked"], 2) if r["booked"] else None
        r["daily"] = db.all(
            """SELECT m.date, m.clicks, m.cost,
                      (SELECT count(*) FROM signups s WHERE s.campaign_id = m.campaign_id AND s.at::date = m.date) AS signups
               FROM ad_metrics_daily m WHERE m.campaign_id = %s AND m.date >= %s ORDER BY m.date""",
            [r["id"], today - timedelta(days=days)])
    return rows


class CampaignChange(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(ENABLED|PAUSED)$")
    daily_budget: Optional[float] = Field(default=None, gt=0)
    managed_by_loop: Optional[bool] = None


@router.patch("/growth/campaigns/{campaign_id}")
def change_campaign(campaign_id: int, body: CampaignChange, db: Db = Depends(get_db)):
    """Owner overrides: approve (enable) a campaign the loop created, pause it, set budget, or take it off autopilot."""
    settings = get_settings()
    c = db.one("SELECT * FROM ad_campaigns WHERE id = %s", [campaign_id])
    if not c or not c["external_id"]:
        raise HTTPException(404, "Campaign not found")
    platform = get_platform(db, settings)
    changes = {}
    if body.daily_budget is not None:
        other = act._enabled_loop_budget(db, campaign_id)
        if c["managed_by_loop"] and other + body.daily_budget > settings.growth.max_total_daily_budget:
            raise HTTPException(400, f"Would exceed the ${settings.growth.max_total_daily_budget:.0f}/day guardrail")
        platform.update_budget(c["external_id"], body.daily_budget)
        changes["daily_budget"] = body.daily_budget
    if body.status:
        platform.set_status(c["external_id"], body.status)
        changes["status"] = body.status
    if body.managed_by_loop is not None:
        changes["managed_by_loop"] = body.managed_by_loop
    return db.update("ad_campaigns", campaign_id, {**changes, "updated_at": shop_today()}) if changes else c


@router.get("/growth/signups")
def list_signups(days: int = 28, db: Db = Depends(get_db)):
    return db.all(
        """SELECT s.*, c.name AS campaign_name, a.start_at AS first_appointment_at
           FROM signups s LEFT JOIN ad_campaigns c ON c.id = s.campaign_id
           LEFT JOIN appointments a ON a.id = s.first_appointment_id
           WHERE s.at >= %s ORDER BY s.at DESC""", [shop_today() - timedelta(days=days)])


@router.get("/growth/signups/summary")
def signups_summary(days: int = 28, db: Db = Depends(get_db)):
    today = shop_today()
    return signup_summary(db, today - timedelta(days=days), today + timedelta(days=1))


# ------------------------------------------------------------------ public join / booking page
class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=40)
    email: Optional[str] = Field(default=None, max_length=200)
    gclid: Optional[str] = Field(default=None, max_length=200)
    utm_source: Optional[str] = Field(default=None, max_length=100)
    utm_medium: Optional[str] = Field(default=None, max_length=100)
    utm_campaign: Optional[str] = Field(default=None, max_length=200)


@router.post("/public/signup", status_code=201)
def public_signup(body: SignupIn, db: Db = Depends(get_db)):
    """The DETECT entry point: the landing page posts here with whatever ad tracking it saw in the URL."""
    if not (body.phone or body.email):
        raise HTTPException(400, "Phone or email is required")
    s = record_signup(db, **body.model_dump())
    return {"signup_id": s["id"], "client_id": s["client_id"], "attribution": s["attribution"]}


@router.get("/public/services")
def public_services(db: Db = Depends(get_db)):
    return db.all("SELECT id, name, price, duration_min FROM services WHERE active ORDER BY price")


@router.get("/public/availability")
def public_availability(day: date, service_id: int, db: Db = Depends(get_db)):
    return [{"start_at": s["start_at"], "staff_id": s["staff_id"]} for s in erp.availability(db, day, service_id)]


class PublicBookingIn(BaseModel):
    signup_id: int
    contact: str = Field(min_length=3, max_length=200)   # the phone or email used to sign up
    service_id: int
    start_at: datetime


@router.post("/public/book", status_code=201)
def public_book(body: PublicBookingIn, db: Db = Depends(get_db)):
    """First booking straight after signing up. Proving the sign-up's phone/email stands in for a login."""
    s = db.one("SELECT * FROM signups WHERE id = %s AND at >= now() - interval '7 days'", [body.signup_id])
    contact = body.contact.strip().lower()
    if not s or contact not in ((s["phone"] or "").lower(), (s["email"] or "").lower()):
        raise HTTPException(404, "Sign-up not found")
    if s["first_appointment_id"]:
        raise HTTPException(409, "You already have a booking - call the shop to change it")
    appt = erp.book_appointment(db, s["client_id"], body.service_id, body.start_at)
    db.update("signups", s["id"], {"first_appointment_id": appt["id"]})
    return {"appointment_id": appt["id"], "start_at": appt["start_at"]}
