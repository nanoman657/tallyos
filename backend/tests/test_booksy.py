from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import booksy, punctuality
from app.config import Settings
from app.growth.signups import link_first_appointments, record_signup

TZ = ZoneInfo("America/Chicago")


def raw_appt(ext="b-1", start="2026-10-13T15:00:00Z", end="2026-10-13T15:40:00Z", status="accepted", **extra):
    base = {
        "appointment_uid": ext, "booked_from": start, "booked_till": end, "status": status,
        "created": "2026-10-10T18:00:00Z", "total_price": "38.00",
        "customer": {"id": 501, "first_name": "Dre", "last_name": "Lopez", "cell_phone": "+1 (713) 555-0142"},
        "service": {"id": 77, "name": "Standard Cut"},
        "staffer": {"id": 9, "name": "Will"},
    }
    base.update(extra)
    return base


def test_normalize_handles_nested_fields_timezones_and_letter_statuses():
    a = booksy.normalize(raw_appt(status="F", checked_in_at="2026-10-13T15:12:00Z"), TZ)
    assert a.start_at == datetime(2026, 10, 13, 10, 0)          # 15:00Z -> 10:00 CDT
    assert a.end_at == datetime(2026, 10, 13, 10, 40)
    assert a.arrived_at == datetime(2026, 10, 13, 10, 12)
    assert a.status == "completed"
    assert a.customer_name == "Dre Lopez" and a.customer_id == "501"
    assert a.price == 38.0 and a.service_name == "Standard Cut" and a.staff_name == "Will"
    assert booksy.map_status("no-show") == "no_show"
    assert booksy.map_status("C") == "cancelled"
    assert booksy.map_status("something new") == "booked"
    with pytest.raises(booksy.BooksyError):
        booksy.normalize({"status": "accepted"}, TZ)


def test_upsert_creates_then_updates_and_matches_existing_catalog(db):
    a = booksy.normalize(raw_appt(), TZ)
    assert booksy.upsert_appointment(db, a) == "created"
    assert booksy.upsert_appointment(db, a) == "unchanged"
    appt = db.one("SELECT * FROM appointments WHERE external_id = 'b-1'")
    assert appt["service_id"] == 1 and appt["staff_id"] == 1     # matched seeded "Standard Cut" / "Will" by name
    assert db.scalar("SELECT external_id FROM services WHERE id = 1") == "77"
    client = db.one("SELECT * FROM clients WHERE id = %s", [appt["client_id"]])
    assert client["source"] == "booksy" and client["external_id"] == "501"

    moved = booksy.normalize(raw_appt(start="2026-10-14T16:00:00Z", end="2026-10-14T16:40:00Z"), TZ)
    assert booksy.upsert_appointment(db, moved) == "updated"
    assert db.scalar("SELECT start_at FROM appointments WHERE external_id = 'b-1'") == datetime(2026, 10, 14, 11, 0)
    assert db.scalar("SELECT count(*) FROM appointments") == 1


def test_finished_booksy_appointment_books_revenue_once(db):
    a = booksy.normalize(raw_appt(status="finished"), TZ)
    booksy.upsert_appointment(db, a)
    booksy.upsert_appointment(db, a)
    sales = db.all("SELECT * FROM sales")
    assert len(sales) == 1 and sales[0]["subtotal"] == 38 and sales[0]["payment_method"] == "booksy"
    assert sales[0]["card_fee"] == pytest.approx(38 * 0.03, abs=0.01)


def test_checkout_in_app_is_not_reverted_by_stale_booksy_status(db):
    booksy.upsert_appointment(db, booksy.normalize(raw_appt(), TZ))
    appt_id = db.scalar("SELECT id FROM appointments")
    db.update("appointments", appt_id, {"status": "completed"})
    booksy.upsert_appointment(db, booksy.normalize(raw_appt(status="accepted"), TZ))
    assert db.scalar("SELECT status FROM appointments") == "completed"


def test_booksy_booking_links_to_google_ads_signup_by_phone(db):
    s = record_signup(db, name="Dre", phone="713-555-0142", gclid="G-1", at=datetime(2026, 10, 10, 12))
    booksy.upsert_appointment(db, booksy.normalize(raw_appt(), TZ))
    assert db.scalar("SELECT count(*) FROM clients") == 1           # same person, not a duplicate
    assert link_first_appointments(db) == 1
    assert db.scalar("SELECT first_appointment_id FROM signups WHERE id = %s", [s["id"]]) is not None


def test_in_app_check_in_is_kept_when_booksy_has_no_arrival(db):
    booksy.upsert_appointment(db, booksy.normalize(raw_appt(), TZ))
    appt_id = db.scalar("SELECT id FROM appointments")
    punctuality.check_in(db, appt_id, datetime(2026, 10, 13, 10, 9))
    booksy.upsert_appointment(db, booksy.normalize(raw_appt(status="finished"), TZ))
    assert db.scalar("SELECT arrived_at FROM appointments") == datetime(2026, 10, 13, 10, 9)


def test_webhook_cancel_without_payload_and_create_with_payload(db):
    assert booksy.handle_webhook(db, {"action": "created", "appointment": raw_appt()}, TZ, None) == "created"
    assert booksy.handle_webhook(db, {"action": "cancelled", "appointment_id": "b-1"}, TZ, None) == "updated"
    assert db.scalar("SELECT status FROM appointments WHERE external_id = 'b-1'") == "cancelled"
    assert booksy.handle_webhook(db, {"action": "modified"}, TZ, None) == "error"
    kinds = [r["result"] for r in db.all("SELECT result FROM integration_events ORDER BY id")]
    assert kinds == ["created", "updated", "error"]


def test_webhook_refetches_from_api_when_configured(db):
    class FakeApi:
        def get_appointment(self, ext_id):
            return raw_appt(ext=ext_id, status="no_show")
    assert booksy.handle_webhook(db, {"action": "modified", "appointment_id": "b-9"}, TZ, FakeApi()) == "created"
    assert db.scalar("SELECT status FROM appointments WHERE external_id = 'b-9'") == "no_show"


def test_bad_row_is_logged_without_aborting_the_batch(db):
    assert booksy.ingest(db, {"id": "x"}, TZ, "api_sync") == "error"      # no start time
    assert booksy.ingest(db, raw_appt(ext="ok"), TZ, "api_sync") == "created"
    assert db.scalar("SELECT count(*) FROM appointments") == 1


def test_sync_paginates_and_records_state(db, monkeypatch):
    settings = Settings(database_url="unused")
    settings.booksy.api_url, settings.booksy.api_token, settings.booksy.business_id = "https://x", "t", "42"
    api = booksy.BooksyApi(settings)
    pages = {1: {"appointments": [raw_appt(ext=f"p{i}", start=f"2026-10-{13 + i % 3}T{14 + i % 5}:00:00Z",
                                           end=None) for i in range(100)]},
             2: {"appointments": [raw_appt(ext="last")]}}
    calls = []
    monkeypatch.setattr(api, "_get", lambda path, params=None: calls.append(params) or pages[params["page"]])
    summary = booksy.sync(db, api, TZ, date(2026, 10, 1), date(2026, 10, 31))
    assert [c["page"] for c in calls] == [1, 2]
    assert calls[0]["date_from"] == "2026-10-01"
    assert summary["created"] == 101
    assert db.scalar("SELECT last_sync_summary->>'created' FROM integration_state WHERE source = 'booksy'") == "101"


CSV = """Appointment ID,Date,Time,Duration,Client,Phone,Service,Staff,Price,Status,Check-in time
A1,10/13/2026,10:00 AM,40,Marcus Brown,713-555-0001,Standard Cut,Will,$38.00,Finished,10:14 AM
A2,10/13/2026,11:00 AM,60,Andre Davis,713-555-0002,Fresh Combo,Will,$65.00,No-show,
A3,10/14/2026,9:00 AM,40,Marcus Brown,713-555-0001,Standard Cut,Will,$38.00,Finished,8:55 AM
A4,bad date,9:00 AM,40,Nobody,,Standard Cut,Will,$38.00,Finished,
"""


def test_csv_import_maps_columns_lateness_and_is_idempotent(db):
    r = booksy.import_csv(db, CSV, TZ)
    assert r["rows"] == 4 and r["created"] == 3 and r["error"] == 1 and r["errors"][0]["row"] == 5
    assert r["columns"]["arrived"] == "Check-in time"
    late = db.one("SELECT * FROM appointments WHERE external_id = 'A1'")
    assert punctuality.minutes_late(late) == 14
    early = db.one("SELECT * FROM appointments WHERE external_id = 'A3'")
    assert punctuality.minutes_late(early) == 0
    assert db.scalar("SELECT status FROM appointments WHERE external_id = 'A2'") == "no_show"
    assert db.scalar("SELECT count(*) FROM clients") == 2
    again = booksy.import_csv(db, CSV, TZ)
    assert again["created"] == 0 and again["unchanged"] == 3




def test_csv_rejects_unusable_headers(db):
    with pytest.raises(booksy.BooksyError, match="date"):
        booksy.import_csv(db, "foo,bar\n1,2\n", TZ)


def test_csv_yes_no_checkin_column_is_ignored_not_an_error(db):
    text = "Date,Client,Service,Checked in\n2026-10-13 10:00,Sam Lee,Standard Cut,Yes\n"
    r = booksy.import_csv(db, text, TZ)
    assert r["created"] == 1 and r["error"] == 0
    assert db.scalar("SELECT arrived_at FROM appointments") is None
    # no id column -> stable synthetic id, so re-import doesn't duplicate
    assert booksy.import_csv(db, text, TZ)["unchanged"] == 1


def test_punctuality_report_and_chronic_latecomers(db):
    c = db.insert("clients", {"name": "Always Late", "phone": "1"})
    on = db.insert("clients", {"name": "On Time", "phone": "2"})
    base = datetime(2026, 10, 6, 10)
    for k, (cid, late) in enumerate([(c["id"], 15), (c["id"], 20), (c["id"], 3), (c["id"], 12), (on["id"], 0), (on["id"], 2)]):
        start = base + timedelta(days=k)
        a = db.insert("appointments", {"client_id": cid, "staff_id": 1, "service_id": 1, "start_at": start,
                                       "duration_min": 40, "price": 38, "status": "completed"})
        punctuality.check_in(db, a["id"], start + timedelta(minutes=late))
    db.insert("appointments", {"client_id": on["id"], "staff_id": 1, "service_id": 1, "start_at": base + timedelta(days=9),
                               "duration_min": 40, "price": 38, "status": "no_show"})
    r = punctuality.shop_report(db, date(2026, 10, 1), date(2026, 10, 31))
    assert r["tracked_arrivals"] == 6 and r["late_count"] == 3
    assert r["on_time_share"] == pytest.approx(0.5)
    assert r["chair_minutes_lost_to_lateness"] == 47
    assert r["no_shows"] == 1 and r["chair_minutes_lost_to_no_shows"] == 40
    assert [x["name"] for x in r["chronic_latecomers"]] == ["Always Late"]
    p = punctuality.client_punctuality(db, c["id"])
    assert p["chronic"] and p["late_count"] == 3 and p["worst_minutes_late"] == 20
    assert not punctuality.client_punctuality(db, on["id"])["chronic"]


def test_cannot_check_in_cancelled_appointment(db):
    from app.erp import ErpError
    cl = db.insert("clients", {"name": "X"})
    a = db.insert("appointments", {"client_id": cl["id"], "staff_id": 1, "service_id": 1, "start_at": datetime(2026, 10, 13, 10),
                                   "duration_min": 40, "price": 38, "status": "cancelled"})
    with pytest.raises(ErpError):
        punctuality.check_in(db, a["id"])


def test_check_in_and_db_defaults_use_shop_local_time(db):
    """Regression: the server clock is often UTC, but appointments are stored in shop-local time."""
    from app.config import shop_now
    cl = db.insert("clients", {"name": "Now"})
    start = shop_now().replace(second=0, microsecond=0) - timedelta(minutes=12)
    a = db.insert("appointments", {"client_id": cl["id"], "staff_id": 1, "service_id": 1, "start_at": start,
                                   "duration_min": 40, "price": 38, "status": "booked"})
    assert abs((a["created_at"] - shop_now()).total_seconds()) < 60          # Postgres now() default is shop-local
    late = punctuality.check_in(db, a["id"])["minutes_late"]
    assert 11 <= late <= 13


def test_lateness_is_capped_at_the_appointment_length(db):
    cl = db.insert("clients", {"name": "Typo"})
    start = datetime(2026, 10, 13, 9)
    a = db.insert("appointments", {"client_id": cl["id"], "staff_id": 1, "service_id": 1, "start_at": start,
                                   "duration_min": 40, "price": 38, "status": "completed"})
    assert punctuality.check_in(db, a["id"], start + timedelta(hours=13))["minutes_late"] == 40
    r = punctuality.shop_report(db, date(2026, 10, 1), date(2026, 10, 31))
    assert r["chair_minutes_lost_to_lateness"] == 40
