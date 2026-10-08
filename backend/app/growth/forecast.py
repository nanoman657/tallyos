"""
THINK, part 1: predict booking frequency.

Expected bookings on a future day d are built bottom-up:

    expected(d) = already_booked(d)
                + sum over clients with no future booking of P(client books on d)
                + expected organic new clients(d)

Per-client model
  Each client's rebooking interval ~ Normal(mu_c, sd_c), where mu_c/sd_c are
  the client's own mean/std of days between visits, shrunk toward the shop-wide
  values (so a client with one visit inherits the shop average). Given the days
  since their last visit, the chance they come back on day d is the normal
  probability mass on d conditioned on "hasn't come back yet", times a
  survival term that decays once they're overdue (lapsing clients). That mass
  is then reshaped by the client's own weekday habits (smoothed toward the
  shop's weekday profile), and closed days get zero.

Organic new clients
  Mean daily first-visits not attributed to ads over the lookback window,
  spread by the shop weekday profile.

`backtest` re-runs the forecast as of an earlier date using only data known
then, and scores it against what actually happened, next to a seasonal-naive
baseline (same weekday last week), so the owner can see how much to trust it.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import numpy as np

from ..db import Db
from .. import erp

SHRINK_VISITS = 2.0           # pseudo-visits of shop-level prior in each client's interval estimate
MIN_SD_DAYS = 3.0
LAPSE_GRACE_SD = 1.5          # overdue = more than mu + 1.5 sd since last visit
LAPSE_HALF_LIFE_DAYS = 21.0   # survival halves every 3 weeks overdue
WEEKDAY_PRIOR_WEIGHT = 3.0    # Dirichlet pseudo-counts toward the shop weekday profile
HISTORY_DAYS = 365


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class ClientOutlook:
    client_id: int
    name: str
    visits: int
    last_visit: Optional[date]
    mean_interval: float
    next_visit_expected: Optional[date]
    p_active: float
    p_within_horizon: float
    next_booked: Optional[datetime] = None
    status: str = "due"   # booked | due | overdue | lapsed | new


@dataclass
class Forecast:
    as_of: date
    days: List[dict]                       # [{date, weekday, expected_bookings, already_booked, from_regulars, organic_new, capacity_slots, gap_slots, utilization}]
    shop_mean_interval: float
    shop_sd_interval: float
    weekday_profile: List[float]
    organic_new_per_day: float
    clients: List[ClientOutlook] = field(default_factory=list)


def _visit_history(db: Db, as_of: date) -> Dict[int, List[dict]]:
    rows = db.all(
        """SELECT a.client_id, a.start_at, c.name FROM appointments a JOIN clients c ON c.id = a.client_id
           WHERE a.status IN ('completed','booked') AND a.start_at < %s AND a.start_at >= %s
             AND a.created_at < %s
           ORDER BY a.client_id, a.start_at""",
        [as_of, as_of - timedelta(days=HISTORY_DAYS), as_of],
    )
    hist: Dict[int, List[dict]] = defaultdict(list)
    for r in rows:
        hist[r["client_id"]].append(r)
    return hist


def _shop_weekday_profile(db: Db, shop: dict, as_of: date, lookback_days: int = 84) -> List[float]:
    rows = db.all(
        """SELECT extract(isodow FROM start_at)::int - 1 AS wd, count(*) AS n FROM appointments
           WHERE status IN ('completed','booked') AND start_at >= %s AND start_at < %s
           GROUP BY 1""",
        [as_of - timedelta(days=lookback_days), as_of],
    )
    counts = [1.0 if wd in shop["open_weekdays"] else 0.0 for wd in range(7)]   # Laplace smoothing on open days
    for r in rows:
        counts[r["wd"]] += r["n"]
    total = sum(counts) or 1.0
    return [c / total for c in counts]


def _interval_stats(visits: List[date]) -> List[float]:
    return [(b - a).days for a, b in zip(visits, visits[1:]) if (b - a).days > 0]


def build_forecast(db: Db, as_of: date, horizon_days: int = 14, include_clients: bool = False,
                   lookback_days: int = 28) -> Forecast:
    shop = erp.get_shop(db)
    barbers = erp.active_barber_count(db)
    avg_minutes = erp.avg_service_minutes(db, as_of)
    horizon = [as_of + timedelta(days=i) for i in range(horizon_days)]
    profile = _shop_weekday_profile(db, shop, as_of)

    hist = _visit_history(db, as_of)
    all_intervals = [iv for visits in hist.values() for iv in _interval_stats([v["start_at"].date() for v in visits])]
    shop_mu = float(np.median(all_intervals)) if len(all_intervals) >= 10 else 28.0
    shop_sd = max(MIN_SD_DAYS, float(np.std(all_intervals))) if len(all_intervals) >= 10 else 6.0

    # Appointments already on the books (as known at as_of) inside the horizon.
    future = db.all(
        """SELECT client_id, start_at FROM appointments
           WHERE status = 'booked' AND start_at >= %s AND start_at < %s AND created_at < %s""",
        [as_of, as_of + timedelta(days=horizon_days + 60), as_of],
    )
    already_by_day: Dict[date, int] = defaultdict(int)
    next_booked: Dict[int, datetime] = {}
    for f in future:
        if f["start_at"].date() < horizon[-1] + timedelta(days=1):
            already_by_day[f["start_at"].date()] += 1
        if f["client_id"] not in next_booked or f["start_at"] < next_booked[f["client_id"]]:
            next_booked[f["client_id"]] = f["start_at"]

    from_regulars = np.zeros(horizon_days)
    outlooks: List[ClientOutlook] = []
    for client_id, visits in hist.items():
        dates = [v["start_at"].date() for v in visits]
        last = dates[-1]
        ivs = _interval_stats(dates)
        n = len(ivs)
        mu = (sum(ivs) + SHRINK_VISITS * shop_mu) / (n + SHRINK_VISITS)
        if n >= 2:
            sd = math.sqrt((np.var(ivs) * n + SHRINK_VISITS * shop_sd ** 2) / (n + SHRINK_VISITS))
        else:
            sd = shop_sd
        sd = max(MIN_SD_DAYS, sd)
        since = (as_of - last).days
        overdue = max(0.0, since - (mu + LAPSE_GRACE_SD * sd))
        p_active = 0.5 ** (overdue / LAPSE_HALF_LIFE_DAYS)

        outlook = ClientOutlook(
            client_id=client_id, name=visits[-1]["name"], visits=len(dates), last_visit=last,
            mean_interval=round(mu, 1), next_visit_expected=last + timedelta(days=round(mu)),
            p_active=round(p_active, 3), p_within_horizon=0.0, next_booked=next_booked.get(client_id),
        )
        if client_id in next_booked:
            outlook.status, outlook.p_within_horizon = "booked", 1.0
            outlooks.append(outlook)
            continue

        # Conditional probability mass of the return visit on each horizon day.
        z0 = (since - 0.5 - mu) / sd
        survive = max(1.0 - _phi(z0), 1e-3)
        raw = np.array([
            (_phi((since + i + 0.5 - mu) / sd) - _phi((since + i - 0.5 - mu) / sd)) / survive
            for i in range(horizon_days)
        ])
        # Overdue clients whose normal tail is exhausted: spread residual intent evenly.
        if raw.sum() < 0.5 and overdue > 0:
            raw = np.full(horizon_days, 1.0 / 30.0)
        mass = min(1.0, raw.sum())

        # Weekday habits, Dirichlet-smoothed toward the shop profile; closed days -> 0.
        wd_counts = np.zeros(7)
        for d in dates:
            wd_counts[d.weekday()] += 1
        wd_pref = (wd_counts + WEEKDAY_PRIOR_WEIGHT * 7 * np.array(profile)) / (len(dates) + WEEKDAY_PRIOR_WEIGHT * 7)
        weights = np.array([wd_pref[d.weekday()] * (1.0 if erp.is_open(shop, d) else 0.0) for d in horizon])
        shaped = raw * weights
        if shaped.sum() > 0:
            shaped = shaped / shaped.sum() * mass
        contribution = shaped * p_active
        from_regulars += contribution

        outlook.p_within_horizon = round(float(contribution.sum()), 3)
        outlook.status = "lapsed" if p_active < 0.25 else "overdue" if overdue > 0 else "due"
        outlooks.append(outlook)

    # Organic (non-ad) new clients per day over the lookback window.
    organic_first_visits = db.scalar(
        """SELECT count(*) FROM clients c
           WHERE c.source <> 'google_ads' AND c.created_at >= %s AND c.created_at < %s
             AND EXISTS (SELECT 1 FROM appointments a WHERE a.client_id = c.id AND a.status IN ('booked','completed'))""",
        [as_of - timedelta(days=lookback_days), as_of],
    ) or 0
    organic_per_day = organic_first_visits / lookback_days
    open_share = sum(profile)  # == 1; profile only has mass on open days

    days = []
    for i, d in enumerate(horizon):
        cap = erp.capacity_slots(db, shop, d, avg_minutes, barbers)
        organic = organic_per_day * 7 * profile[d.weekday()] / open_share if cap else 0.0
        expected = already_by_day[d] + from_regulars[i] + organic
        expected = min(expected, cap) if cap else 0.0
        days.append({
            "date": d, "weekday": d.weekday(),
            "expected_bookings": round(float(expected), 2),
            "already_booked": already_by_day[d],
            "from_regulars": round(float(from_regulars[i]), 2),
            "organic_new": round(organic, 2),
            "capacity_slots": round(cap, 2),
            "utilization": round(expected / cap, 3) if cap else None,
        })

    return Forecast(
        as_of=as_of, days=days, shop_mean_interval=round(shop_mu, 1), shop_sd_interval=round(shop_sd, 1),
        weekday_profile=[round(p, 3) for p in profile], organic_new_per_day=round(organic_per_day, 3),
        clients=sorted(outlooks, key=lambda o: -o.p_within_horizon) if include_clients else [],
    )


def actual_bookings(db: Db, start: date, end: date) -> Dict[date, int]:
    rows = db.all(
        """SELECT start_at::date AS d, count(*) AS n FROM appointments
           WHERE status IN ('completed','booked','no_show') AND start_at >= %s AND start_at < %s GROUP BY 1""",
        [start, end],
    )
    return {r["d"]: r["n"] for r in rows}


def backtest(db: Db, as_of: date, horizon_days: int = 14) -> dict:
    """Forecast as of (as_of - horizon) and score it against what actually happened."""
    origin = as_of - timedelta(days=horizon_days)
    fc = build_forecast(db, origin, horizon_days)
    actual = actual_bookings(db, origin - timedelta(days=7), as_of)
    errors, naive_errors, rows = [], [], []
    for day in fc.days:
        if not day["capacity_slots"]:
            continue
        a = actual.get(day["date"], 0)
        naive = actual.get(day["date"] - timedelta(days=7), 0)
        errors.append(abs(day["expected_bookings"] - a))
        naive_errors.append(abs(naive - a))
        rows.append({"date": day["date"], "forecast": day["expected_bookings"], "actual": a, "seasonal_naive": naive})
    total_actual = sum(r["actual"] for r in rows) or 1
    return {
        "origin": origin, "days": rows,
        "mae": round(float(np.mean(errors)), 2) if errors else None,
        "wape": round(sum(errors) / total_actual, 3) if errors else None,
        "naive_mae": round(float(np.mean(naive_errors)), 2) if naive_errors else None,
    }
