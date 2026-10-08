"""
THINK, part 2: turn the booking forecast + ad results into campaign decisions.

1. Economics -- what is a new client worth?  LTV = contribution margin per
   visit x expected visits in `ltv_months` x the share of new clients who
   come back (measured from the client book). The most we will pay to win a
   booked new client is `max_cpa_fraction_of_ltv` of that.

2. Ad efficiency -- what does a booked new client cost through Google Ads?
   Per campaign: CPC from spend/clicks, click->sign-up rate from a Beta
   posterior (prior + observed attributed sign-ups), sign-up->booking rate
   from observed first appointments. CPA = CPC / (cvr x booking rate).
   An optimistic CPA (90th-percentile cvr) is used for "is this campaign
   hopeless?" so a campaign isn't killed by a few unlucky days. With no
   judged campaign yet, the optimistic prior CPA is used so the loop explores
   (capped at half the guardrail budget) instead of never trying.

3. Gap -- open chair slots the forecast says won't fill on their own:
   gap(d) = max(0, target_utilization x capacity(d) - expected(d)).
   Required daily budget = (gap slots over the next 7 days / 7) x CPA,
   capped by the guardrail budget.

4. Decisions (each with a human-readable reason):
   - CREATE a campaign aimed at the weekdays with gaps if none is running,
   - ENABLE a paused campaign that still has acceptable CPA,
   - SCALE budgets toward the requirement (bounded step up / step down),
   - RESCHEDULE when the gap weekdays move,
   - PAUSE campaigns whose optimistic CPA still exceeds the ceiling, or
     when the book is already full.
"""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np

from ..config import GrowthConfig
from ..db import Db
from .forecast import Forecast

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GAP_WEEKDAY_THRESHOLD = 0.10       # a weekday "has a gap" if >10% of its target slots are unfilled
GAP_WEEKDAY_KEEP_THRESHOLD = 0.05  # hysteresis: a day already in the ad schedule stays until <5%
NEW_CLIENT_RETURN_PRIOR = 0.5
EXPLORE_BUDGET_SHARE = 0.5         # while exploring, spend at most half the guardrail budget
NEW_CLIENT_RETURN_PRIOR_WEIGHT = 10.0


@dataclass
class Decision:
    action: str                      # create | enable | scale | reschedule | pause | hold
    reason: str
    campaign_id: Optional[int] = None
    daily_budget: Optional[float] = None
    target_weekdays: Optional[List[int]] = None


def optimistic_prior_cpa(cfg: GrowthConfig) -> float:
    """CPA at the 90th-percentile click->sign-up rate of the prior (no campaign data yet)."""
    rng = np.random.default_rng(7)
    cvr_p90 = float(np.quantile(rng.beta(cfg.cvr_prior_alpha, cfg.cvr_prior_beta, 4000), 0.9))
    return cfg.default_cpc / (cvr_p90 * cfg.signup_to_booking_rate)


def economics(db: Db, as_of: date, forecast: Forecast, cfg: GrowthConfig) -> dict:
    shop = db.one("SELECT * FROM shop WHERE id = 1")
    t = db.one(
        """SELECT avg(a.price) AS ticket, avg(s.cogs) AS cogs, avg(st.commission_rate) AS commission
           FROM appointments a JOIN services s ON s.id = a.service_id JOIN staff st ON st.id = a.staff_id
           WHERE a.status = 'completed' AND a.start_at >= %s AND a.start_at < %s""",
        [as_of - timedelta(days=90), as_of],
    )
    ticket = t["ticket"] or db.scalar("SELECT avg(price) FROM services WHERE active") or 35.0
    margin = ticket * (1 - shop["card_fee_rate"] - (t["commission"] or 0.0)) - (t["cogs"] or 0.0)

    # Share of new clients (joined 60-365 days ago and visited at least once) who came back.
    r = db.one(
        """SELECT count(*) AS n, count(*) FILTER (WHERE v.visits >= 2) AS returned
           FROM clients c JOIN (SELECT client_id, count(*) AS visits FROM appointments
                                WHERE status = 'completed' AND start_at < %s GROUP BY client_id) v
                ON v.client_id = c.id
           WHERE c.created_at < %s AND c.created_at >= %s""",
        [as_of, as_of - timedelta(days=60), as_of - timedelta(days=365)],
    )
    return_rate = ((r["returned"] + NEW_CLIENT_RETURN_PRIOR * NEW_CLIENT_RETURN_PRIOR_WEIGHT)
                   / (r["n"] + NEW_CLIENT_RETURN_PRIOR_WEIGHT))
    visits_in_horizon = cfg.ltv_months * 30.4 / max(forecast.shop_mean_interval, 7.0)
    # First visit is certain; the rest happen only if the client sticks.
    expected_visits = 1 + return_rate * max(0.0, visits_in_horizon - 1)
    ltv = margin * expected_visits
    return {
        "avg_ticket": round(ticket, 2), "margin_per_visit": round(margin, 2),
        "new_client_return_rate": round(return_rate, 3), "expected_visits": round(expected_visits, 2),
        "ltv": round(ltv, 2), "max_cpa": round(ltv * cfg.max_cpa_fraction_of_ltv, 2),
    }


def campaign_efficiency(campaign_stats: List[dict], cfg: GrowthConfig, seed: int = 7) -> Dict[int, dict]:
    """Bayesian CPA estimate per campaign from SENSE stats."""
    rng = np.random.default_rng(seed)
    out = {}
    for c in campaign_stats:
        clicks, signups, booked = c["clicks"], c["signups"], c["booked"]
        a = cfg.cvr_prior_alpha + signups
        b = cfg.cvr_prior_beta + max(0, clicks - signups)
        cvr_mean = a / (a + b)
        cvr_p90 = float(np.quantile(rng.beta(a, b, 4000), 0.9))
        book_rate = (booked + cfg.signup_to_booking_rate * 5) / (signups + 5)   # 5 pseudo-signups of prior
        cpc = c["cost"] / clicks if clicks else cfg.default_cpc
        cpa = cpc / (cvr_mean * book_rate)
        cpa_optimistic = cpc / (cvr_p90 * book_rate)
        out[c["campaign_id"]] = {
            "cpc": round(cpc, 2), "cvr": round(cvr_mean, 4), "cvr_p90": round(cvr_p90, 4),
            "booking_rate": round(book_rate, 3), "cpa": round(cpa, 2), "cpa_optimistic": round(cpa_optimistic, 2),
            "observed_cpa": round(c["cost"] / booked, 2) if booked else None,
        }
    return out


def capacity_gap(forecast: Forecast, cfg: GrowthConfig) -> dict:
    per_day, by_weekday_gap, by_weekday_target = [], [0.0] * 7, [0.0] * 7
    for d in forecast.days:
        target = cfg.target_utilization * d["capacity_slots"]
        gap = max(0.0, target - d["expected_bookings"])
        d["gap_slots"] = round(gap, 2)
        per_day.append(gap)
        by_weekday_gap[d["weekday"]] += gap
        by_weekday_target[d["weekday"]] += target
    next7 = sum(per_day[:7])
    gap_weekdays = [wd for wd in range(7)
                    if by_weekday_target[wd] and by_weekday_gap[wd] / by_weekday_target[wd] > GAP_WEEKDAY_THRESHOLD]
    return {
        "gap_slots_next_7_days": round(next7, 2),
        "gap_slots_horizon": round(sum(per_day), 2),
        "gap_weekdays": gap_weekdays,
        "gap_weekday_names": [WEEKDAY_NAMES[w] for w in gap_weekdays],
        "gap_share_by_weekday": [round(g / t, 3) if t else None for g, t in zip(by_weekday_gap, by_weekday_target)],
    }


def decide(campaigns: List[dict], efficiency: Dict[int, dict], econ: dict, gap: dict,
           cfg: GrowthConfig) -> tuple:
    """Pure function: (state) -> (budget plan, decisions). Easy to unit test."""
    loop_campaigns = [c for c in campaigns if c["managed_by_loop"] and c["status"] != "REMOVED"]
    enabled = [c for c in loop_campaigns if c["status"] == "ENABLED"]
    max_cpa = econ["max_cpa"]
    decisions: List[Decision] = []

    def eff(c):
        return efficiency.get(c["id"]) or {"cpa": None, "cpa_optimistic": None, "cpc": cfg.default_cpc}

    # 1) Kill campaigns that can't pay back even under optimistic assumptions.
    survivors = []
    for c in enabled:
        e, stats_clicks = eff(c), c.get("clicks", 0)
        if stats_clicks >= cfg.min_clicks_for_judgement and e["cpa_optimistic"] and e["cpa_optimistic"] > max_cpa:
            decisions.append(Decision("pause",
                f"CPA ~${e['cpa']:.0f} (best case ${e['cpa_optimistic']:.0f}) exceeds the ${max_cpa:.0f} ceiling "
                f"(1/3 of a ${econ['ltv']:.0f} 12-month client value)", c["id"]))
        else:
            survivors.append(c)

    # 2) How much budget does the gap justify?
    # Optimism under uncertainty: until some campaign has enough clicks to judge, price
    # ads at the optimistic end of the prior so the loop explores (small budget) instead
    # of never trying; real data then takes over and step 1 pauses what doesn't pay back.
    judged = [eff(c)["cpa"] for c in survivors
              if eff(c)["cpa"] and c.get("clicks", 0) >= cfg.min_clicks_for_judgement]
    exploring = not judged
    blended_cpa = float(np.mean(judged)) if judged else optimistic_prior_cpa(cfg)
    if blended_cpa > max_cpa:
        required = 0.0
    else:
        required = gap["gap_slots_next_7_days"] / 7.0 * blended_cpa
    required = min(required, cfg.max_total_daily_budget)
    if exploring:
        required = min(required, cfg.max_total_daily_budget * EXPLORE_BUDGET_SHARE)
    plan = {"blended_cpa": round(blended_cpa, 2), "required_daily_budget": round(required, 2),
            "max_total_daily_budget": cfg.max_total_daily_budget, "exploring": exploring}

    # 3) Book is (nearly) full -> step budgets down, pause when they fall below the floor.
    if required < cfg.min_campaign_daily_budget:
        reason = ("forecast says the book fills itself over the next 7 days"
                  if gap["gap_slots_next_7_days"] < 1 else
                  f"remaining gap ({gap['gap_slots_next_7_days']:.1f} slots) doesn't justify the minimum budget")
        for c in survivors:
            new_budget = round(c["daily_budget"] * cfg.budget_step_down, 2)
            if new_budget < cfg.min_campaign_daily_budget:
                decisions.append(Decision("pause", f"Pausing: {reason}", c["id"]))
            else:
                decisions.append(Decision("scale", f"Cutting budget: {reason}", c["id"], new_budget))
        if not survivors:
            decisions.append(Decision("hold", f"No ads needed: {reason}"))
        return plan, decisions

    gap_days = gap["gap_weekdays"] or list(range(7))
    gap_names = ", ".join(gap["gap_weekday_names"]) or "all open days"

    # 4) Nothing running -> re-enable a paused campaign that was efficient, else create one.
    if not survivors:
        paused_ok = [c for c in loop_campaigns if c["status"] == "PAUSED"
                     and (eff(c)["cpa"] or blended_cpa) <= max_cpa
                     and not (c.get("clicks", 0) >= cfg.min_clicks_for_judgement
                              and (eff(c)["cpa_optimistic"] or 0) > max_cpa)]
        budget = round(max(cfg.min_campaign_daily_budget, required), 2)
        if paused_ok:
            best = min(paused_ok, key=lambda c: eff(c)["cpa"] or blended_cpa)
            decisions.append(Decision("enable",
                f"{gap['gap_slots_next_7_days']:.1f} open slots next 7 days on {gap_names}; "
                f"re-enabling best past campaign at ${budget:.0f}/day", best["id"], budget, gap_days))
        else:
            decisions.append(Decision("create",
                f"{gap['gap_slots_next_7_days']:.1f} open slots next 7 days on {gap_names}; "
                f"est. ${blended_cpa:.0f} per booked new client vs ${max_cpa:.0f} ceiling"
                + (" (exploring: optimistic estimate until real click data arrives)" if exploring else ""),
                None, budget, gap_days))
        return plan, decisions

    # 5) Scale survivors toward the requirement, weighting cheaper campaigns more.
    weights = np.array([1.0 / (eff(c)["cpa"] or blended_cpa) for c in survivors])
    shares = weights / weights.sum()
    for c, share in zip(survivors, shares):
        # Hysteresis so the ad schedule doesn't flap between cycles on small forecast moves.
        shares_by_day = gap["gap_share_by_weekday"]
        keep = [wd for wd in c["target_weekdays"]
                if shares_by_day[wd] is not None and shares_by_day[wd] > GAP_WEEKDAY_KEEP_THRESHOLD]
        wanted_days = sorted(set(gap["gap_weekdays"]) | set(keep)) or gap_days
        want = required * float(share)
        current = c["daily_budget"]
        new_budget = min(want, current * cfg.budget_step_up)
        new_budget = max(new_budget, current * cfg.budget_step_down, cfg.min_campaign_daily_budget)
        new_budget = round(new_budget, 2)
        if abs(new_budget - current) >= 0.5:
            verb = "Raising" if new_budget > current else "Lowering"
            decisions.append(Decision("scale",
                f"{verb} budget ${current:.0f} -> ${new_budget:.0f}/day toward ${required:.0f}/day needed for "
                f"{gap['gap_slots_next_7_days']:.1f} open slots", c["id"], new_budget))
        if sorted(c["target_weekdays"]) != wanted_days:
            names = ", ".join(WEEKDAY_NAMES[w] for w in wanted_days)
            decisions.append(Decision("reschedule", f"Open-chair days are now {names}", c["id"],
                                      target_weekdays=wanted_days))
    if not decisions:
        decisions.append(Decision("hold", "Campaigns are on target; no change"))
    return plan, decisions


def as_dicts(decisions: List[Decision]) -> List[dict]:
    return [asdict(d) for d in decisions]
