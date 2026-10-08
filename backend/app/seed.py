"""
Demo data: a solo-barber shop (calibrated to the digital twin's Fresh &
Focused / Will numbers -- $38 cuts, $65 combos, 40-60 minute services, Tue-Sat)
with ~150 days of client history, and the growth loop replayed over the last
60 days against the simulated Google Ads platform.

    python -m app.cli seed --reset
"""

from datetime import date, datetime, time, timedelta

import numpy as np

from . import erp
from .ads.simulated import FIRST_NAMES, LAST_NAMES, SimulatedGoogleAds
from .config import Settings
from .db import Db
from .growth.loop import run_cycle
from .growth.signups import record_signup

HISTORY_DAYS = 150
LOOP_REPLAY_DAYS = 60
LOOP_EVERY_DAYS = 3
REGULARS = 115
ORGANIC_NEW_PER_DAY = 0.22
NEW_CLIENT_STICK_PROB = 0.55
LAPSE_PROB = 0.12
ONLINE_SIGNUP_SHARE = 0.5


def seed_catalog(db: Db) -> None:
    db.insert("shop", {
        "id": 1, "name": "Fresh & Focused Barbershop", "address": "2401 N. Shepherd Dr, Suite 236, Houston, TX 77008",
        "open_weekdays": [1, 2, 3, 4, 5], "open_minute": 9 * 60, "close_minute": 17 * 60, "break_minutes": 30,
        "monthly_rent": 1750, "monthly_software": 200, "card_fee_rate": 0.03, "state_city_tax_rate": 0.0,
        "health_insurance_annual": 6000, "filing_status": "head_of_household",
    })
    db.insert("staff", {"name": "Will", "role": "barber", "commission_rate": 0})
    db.insert("staff", {"name": "Front desk (Booksy)", "role": "admin", "commission_rate": 0})
    for name, price, minutes, cogs in [
        ("Standard Cut", 38, 40, 1.80), ("Skin Fade", 40, 45, 1.90), ("Fresh Combo", 65, 60, 3.20),
        ("Beard Trim", 20, 20, 1.00), ("Kids Cut", 28, 30, 1.50),
    ]:
        db.insert("services", {"name": name, "price": price, "duration_min": minutes, "cogs": cogs})
    for sku, name, cost, retail, on_hand, rp, rq in [
        ("POM-01", "Matte Pomade 3oz", 6.50, 18.00, 14, 5, 12),
        ("OIL-01", "Beard Oil 1oz", 5.00, 16.00, 9, 4, 12),
        ("BLD-100", "Razor Blades (100)", 12.00, None, 3, 2, 4),
        ("NCK-500", "Neck Strips (500)", 9.00, None, 2, 1, 3),
        ("BAR-32", "Barbicide 32oz", 11.00, None, 1, 1, 2),
    ]:
        db.insert("products", {"sku": sku, "name": name, "unit_cost": cost, "retail_price": retail,
                               "on_hand": on_hand, "reorder_point": rp, "reorder_qty": rq})


def _new_client(db: Db, rng, created: datetime, source: str = "organic") -> dict:
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    return db.insert("clients", {"name": name, "phone": f"713{int(rng.integers(1000000, 9999999))}",
                                 "created_at": created, "source": source})


def _profile(rng) -> dict:
    prefs = [4, 5] if rng.random() < 0.6 else sorted(rng.choice([1, 2, 3], size=2, replace=False).tolist())
    return {
        "mu": float(np.clip(rng.normal(27, 5), 14, 45)), "sd": float(rng.uniform(2.5, 6)),
        "prefs": prefs, "service": int(rng.choice([1, 2, 3, 4, 5], p=[0.42, 0.25, 0.2, 0.08, 0.05])),
        "lapse_on": None,
    }


def _try_book(db: Db, client_id: int, prof: dict, want: date, created: datetime) -> date:
    slot = erp.first_free_slot(db, prof["service"], want, prof["prefs"], search_days=10) \
        or erp.first_free_slot(db, prof["service"], want, None, search_days=10)
    if not slot:
        return None
    erp.book_appointment(db, client_id, prof["service"], slot["start_at"], slot["staff_id"], created_at=created)
    return slot["start_at"].date()


def _close_day(db: Db, rng, day: date) -> None:
    """Check out (or no-show) every appointment that started on `day`."""
    for appt in db.all("SELECT id FROM appointments WHERE status = 'booked' AND start_at::date = %s", [day]):
        if rng.random() < 0.03:
            db.update("appointments", appt["id"], {"status": "no_show"})
            continue
        products = [{"product_id": 1 if rng.random() < 0.6 else 2, "qty": 1}] if rng.random() < 0.08 else []
        for p in products:
            if db.scalar("SELECT on_hand FROM products WHERE id = %s", [p["product_id"]]) < 1:
                products = []
        price = db.scalar("SELECT price FROM appointments WHERE id = %s", [appt["id"]])
        erp.complete_appointment(db, appt["id"], tip=round(price * rng.uniform(0.1, 0.25), 2),
                                 payment_method="card" if rng.random() < 0.85 else "cash", products=products)
    # Restock anything at or under its reorder point once a week (Mondays).
    if day.weekday() == 0:
        for p in erp.low_stock(db):
            erp.adjust_stock(db, p["id"], p["reorder_qty"], "purchase", datetime.combine(day, time(10)))
            db.insert("expenses", {"at": day, "category": "supplies", "amount": p["unit_cost"] * p["reorder_qty"],
                                   "memo": f"Restock {p['name']}"})


def seed(db: Db, settings: Settings, today: date = None, seed: int = 11) -> dict:
    today = today or date.today()
    rng = np.random.default_rng(seed)
    seed_catalog(db)
    platform = SimulatedGoogleAds(db, seed=seed)
    start = today - timedelta(days=HISTORY_DAYS)

    # Established regulars (clients for over a year), next visit due somewhere in the first cycle.
    profiles, next_due = {}, {}
    for _ in range(REGULARS):
        c = _new_client(db, rng, datetime.combine(start - timedelta(days=int(rng.integers(240, 900))), time(12)))
        prof = _profile(rng)
        if rng.random() < LAPSE_PROB:
            prof["lapse_on"] = start + timedelta(days=int(rng.integers(20, HISTORY_DAYS)))
        profiles[c["id"]] = prof
        next_due[c["id"]] = start + timedelta(days=int(rng.integers(0, int(prof["mu"]))))

    runs = 0
    for offset in range(HISTORY_DAYS + 1):
        day = start + timedelta(days=offset)
        _close_day(db, rng, day - timedelta(days=1))

        # Ad-driven clients who came back become regulars too.
        for row in db.all("SELECT id FROM clients WHERE source = 'google_ads' AND NOT (id = ANY(%s))", [list(profiles)]):
            visited = db.scalar("SELECT max(start_at) FROM appointments WHERE client_id = %s AND status = 'completed'",
                                [row["id"]])
            if visited:
                prof = _profile(rng)
                if rng.random() > NEW_CLIENT_STICK_PROB:
                    prof["lapse_on"] = day
                profiles[row["id"]] = prof
                next_due[row["id"]] = visited.date() + timedelta(days=int(max(10, rng.normal(prof["mu"], prof["sd"]))) - 5)

        # Organic walk-ins / referrals.
        for _ in range(rng.poisson(ORGANIC_NEW_PER_DAY)):
            created = datetime.combine(day, time(int(rng.integers(8, 20))))
            if rng.random() < ONLINE_SIGNUP_SHARE:
                # Found the shop online (Instagram, Maps, word of mouth) and used the join page.
                signup = record_signup(db, name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                                       phone=f"832{int(rng.integers(1000000, 9999999))}",
                                       utm_source=str(rng.choice(["instagram", "google_maps", ""])) or None, at=created)
                c = {"id": signup["client_id"]}
            else:
                c = _new_client(db, rng, created, source=str(rng.choice(["referral", "walk_in"])))
            prof = _profile(rng)
            if rng.random() > NEW_CLIENT_STICK_PROB:
                prof["lapse_on"] = day + timedelta(days=1)
            profiles[c["id"]] = prof
            _try_book(db, c["id"], prof, day + timedelta(days=int(rng.integers(0, 4))), created)
            next_due[c["id"]] = day + timedelta(days=int(prof["mu"]))

        # Regulars whose cycle is up reach out and book (lead time 0-6 days).
        for cid, due in list(next_due.items()):
            prof = profiles[cid]
            if due != day or (prof["lapse_on"] and day >= prof["lapse_on"]):
                continue
            created = datetime.combine(day, time(int(rng.integers(7, 22))))
            booked_on = _try_book(db, cid, prof, day + timedelta(days=int(rng.integers(0, 7))), created)
            anchor = booked_on or day
            next_due[cid] = anchor + timedelta(days=int(max(10, rng.normal(prof["mu"], prof["sd"]))) - 5)

        # Replay the growth loop over the recent past.
        if day >= today - timedelta(days=LOOP_REPLAY_DAYS) and (offset % LOOP_EVERY_DAYS == 0 or day == today):
            run_cycle(db, platform, settings, as_of=day)
            runs += 1

    return {
        "clients": db.scalar("SELECT count(*) FROM clients"),
        "appointments": db.scalar("SELECT count(*) FROM appointments"),
        "signups": db.scalar("SELECT count(*) FROM signups"),
        "campaigns": db.scalar("SELECT count(*) FROM ad_campaigns"),
        "loop_runs": runs,
    }
