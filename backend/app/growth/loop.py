"""
The sense -> think -> act cycle, persisted as an auditable loop_runs row.

    SENSE  sync Google Ads metrics + gclids, attribute sign-ups, measure lift
    THINK  forecast booking frequency, size the capacity gap, price a new
           client, decide campaign changes
    ACT    create / scale / reschedule / pause campaigns, upload conversions
    (next cycle's SENSE detects the sign-ups those actions produced)
"""

from dataclasses import asdict
from datetime import date, datetime, time
from typing import Optional

from ..ads.base import AdsPlatform
from ..config import Settings
from ..db import Db
from . import act, think
from .forecast import backtest, build_forecast
from .sense import sense


def run_cycle(db: Db, platform: AdsPlatform, settings: Settings, as_of: Optional[date] = None,
              dry_run: bool = False) -> dict:
    as_of = as_of or date.today()
    cfg = settings.growth
    if hasattr(platform, "set_today"):
        platform.set_today(as_of)

    # SENSE
    sensed = sense(db, platform, as_of, cfg)

    # THINK
    fc = build_forecast(db, as_of, cfg.forecast_horizon_days, lookback_days=cfg.lookback_days)
    econ = think.economics(db, as_of, fc, cfg)
    efficiency = think.campaign_efficiency(sensed["campaigns"], cfg)
    gap = think.capacity_gap(fc, cfg)
    campaigns = db.all("SELECT * FROM ad_campaigns ORDER BY id")
    clicks = {c["campaign_id"]: c["clicks"] for c in sensed["campaigns"]}
    for c in campaigns:
        c["clicks"] = clicks.get(c["id"], 0)
    plan, decisions = think.decide(campaigns, efficiency, econ, gap, cfg)
    thought = {
        "economics": econ, "gap": gap, "plan": plan,
        "efficiency": {str(k): v for k, v in efficiency.items()},
        "forecast_summary": {
            "shop_mean_interval_days": fc.shop_mean_interval,
            "organic_new_per_day": fc.organic_new_per_day,
            "expected_next_7": round(sum(d["expected_bookings"] for d in fc.days[:7]), 1),
            "capacity_next_7": round(sum(d["capacity_slots"] for d in fc.days[:7]), 1),
        },
        "backtest": {k: v for k, v in backtest(db, as_of, cfg.forecast_horizon_days).items() if k != "days"},
        "decisions": think.as_dicts(decisions),
    }

    # ACT
    acted = act.execute(db, platform, decisions, settings, datetime.combine(as_of, time(6, 0)), dry_run)

    run = db.insert("loop_runs", {"as_of": as_of, "dry_run": dry_run, "sense": _jsonable(sensed),
                                  "think": _jsonable(thought), "act": _jsonable(acted)})
    for d in fc.days:
        db.execute(
            """INSERT INTO forecasts (run_id, date, expected_bookings, already_booked, capacity_slots, gap_slots)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            [run["id"], d["date"], d["expected_bookings"], d["already_booked"], d["capacity_slots"], d["gap_slots"]],
        )
    return {"run_id": run["id"], "as_of": as_of, "dry_run": dry_run, "sense": sensed, "think": thought,
            "act": acted, "forecast": fc.days}


def _jsonable(obj):
    """JSONB-safe copy (dates/datetimes -> ISO strings, dataclasses -> dicts)."""
    if hasattr(obj, "__dataclass_fields__"):
        obj = asdict(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
