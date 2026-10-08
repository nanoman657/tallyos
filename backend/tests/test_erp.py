from datetime import date, datetime, timedelta

import pytest

from app import erp

TUESDAY = date(2026, 10, 13)   # open (shop is Tue-Sat)
MONDAY = date(2026, 10, 12)    # closed


def at(day, hhmm):
    h, m = hhmm.split(":")
    return datetime.combine(day, datetime.min.time()).replace(hour=int(h), minute=int(m))


def client(db, name="Ana"):
    return db.insert("clients", {"name": name, "phone": name + "1"})


def test_capacity_counts_break_and_closed_days(db):
    shop = erp.get_shop(db)
    assert erp.bookable_minutes(shop, 1, TUESDAY) == 8 * 60 - 30
    assert erp.bookable_minutes(shop, 1, MONDAY) == 0
    assert erp.capacity_slots(db, shop, TUESDAY, 45.0) == pytest.approx(450 / 45)


def test_booking_rejects_overlap_and_outside_hours(db):
    c = client(db)
    erp.book_appointment(db, c["id"], 1, at(TUESDAY, "10:00"))
    with pytest.raises(erp.ErpError, match="No barber free"):
        erp.book_appointment(db, c["id"], 1, at(TUESDAY, "10:20"))
    with pytest.raises(erp.ErpError, match="Outside opening hours"):
        erp.book_appointment(db, c["id"], 1, at(MONDAY, "10:00"))
    with pytest.raises(erp.ErpError, match="Outside opening hours"):
        erp.book_appointment(db, c["id"], 3, at(TUESDAY, "16:30"))   # 60 min combo runs past close
    # back-to-back is fine
    erp.book_appointment(db, c["id"], 1, at(TUESDAY, "10:40"))


def test_availability_skips_booked_time(db):
    c = client(db)
    erp.book_appointment(db, c["id"], 1, at(TUESDAY, "09:00"))
    starts = [s["start_at"] for s in erp.availability(db, TUESDAY, 1)]
    assert at(TUESDAY, "09:00") not in starts
    assert at(TUESDAY, "09:30") not in starts
    assert at(TUESDAY, "09:45") in starts
    assert erp.availability(db, MONDAY, 1) == []


def test_checkout_records_sale_fees_and_stock(db):
    c = client(db)
    appt = erp.book_appointment(db, c["id"], 1, at(TUESDAY, "11:00"))
    before = db.scalar("SELECT on_hand FROM products WHERE id = 1")
    sale = erp.complete_appointment(db, appt["id"], tip=10, products=[{"product_id": 1, "qty": 2}])
    assert sale["subtotal"] == 38 + 2 * 18
    assert sale["card_fee"] == round((38 + 36 + 10) * 0.03, 2)
    assert sale["cogs"] == pytest.approx(1.80 + 2 * 6.50)
    assert db.scalar("SELECT on_hand FROM products WHERE id = 1") == before - 2
    assert db.scalar("SELECT status FROM appointments WHERE id = %s", [appt["id"]]) == "completed"
    with pytest.raises(erp.ErpError):
        erp.complete_appointment(db, appt["id"])


def test_cannot_sell_back_bar_supplies(db):
    with pytest.raises(erp.ErpError, match="back-bar"):
        erp.record_sale(db, client_id=None, staff_id=1, items=[{"kind": "product", "ref_id": 3, "qty": 1}])


def test_finance_summary_includes_ad_spend_and_taxes(db):
    c = client(db)
    appt = erp.book_appointment(db, c["id"], 3, at(TUESDAY, "12:00"))
    erp.complete_appointment(db, appt["id"], payment_method="cash")
    camp = db.insert("ad_campaigns", {"name": "x", "daily_budget": 10, "status": "ENABLED"})
    db.insert("ad_metrics_daily", {"campaign_id": camp["id"], "date": TUESDAY, "clicks": 3, "cost": 9.5})
    f = erp.finance_summary(db, TUESDAY, TUESDAY + timedelta(days=1))
    assert f["revenue"] == 65
    assert f["card_fees"] == 0
    assert f["ad_spend"] == 9.5
    assert f["operating_profit"] == pytest.approx(65 - 3.20 - 9.5 - (1750 + 200) * 12 / 365)
    assert set(f["taxes"]) >= {"se_tax", "federal_income_tax", "true_take_home"}
