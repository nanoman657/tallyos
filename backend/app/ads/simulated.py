"""
Offline stand-in for Google Ads, so the whole sense-think-act loop can be run
and demoed without an ad account or real money.

It keeps its own "remote" state in sim_ads_* tables (separate from the ERP's
ad_* tables, exactly as a real Google Ads account would be), and simulates the
outside world day by day for every ENABLED campaign:

  clicks      Hill saturation curve in daily budget -- the same functional
              form the digital twin uses (barbershop_twin/models.py,
              ad_walkin_multiplier): a ~3-mile audience saturates fast, so
              extra budget buys fewer and pricier clicks.
  sign-ups    a share of clicks fill in the shop's join form, carrying the
              click's gclid (recorded through the real sign-up code path).
  bookings    a share of those sign-ups book a first appointment on one of
              the campaign's target weekdays, if a chair is free.

The world is simulated lazily up to "yesterday" whenever metrics are read.
"""

import json
import uuid
from datetime import date, datetime, time, timedelta
from typing import List

import numpy as np

from ..db import Db
from .base import CampaignSpec, Click, DailyMetric, OfflineConversion, UploadResult

SIM_SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_ads_campaigns (
    external_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_on  DATE NOT NULL,
    events      JSONB NOT NULL DEFAULT '[]'   -- [{on, status?, budget?, weekdays?}]
);
CREATE TABLE IF NOT EXISTS sim_ads_metrics (
    external_id TEXT NOT NULL, date DATE NOT NULL,
    impressions INTEGER NOT NULL, clicks INTEGER NOT NULL, cost NUMERIC(12,2) NOT NULL,
    conversions INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (external_id, date)
);
CREATE TABLE IF NOT EXISTS sim_ads_clicks (
    gclid TEXT PRIMARY KEY, external_id TEXT NOT NULL, date DATE NOT NULL,
    converted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS sim_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Market response (reasoned assumptions for a ~3 mile radius, single-shop local search)
HILL_MAX_CLICKS = 22.0      # daily clicks at full saturation of local "barber near me" demand
HILL_HALF_SAT_BUDGET = 15.0 # $/day for half of that
HILL_SLOPE = 1.5
BASE_CPC = 2.40
CTR = 0.055
BASE_CVR = 0.10             # click -> sign-up form
FOCUSED_SCHEDULE_CVR_BONUS = 1.15   # "open chairs Tue & Wed" copy converts better than generic
SIGNUP_BOOK_PROB = 0.65
FIRST_NAMES = ["Marcus", "Andre", "Jamal", "Luis", "Chris", "Darius", "Kevin", "Omar", "Tyler", "Malik",
               "Jordan", "Isaiah", "Carlos", "Devin", "Brandon", "Elijah", "Xavier", "Nate", "Rashad", "Victor"]
LAST_NAMES = ["Johnson", "Williams", "Garcia", "Brown", "Davis", "Lopez", "Wilson", "Moore", "Taylor",
              "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Robinson", "Clark", "Lewis"]


class SimulatedGoogleAds:
    name = "simulated"

    def __init__(self, db: Db, seed: int = 42):
        self.db = db
        self.seed = seed
        self.today = date.today()
        db.conn.execute(SIM_SCHEMA)

    def set_today(self, today: date) -> None:
        self.today = today

    # ---------------------------------------------------------------- campaign management
    def _event(self, external_id: str, **change) -> None:
        self.db.execute(
            "UPDATE sim_ads_campaigns SET events = events || %s::jsonb WHERE external_id = %s",
            [json.dumps([{"on": self.today.isoformat(), **change}]), external_id],
        )

    def create_campaign(self, spec: CampaignSpec) -> str:
        external_id = f"customers/0000000000/campaigns/{uuid.uuid4().int % 10**10}"
        self.db.execute("INSERT INTO sim_ads_campaigns (external_id, name, created_on) VALUES (%s,%s,%s)",
                        [external_id, spec.name, self.today])
        self._event(external_id, status="ENABLED" if spec.enabled else "PAUSED",
                    budget=spec.daily_budget, weekdays=spec.target_weekdays)
        return external_id

    def update_budget(self, external_id: str, daily_budget: float) -> None:
        self._event(external_id, budget=daily_budget)

    def update_schedule(self, external_id: str, weekdays: List[int]) -> None:
        self._event(external_id, weekdays=weekdays)

    def set_status(self, external_id: str, status: str) -> None:
        self._event(external_id, status=status)

    @staticmethod
    def _state_on(events: list, day: date) -> dict:
        state = {"status": "PAUSED", "budget": 0.0, "weekdays": []}
        for e in events:
            if date.fromisoformat(e["on"]) <= day:
                state.update({k: v for k, v in e.items() if k != "on"})
        return state

    # ---------------------------------------------------------------- the simulated world
    def _simulate_through(self, end: date) -> None:
        end = min(end, self.today - timedelta(days=1))
        row = self.db.one("SELECT value FROM sim_state WHERE key = 'simulated_through'")
        first_created = self.db.scalar("SELECT min(created_on) FROM sim_ads_campaigns")
        if first_created is None:
            return
        day = date.fromisoformat(row["value"]) + timedelta(days=1) if row else first_created
        while day <= end:
            self.simulate_day(day)
            self.db.execute(
                """INSERT INTO sim_state (key, value) VALUES ('simulated_through', %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", [day.isoformat()])
            day += timedelta(days=1)

    def simulate_day(self, day: date) -> None:
        # Imported here: the simulator plays the role of real people using the shop's
        # own sign-up and booking flows.
        from .. import erp
        from ..growth.signups import record_signup

        rng = np.random.default_rng(self.seed * 100_003 + day.toordinal())
        for camp in self.db.all("SELECT * FROM sim_ads_campaigns WHERE created_on <= %s ORDER BY external_id", [day]):
            st = self._state_on(camp["events"], day)
            if st["status"] != "ENABLED" or (st["weekdays"] and day.weekday() not in st["weekdays"]):
                continue
            budget = float(st["budget"])
            sat = budget ** HILL_SLOPE / (HILL_HALF_SAT_BUDGET ** HILL_SLOPE + budget ** HILL_SLOPE)
            cpc = BASE_CPC * (1 + 0.5 * sat) * rng.uniform(0.85, 1.15)
            expected_clicks = min(HILL_MAX_CLICKS * sat, budget / cpc)
            clicks = int(min(rng.poisson(expected_clicks), budget * 1.2 // cpc))
            cost = round(clicks * cpc, 2)
            impressions = int(clicks / CTR * rng.uniform(0.8, 1.2)) if clicks else int(rng.poisson(budget * 2))
            self.db.execute(
                """INSERT INTO sim_ads_metrics (external_id, date, impressions, clicks, cost) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (external_id, date) DO NOTHING""",
                [camp["external_id"], day, impressions, clicks, cost])

            focused = 0 < len(st["weekdays"]) <= 3
            cvr = BASE_CVR * (1 - 0.35 * sat) * (FOCUSED_SCHEDULE_CVR_BONUS if focused else 1.0)
            for _ in range(clicks):
                gclid = "SIM" + uuid.UUID(int=int(rng.integers(0, 2**63)) << 64 | int(rng.integers(0, 2**63))).hex
                self.db.execute("INSERT INTO sim_ads_clicks (gclid, external_id, date) VALUES (%s,%s,%s)",
                                [gclid, camp["external_id"], day])
                if rng.random() >= cvr:
                    continue
                at = datetime.combine(day, time(int(rng.integers(8, 22)), int(rng.integers(0, 60))))
                first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
                signup = record_signup(
                    self.db, name=f"{first} {last}", phone=f"555{int(rng.integers(1000000, 9999999))}",
                    gclid=gclid, at=at)
                if rng.random() >= SIGNUP_BOOK_PROB:
                    continue
                service = self.db.one("SELECT id FROM services WHERE active ORDER BY price LIMIT 1")
                slot = erp.first_free_slot(self.db, service["id"], day + timedelta(days=1),
                                           st["weekdays"] or None, search_days=10)
                if slot:
                    erp.book_appointment(self.db, signup["client_id"], service["id"], slot["start_at"],
                                         slot["staff_id"], created_at=at)

    # ---------------------------------------------------------------- reporting
    def fetch_daily_metrics(self, start: date, end: date) -> List[DailyMetric]:
        self._simulate_through(end)
        rows = self.db.all("SELECT * FROM sim_ads_metrics WHERE date BETWEEN %s AND %s ORDER BY date", [start, end])
        return [DailyMetric(r["external_id"], r["date"], r["impressions"], r["clicks"], r["cost"], r["conversions"])
                for r in rows]

    def fetch_clicks(self, start: date, end: date) -> List[Click]:
        self._simulate_through(end)
        rows = self.db.all("SELECT * FROM sim_ads_clicks WHERE date BETWEEN %s AND %s", [start, end])
        return [Click(r["gclid"], r["external_id"], r["date"]) for r in rows]

    def upload_conversions(self, conversions: List[OfflineConversion]) -> UploadResult:
        failed = []
        for conv in conversions:
            hit = self.db.one("UPDATE sim_ads_clicks SET converted = TRUE WHERE gclid = %s AND NOT converted "
                              "RETURNING external_id, date", [conv.gclid])
            if not hit:
                failed.append(conv.gclid)
                continue
            self.db.execute("UPDATE sim_ads_metrics SET conversions = conversions + 1 WHERE external_id = %s AND date = %s",
                            [hit["external_id"], hit["date"]])
        return UploadResult(uploaded=len(conversions) - len(failed), failed=failed)
