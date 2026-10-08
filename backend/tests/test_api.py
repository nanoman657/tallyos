from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app


def next_open_day():
    d = date.today() + timedelta(days=1)
    while d.weekday() not in (1, 2, 3, 4, 5):
        d += timedelta(days=1)
    return d


def test_public_signup_then_verified_first_booking(db):
    with TestClient(app) as client:
        r = client.post("/api/public/signup", json={"name": "Ad Visitor", "phone": "5551234", "gclid": "G-1"})
        assert r.status_code == 201
        signup = r.json()
        assert signup["attribution"] == "gclid_pending"     # click report not synced yet

        day = next_open_day()
        slot = client.get(f"/api/public/availability?day={day}&service_id=1").json()[0]
        booking = {"signup_id": signup["signup_id"], "service_id": 1, "start_at": slot["start_at"]}

        assert client.post("/api/public/book", json={**booking, "contact": "wrong-number"}).status_code == 404
        assert client.post("/api/public/book", json={**booking, "contact": "5551234"}).status_code == 201
        assert client.post("/api/public/book", json={**booking, "contact": "5551234"}).status_code == 409


def test_public_signup_requires_contact(db):
    with TestClient(app) as client:
        assert client.post("/api/public/signup", json={"name": "Nobody"}).status_code == 400


def test_booking_conflict_is_409(db):
    with TestClient(app) as client:
        c = client.post("/api/clients", json={"name": "A", "phone": "1"}).json()
        start = f"{next_open_day()}T10:00:00"
        assert client.post("/api/appointments", json={"client_id": c["id"], "service_id": 1, "start_at": start}).status_code == 201
        r = client.post("/api/appointments", json={"client_id": c["id"], "service_id": 1, "start_at": start})
        assert r.status_code == 409 and "barber" in r.json()["detail"]


def test_campaign_budget_guardrail(db):
    db.insert("ad_campaigns", {"name": "x", "daily_budget": 10, "status": "ENABLED", "external_id": "ext-9"})
    db.conn.commit()
    with TestClient(app) as client:
        cid = client.get("/api/growth/campaigns").json()[0]["id"]
        assert client.patch(f"/api/growth/campaigns/{cid}", json={"daily_budget": 500}).status_code == 400
        assert client.patch(f"/api/growth/campaigns/{cid}", json={"daily_budget": 15}).json()["daily_budget"] == 15


def test_dashboard_and_forecast_render_on_empty_shop(db):
    with TestClient(app) as client:
        assert client.get("/api/dashboard").status_code == 200
        fc = client.get("/api/growth/forecast?days=7").json()
        assert len(fc["days"]) == 7


def test_booksy_webhook_requires_configured_secret(db, monkeypatch):
    from app.config import get_settings
    payload = {"action": "created", "appointment": {"id": "w1", "booked_from": f"{next_open_day()}T10:00:00",
                                                     "customer": {"name": "Hook", "phone": "555"}, "service": {"name": "Standard Cut"}}}
    with TestClient(app) as client:
        monkeypatch.setattr(get_settings().booksy, "webhook_secret", "")
        assert client.post("/api/integrations/booksy/webhook", json=payload).status_code == 503
        monkeypatch.setattr(get_settings().booksy, "webhook_secret", "s3cret")
        assert client.post("/api/integrations/booksy/webhook?secret=nope", json=payload).status_code == 401
        r = client.post("/api/integrations/booksy/webhook", json=payload, headers={"X-Webhook-Secret": "s3cret"})
        assert r.status_code == 200 and r.json()["results"] == ["created"]
        status = client.get("/api/integrations/booksy").json()
        assert status["booksy_appointments"] == 1 and status["recent_events"][0]["result"] == "created"


def test_booksy_sync_without_credentials_is_400(db):
    with TestClient(app) as client:
        assert client.post("/api/integrations/booksy/sync").status_code == 400


def test_csv_upload_checkin_and_punctuality_endpoints(db):
    day = next_open_day()
    csv_text = f"Date,Time,Client,Phone,Service,Status\n{day},10:00,Late Larry,555-1,Standard Cut,Accepted\n"
    with TestClient(app) as client:
        r = client.post("/api/integrations/booksy/import", content=csv_text, headers={"content-type": "text/csv"})
        assert r.status_code == 200 and r.json()["created"] == 1
        appt = client.get(f"/api/appointments?start={day}").json()[0]
        assert appt["external_source"] == "booksy" and appt["minutes_late"] is None
        r = client.post(f"/api/appointments/{appt['id']}/checkin", json={"arrived_at": f"{day}T10:17:00"})
        assert r.json()["minutes_late"] == 17
        assert client.get(f"/api/appointments?start={day}").json()[0]["minutes_late"] == 17
        report = client.get("/api/punctuality?days=60")
        assert report.status_code == 200 and {"on_time_share", "chronic_latecomers"} <= set(report.json())
        detail = client.get(f"/api/clients/{appt['client_id']}").json()
        assert detail["punctuality"]["late_count"] == 1
        bad = client.post("/api/integrations/booksy/import", content="x,y\n1,2\n", headers={"content-type": "text/csv"})
        assert bad.status_code == 400
