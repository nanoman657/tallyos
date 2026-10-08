from datetime import date, datetime, time, timedelta

import pytest

from app import erp
from app.ads.base import Click
from app.ads.simulated import SimulatedGoogleAds
from app.config import GrowthConfig, Settings
from app.growth import think
from app.growth.forecast import build_forecast
from app.growth.loop import run_cycle
from app.growth.signups import link_first_appointments, reattribute_pending, record_signup
from app.growth.sense import sync_platform

AS_OF = date(2026, 10, 13)   # a Tuesday
CFG = GrowthConfig()


def visit(db, client_id, day, hour=10, status="completed"):
    start = datetime.combine(day, time(hour))
    return db.insert("appointments", {"client_id": client_id, "staff_id": 1, "service_id": 1, "start_at": start,
                                      "duration_min": 40, "price": 38, "status": status,
                                      "created_at": start - timedelta(days=3)})


def test_forecast_puts_regular_client_mass_near_their_cycle(db):
    c = db.insert("clients", {"name": "Reg", "created_at": datetime(2025, 1, 1)})
    # Every 21 days on Tuesdays, last visit 3 weeks before AS_OF.
    for k in range(6, 0, -1):
        visit(db, c["id"], AS_OF - timedelta(days=21 * k))
    fc = build_forecast(db, AS_OF, 14, include_clients=True)
    by_day = {d["date"]: d["from_regulars"] for d in fc.days}
    assert by_day[AS_OF] == max(by_day.values())          # due today, on a Tuesday
    assert by_day[date(2026, 10, 19)] == 0                  # Monday: closed
    outlook = fc.clients[0]
    assert outlook.mean_interval == pytest.approx(21, abs=3)
    assert outlook.status == "due"
    assert 0.5 < outlook.p_within_horizon <= 1.0


def test_already_booked_clients_are_not_double_counted(db):
    c = db.insert("clients", {"name": "Reg", "created_at": datetime(2025, 1, 1)})
    for k in range(4, 0, -1):
        visit(db, c["id"], AS_OF - timedelta(days=28 * k))
    visit(db, c["id"], AS_OF + timedelta(days=2), status="booked")
    fc = build_forecast(db, AS_OF, 7)
    assert sum(d["from_regulars"] for d in fc.days) == 0
    assert fc.days[2]["already_booked"] == 1
    assert fc.days[2]["expected_bookings"] == pytest.approx(1, abs=0.2)


def test_lapsed_client_contributes_little(db):
    c = db.insert("clients", {"name": "Gone", "created_at": datetime(2025, 1, 1)})
    for k in range(5, 0, -1):
        visit(db, c["id"], AS_OF - timedelta(days=120 + 21 * k))
    fc = build_forecast(db, AS_OF, 14, include_clients=True)
    assert fc.clients[0].status == "lapsed"
    assert fc.clients[0].p_within_horizon < 0.1


ECON = {"max_cpa": 100.0, "ltv": 300.0}


def gap(slots, weekdays=(1, 2)):
    shares = [None] + [0.0] * 5 + [None]
    for w in weekdays:
        shares[w] = 0.4
    return {"gap_slots_next_7_days": slots, "gap_weekdays": list(weekdays),
            "gap_weekday_names": [think.WEEKDAY_NAMES[w] for w in weekdays], "gap_share_by_weekday": shares}


def campaign(**kw):
    base = {"id": 1, "managed_by_loop": True, "status": "ENABLED", "daily_budget": 20.0,
            "target_weekdays": [1, 2], "clicks": 0}
    return {**base, **kw}


def test_decide_creates_campaign_for_gap_when_none_running():
    plan, decisions = think.decide([], {}, ECON, gap(10), CFG)
    assert [d.action for d in decisions] == ["create"]
    assert decisions[0].target_weekdays == [1, 2]
    assert CFG.min_campaign_daily_budget <= decisions[0].daily_budget <= CFG.max_total_daily_budget


def test_decide_pauses_campaign_that_cannot_pay_back():
    eff = {1: {"cpa": 400.0, "cpa_optimistic": 250.0, "cpc": 3.0}}
    _, decisions = think.decide([campaign(clicks=200)], eff, ECON, gap(10), CFG)
    assert decisions[0].action == "pause"


def test_decide_does_not_judge_on_too_few_clicks():
    eff = {1: {"cpa": 400.0, "cpa_optimistic": 250.0, "cpc": 3.0}}
    _, decisions = think.decide([campaign(clicks=5)], eff, ECON, gap(10), CFG)
    assert "pause" not in [d.action for d in decisions]


def test_decide_winds_down_when_book_is_full():
    eff = {1: {"cpa": 50.0, "cpa_optimistic": 40.0, "cpc": 3.0}}
    _, decisions = think.decide([campaign(daily_budget=20)], eff, ECON, gap(0, ()), CFG)
    assert decisions[0].action == "scale" and decisions[0].daily_budget == pytest.approx(14.0)
    _, decisions = think.decide([campaign(daily_budget=6)], eff, ECON, gap(0, ()), CFG)
    assert decisions[0].action == "pause"


def test_decide_scales_budget_up_in_bounded_steps():
    eff = {1: {"cpa": 50.0, "cpa_optimistic": 40.0, "cpc": 3.0}}
    plan, decisions = think.decide([campaign(daily_budget=10)], eff, ECON, gap(20), CFG)
    scale = next(d for d in decisions if d.action == "scale")
    assert scale.daily_budget == pytest.approx(10 * CFG.budget_step_up)
    assert plan["required_daily_budget"] <= CFG.max_total_daily_budget


def test_decide_reschedule_has_hysteresis():
    eff = {1: {"cpa": 50.0, "cpa_optimistic": 40.0, "cpc": 3.0}}
    g = gap(20, (1,))
    g["gap_share_by_weekday"][2] = 0.07   # Wednesday dipped below "add" threshold but above "keep"
    _, decisions = think.decide([campaign(daily_budget=40 / 1.25)], eff, ECON, g, CFG)
    assert "reschedule" not in [d.action for d in decisions]


def test_signup_attribution_gclid_utm_organic_and_pending(db):
    camp = db.insert("ad_campaigns", {"name": "Fill Tue", "daily_budget": 10, "external_id": "ext-1"})
    db.insert("ad_clicks", {"gclid": "G-KNOWN", "campaign_id": camp["id"], "clicked_on": AS_OF})
    assert record_signup(db, name="A", phone="1", gclid="G-KNOWN")["attribution"] == "gclid"
    assert record_signup(db, name="B", phone="2", utm_source="google", utm_campaign=str(camp["id"]))["attribution"] == "utm"
    assert record_signup(db, name="C", phone="3", utm_source="instagram")["attribution"] == "organic"
    pending = record_signup(db, name="D", phone="4", gclid="G-LATE")
    assert pending["attribution"] == "gclid_pending" and pending["campaign_id"] is None
    assert db.scalar("SELECT source FROM clients WHERE id = %s", [pending["client_id"]]) == "google_ads"

    # Click report catches up -> next SENSE re-attributes.
    db.insert("ad_clicks", {"gclid": "G-LATE", "campaign_id": camp["id"], "clicked_on": AS_OF})
    assert reattribute_pending(db) == 1
    assert db.scalar("SELECT campaign_id FROM signups WHERE id = %s", [pending["id"]]) == camp["id"]


def test_signup_links_to_first_booking_after_signup(db):
    s = record_signup(db, name="New", phone="9", at=datetime(2026, 10, 12, 20))
    erp.book_appointment(db, s["client_id"], 1, datetime(2026, 10, 14, 10), created_at=datetime(2026, 10, 12, 20, 5))
    assert link_first_appointments(db) == 1
    assert db.scalar("SELECT first_appointment_id FROM signups WHERE id = %s", [s["id"]]) is not None


def test_existing_client_signing_up_again_is_not_duplicated(db):
    a = record_signup(db, name="Same", phone="777")
    b = record_signup(db, name="Same Person", phone="777", gclid="G-X")
    assert a["client_id"] == b["client_id"]


def test_full_loop_creates_campaign_then_detects_signups(db):
    """SENSE -> THINK -> ACT, let simulated days pass, then SENSE detects the ad sign-ups."""
    settings = Settings(database_url="unused")
    platform = SimulatedGoogleAds(db, seed=3)
    # A thin book: lots of open chairs.
    for i in range(10):
        c = db.insert("clients", {"name": f"R{i}", "created_at": datetime(2025, 1, 1)})
        for k in range(3, 0, -1):
            visit(db, c["id"], AS_OF - timedelta(days=28 * k - i % 5), hour=9 + i % 7)

    first = run_cycle(db, platform, settings, as_of=AS_OF)
    created = [a for a in first["act"] if a["action"] == "create"]
    assert created and created[0]["executed"] and created[0]["status"] == "ENABLED"
    assert db.scalar("SELECT count(*) FROM ad_campaigns WHERE status = 'ENABLED'") == 1

    later = AS_OF + timedelta(days=21)
    second = run_cycle(db, platform, settings, as_of=later)
    camp_stats = second["sense"]["campaigns"][0]
    assert camp_stats["clicks"] > 0 and camp_stats["cost"] > 0
    assert second["sense"]["signups"]["google_ads_signups"] > 0
    assert db.scalar("SELECT count(*) FROM signups WHERE attribution = 'gclid' AND campaign_id IS NOT NULL") > 0
    uploaded = next(a for a in second["act"] if a["action"] == "upload_conversions")
    assert uploaded["uploaded"] == db.scalar("SELECT count(*) FROM signups WHERE conversion_uploaded")
    # Guardrail held throughout.
    assert db.scalar("SELECT sum(daily_budget) FROM ad_campaigns WHERE status = 'ENABLED'") <= CFG.max_total_daily_budget
    assert db.scalar("SELECT count(*) FROM loop_runs") == 2
    assert db.scalar("SELECT count(*) FROM forecasts") == 2 * CFG.forecast_horizon_days


def test_dry_run_changes_nothing(db):
    settings = Settings(database_url="unused")
    result = run_cycle(db, SimulatedGoogleAds(db), settings, as_of=AS_OF, dry_run=True)
    assert db.scalar("SELECT count(*) FROM ad_campaigns") == 0
    assert all(a.get("note") == "dry run" or a["action"] == "hold" for a in result["act"])


def test_live_backend_creates_campaigns_paused_for_approval(db):
    settings = Settings(database_url="unused", ads_backend="google", ads_auto_enable=False)
    platform = SimulatedGoogleAds(db)        # stand-in API; only the approval rule is under test
    result = run_cycle(db, platform, settings, as_of=AS_OF)
    created = next(a for a in result["act"] if a["action"] == "create")
    assert created["status"] == "PAUSED" and "approve" in created["note"]


def test_sync_imports_external_campaigns_as_unmanaged(db):
    class FakePlatform:
        def fetch_daily_metrics(self, start, end):
            return []

        def fetch_clicks(self, start, end):
            return [Click("G-EXT", "customers/1/campaigns/999", AS_OF)]

    sync_platform(db, FakePlatform(), AS_OF, AS_OF)
    row = db.one("SELECT * FROM ad_campaigns WHERE external_id = 'customers/1/campaigns/999'")
    assert row and row["managed_by_loop"] is False
