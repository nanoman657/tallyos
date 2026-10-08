"""
Booksy connector: bring Booksy bookings into TallyOS so the forecast, the
growth loop and the punctuality report see what people actually booked,
whether they showed up, and when they arrived.

Three ways in, all funnelling through `upsert_appointment`:

  1. Partner API pull   `BooksyApi.list_appointments` (cron / "Sync now")
  2. Webhooks           Booksy POSTs created / modified / cancelled
                        notifications; we re-fetch the appointment from the
                        API when credentials are configured, else use the
                        payload as sent.
  3. CSV import         an appointments export, for shops without partner
                        API access.

IMPORTANT -- unverified field names. Booksy's partner API is invite-only and
its documentation isn't public, so the field names below (FIELD_PATHS,
STATUS_MAP, endpoint paths) are best guesses built to be tolerant: each
attribute is looked up under several likely names. Check them against the
partner docs (or a real webhook payload in Settings > Booksy > recent events)
and adjust FIELD_PATHS / the BOOKSY_* env vars; nothing else needs to change.
"""

import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable, List, Optional
from zoneinfo import ZoneInfo

from . import erp
from .config import Settings
from .db import Db

SOURCE = "booksy"

# Candidate locations for each attribute, tried in order ("a.b" = nested, "a.0.b" = list index).
FIELD_PATHS = {
    "id": ["appointment_uid", "appointment_id", "id", "uid"],
    "start": ["booked_from", "start", "start_time", "starts_at", "datetime", "subbookings.0.booked_from"],
    "end": ["booked_till", "end", "end_time", "ends_at", "subbookings.0.booked_till"],
    "status": ["status", "appointment_status", "state"],
    "arrived": ["checked_in_at", "check_in_time", "customer_arrived_at", "arrived_at", "check_in.created"],
    "created": ["created", "created_at", "booked_at"],
    "price": ["total_price", "total", "price", "service_price", "subbookings.0.service.price", "service.price"],
    "customer_id": ["customer.id", "customer.customer_id", "client.id", "customer_id", "customer_card_id"],
    "customer_name": ["customer.full_name", "customer.name", "client.name", "customer_name", "client_name"],
    "customer_first": ["customer.first_name", "client.first_name"],
    "customer_last": ["customer.last_name", "client.last_name"],
    "customer_phone": ["customer.cell_phone", "customer.phone", "client.phone", "customer_phone", "phone"],
    "customer_email": ["customer.email", "client.email", "customer_email", "email"],
    "service_id": ["service.id", "subbookings.0.service.id", "service_id"],
    "service_name": ["service.name", "subbookings.0.service.name", "service_name"],
    "staff_id": ["staffer.id", "staff.id", "resource.id", "subbookings.0.staffer.id", "staffer_id", "staff_id"],
    "staff_name": ["staffer.name", "staff.name", "resource.name", "subbookings.0.staffer.name", "staffer_name", "staff_name"],
}

# Booksy status -> TallyOS status. Word forms plus single-letter codes as some
# Booksy payloads abbreviate them (unverified -- extend as you see real values).
STATUS_MAP = {
    "booked": "booked", "accepted": "booked", "confirmed": "booked", "pending": "booked", "waiting": "booked",
    "a": "booked", "w": "booked", "p": "booked", "modified": "booked", "created": "booked",
    "finished": "completed", "completed": "completed", "done": "completed", "f": "completed",
    "no_show": "no_show", "noshow": "no_show", "no-show": "no_show", "no show": "no_show", "n": "no_show",
    "cancelled": "cancelled", "canceled": "cancelled", "rejected": "cancelled", "declined": "cancelled",
    "c": "cancelled", "r": "cancelled", "d": "cancelled",
}


class BooksyError(ValueError):
    pass


@dataclass
class BooksyAppointment:
    external_id: str
    start_at: datetime
    end_at: Optional[datetime]
    status: str
    arrived_at: Optional[datetime]
    created_at: Optional[datetime]
    price: Optional[float]
    customer_id: Optional[str]
    customer_name: str
    customer_phone: Optional[str]
    customer_email: Optional[str]
    service_id: Optional[str]
    service_name: Optional[str]
    staff_id: Optional[str]
    staff_name: Optional[str]


# ------------------------------------------------------------------ parsing helpers
def _pick(obj: Any, paths: Iterable[str]) -> Any:
    for path in paths:
        cur = obj
        for part in path.split("."):
            if isinstance(cur, list):
                cur = cur[int(part)] if part.isdigit() and int(part) < len(cur) else None
            elif isinstance(cur, dict):
                cur = cur.get(part)
            else:
                cur = None
            if cur is None:
                break
        if cur not in (None, ""):
            return cur
    return None


def _to_local(value: Any, tz: ZoneInfo) -> Optional[datetime]:
    """Parse ISO / epoch / common formats; aware times are converted to shop-local wall clock."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz)
    else:
        s = str(value).strip().replace("Z", "+00:00")
        dt = None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %I:%M %p",
                        "%m/%d/%y %I:%M %p", "%m/%d/%y %H:%M"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise BooksyError(f"Unrecognised date/time: {value!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz).replace(tzinfo=None)
    return dt


def _money(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, dict):          # {"amount": 38, ...} style
        value = value.get("amount") or value.get("value")
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    return float(cleaned) if cleaned not in ("", "-", ".") else None


def _phone_key(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 7 else None


def map_status(raw: Any) -> str:
    key = str(raw or "booked").strip().lower()
    return STATUS_MAP.get(key, "booked")


def normalize(raw: dict, tz: ZoneInfo) -> BooksyAppointment:
    """Booksy appointment JSON -> BooksyAppointment (tolerant of naming differences)."""
    ext_id = _pick(raw, FIELD_PATHS["id"])
    start = _to_local(_pick(raw, FIELD_PATHS["start"]), tz)
    if ext_id is None or start is None:
        raise BooksyError("Appointment needs an id and a start time")
    name = _pick(raw, FIELD_PATHS["customer_name"]) or " ".join(
        p for p in (_pick(raw, FIELD_PATHS["customer_first"]), _pick(raw, FIELD_PATHS["customer_last"])) if p)
    return BooksyAppointment(
        external_id=str(ext_id), start_at=start,
        end_at=_to_local(_pick(raw, FIELD_PATHS["end"]), tz),
        status=map_status(_pick(raw, FIELD_PATHS["status"])),
        arrived_at=_to_local(_pick(raw, FIELD_PATHS["arrived"]), tz),
        created_at=_to_local(_pick(raw, FIELD_PATHS["created"]), tz),
        price=_money(_pick(raw, FIELD_PATHS["price"])),
        customer_id=(str(v) if (v := _pick(raw, FIELD_PATHS["customer_id"])) is not None else None),
        customer_name=name or "Booksy client",
        customer_phone=_pick(raw, FIELD_PATHS["customer_phone"]),
        customer_email=_pick(raw, FIELD_PATHS["customer_email"]),
        service_id=(str(v) if (v := _pick(raw, FIELD_PATHS["service_id"])) is not None else None),
        service_name=_pick(raw, FIELD_PATHS["service_name"]),
        staff_id=(str(v) if (v := _pick(raw, FIELD_PATHS["staff_id"])) is not None else None),
        staff_name=_pick(raw, FIELD_PATHS["staff_name"]),
    )


# ------------------------------------------------------------------ matching + upsert
def _match_client(db: Db, a: BooksyAppointment, fallback_client_id: Optional[int] = None) -> dict:
    client = None
    if a.customer_id:
        client = db.one("SELECT * FROM clients WHERE external_source = %s AND external_id = %s", [SOURCE, a.customer_id])
    key = _phone_key(a.customer_phone)
    if not client and key:
        # Same person who signed up from a Google Ad -> their Booksy booking credits that campaign.
        client = db.one("SELECT * FROM clients WHERE right(regexp_replace(coalesce(phone,''), '\\D', '', 'g'), 10) = %s "
                        "ORDER BY id LIMIT 1", [key])
    if not client and a.customer_email:
        client = db.one("SELECT * FROM clients WHERE lower(email) = lower(%s) ORDER BY id LIMIT 1", [a.customer_email])
    if not client and fallback_client_id:
        # No usable identifier (e.g. a CSV row with just a name): keep whoever this booking already belongs to.
        client = db.one("SELECT * FROM clients WHERE id = %s", [fallback_client_id])
    if not client:
        return db.insert("clients", {
            "name": a.customer_name, "phone": a.customer_phone, "email": a.customer_email,
            "created_at": a.created_at or a.start_at, "source": SOURCE,
            "external_source": SOURCE if a.customer_id else None, "external_id": a.customer_id,
        })
    if a.customer_id and not client.get("external_id"):
        client = db.update("clients", client["id"], {"external_source": SOURCE, "external_id": a.customer_id})
    return client


def _match_service(db: Db, a: BooksyAppointment) -> dict:
    svc = None
    if a.service_id:
        svc = db.one("SELECT * FROM services WHERE external_id = %s", [a.service_id])
    if not svc and a.service_name:
        svc = db.one("SELECT * FROM services WHERE lower(name) = lower(%s) ORDER BY active DESC, id LIMIT 1", [a.service_name])
    if not svc and not a.service_name:
        svc = db.one("SELECT * FROM services WHERE active ORDER BY id LIMIT 1")
    minutes = int((a.end_at - a.start_at).total_seconds() // 60) if a.end_at and a.end_at > a.start_at else 40
    if not svc:
        svc = db.insert("services", {"name": a.service_name or "Booksy service", "price": a.price or 0.01,
                                     "duration_min": minutes, "external_id": a.service_id})
    elif a.service_id and not svc.get("external_id"):
        svc = db.update("services", svc["id"], {"external_id": a.service_id})
    return svc


def _match_staff(db: Db, a: BooksyAppointment) -> dict:
    staff = None
    if a.staff_id:
        staff = db.one("SELECT * FROM staff WHERE external_id = %s", [a.staff_id])
    if not staff and a.staff_name:
        staff = db.one("SELECT * FROM staff WHERE lower(name) = lower(%s) ORDER BY active DESC, id LIMIT 1", [a.staff_name])
    if not staff and not a.staff_name:
        staff = db.one("SELECT * FROM staff WHERE active AND role = 'barber' ORDER BY id LIMIT 1")
    if not staff:
        staff = db.insert("staff", {"name": a.staff_name or "Booksy barber", "role": "barber", "external_id": a.staff_id})
    elif a.staff_id and not staff.get("external_id"):
        staff = db.update("staff", staff["id"], {"external_id": a.staff_id})
    return staff


def upsert_appointment(db: Db, a: BooksyAppointment) -> str:
    """Create or update the TallyOS appointment mirroring a Booksy booking. Returns created|updated|unchanged."""
    existing = db.one("SELECT * FROM appointments WHERE external_source = %s AND external_id = %s", [SOURCE, a.external_id])
    client = _match_client(db, a, existing["client_id"] if existing else None)
    service, staff = _match_service(db, a), _match_staff(db, a)
    minutes = int((a.end_at - a.start_at).total_seconds() // 60) if a.end_at and a.end_at > a.start_at else service["duration_min"]
    price = a.price if a.price is not None else service["price"]

    status = a.status
    if existing and existing["status"] == "completed" and status == "booked":
        status = "completed"      # checked out in TallyOS; Booksy just hasn't caught up
    fields = {"client_id": client["id"], "staff_id": staff["id"], "service_id": service["id"],
              "start_at": a.start_at, "duration_min": minutes, "price": price, "status": status}
    if a.arrived_at:
        fields["arrived_at"] = a.arrived_at   # never clear an in-app check-in with a missing value

    if existing:
        changed = {k: v for k, v in fields.items() if existing.get(k) != v}
        appt = db.update("appointments", existing["id"], changed) if changed else existing
        result = "updated" if changed else "unchanged"
    else:
        appt = db.insert("appointments", {**fields, "external_source": SOURCE, "external_id": a.external_id,
                                          "created_at": a.created_at or datetime.now()})
        result = "created"

    # Finished in Booksy and not checked out here -> book the revenue so finance stays complete.
    if status == "completed" and not db.one("SELECT id FROM sales WHERE appointment_id = %s", [appt["id"]]):
        erp.record_sale(db, client_id=client["id"], staff_id=staff["id"], appointment_id=appt["id"],
                        items=[{"kind": "service", "ref_id": service["id"], "qty": 1, "unit_price": price}],
                        payment_method="booksy", sold_at=a.start_at + timedelta(minutes=minutes))
    return result


def _log(db: Db, kind: str, action: Optional[str], external_id: Optional[str], payload: Any,
         result: Optional[str], error: Optional[str] = None) -> None:
    db.insert("integration_events", {"source": SOURCE, "kind": kind, "action": action, "external_id": external_id,
                                     "payload": payload if isinstance(payload, (dict, list)) else {"raw": str(payload)},
                                     "result": result, "error": error})


def ingest(db: Db, raw: dict, tz: ZoneInfo, kind: str, action: Optional[str] = None) -> str:
    """Normalize + upsert one raw appointment inside a savepoint, logging the outcome either way."""
    ext = _pick(raw, FIELD_PATHS["id"])
    try:
        with db.conn.transaction():
            result = upsert_appointment(db, normalize(raw, tz))
        _log(db, kind, action or "upsert", str(ext) if ext is not None else None, raw, result)
        return result
    except Exception as exc:
        _log(db, kind, action or "upsert", str(ext) if ext is not None else None, raw, "error", f"{type(exc).__name__}: {exc}")
        return "error"


# ------------------------------------------------------------------ partner API
class BooksyApi:
    """Minimal REST client. Endpoint paths and query params are env-configurable (see config.BooksySettings)."""

    def __init__(self, settings: Settings):
        b = settings.booksy
        if not (b.api_url and b.api_token and b.business_id):
            raise BooksyError("Booksy API is not configured (BOOKSY_API_URL, BOOKSY_API_TOKEN, BOOKSY_BUSINESS_ID)")
        self.cfg = b

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = self.cfg.api_url.rstrip("/") + path.format(business_id=self.cfg.business_id)
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {self.cfg.api_token}", "Accept": self.cfg.accept_header,
            "User-Agent": "TallyOS/0.1"})
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode() or "null")

    @staticmethod
    def _items(payload: Any) -> List[dict]:
        if isinstance(payload, list):
            return payload
        for key in ("appointments", "results", "data", "items"):
            if isinstance(payload, dict) and isinstance(payload.get(key), list):
                return payload[key]
        return []

    def list_appointments(self, start: date, end: date, max_pages: int = 50) -> List[dict]:
        out: List[dict] = []
        for page in range(1, max_pages + 1):
            payload = self._get(self.cfg.appointments_path, {
                self.cfg.param_from: start.isoformat(), self.cfg.param_till: end.isoformat(),
                "page": page, "per_page": 100})
            items = self._items(payload)
            out.extend(items)
            if len(items) < 100:
                break
        return out

    def get_appointment(self, external_id: str) -> dict:
        payload = self._get(self.cfg.appointment_path.replace("{appointment_id}", urllib.parse.quote(str(external_id))))
        return payload.get("appointment", payload) if isinstance(payload, dict) else payload


def sync(db: Db, api: BooksyApi, tz: ZoneInfo, start: date, end: date) -> dict:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "error": 0}
    for raw in api.list_appointments(start, end):
        counts[ingest(db, raw, tz, "api_sync")] += 1
    summary = {"window": [start.isoformat(), end.isoformat()], **counts}
    db.execute("""INSERT INTO integration_state (source, last_sync_at, last_sync_summary) VALUES (%s, now(), %s)
                  ON CONFLICT (source) DO UPDATE SET last_sync_at = now(), last_sync_summary = EXCLUDED.last_sync_summary""",
               [SOURCE, json.dumps(summary)])
    return summary


def handle_webhook(db: Db, body: dict, tz: ZoneInfo, api: Optional[BooksyApi]) -> str:
    """Booksy notifies created / modified / cancelled; treat the payload as a hint and re-fetch when we can."""
    action = str(body.get("action") or body.get("event") or "modified").lower()
    raw = body.get("appointment") if isinstance(body.get("appointment"), dict) else None
    ext_id = _pick(raw or {}, FIELD_PATHS["id"]) or body.get("appointment_id") or body.get("appointment_uid")
    if api and ext_id is not None:
        try:
            raw = api.get_appointment(str(ext_id))
        except Exception as exc:  # fall back to the payload; record why
            _log(db, "webhook", action, str(ext_id), body, "refetch_failed", f"{type(exc).__name__}: {exc}")
    if raw is None:
        if "cancel" in action and ext_id is not None:
            n = db.execute("UPDATE appointments SET status = 'cancelled' WHERE external_source = %s AND external_id = %s "
                           "AND status = 'booked'", [SOURCE, str(ext_id)])
            _log(db, "webhook", action, str(ext_id), body, "updated" if n else "unchanged")
            return "updated" if n else "unchanged"
        _log(db, "webhook", action, str(ext_id) if ext_id else None, body, "error", "No appointment data and no API to fetch it")
        return "error"
    if "cancel" in action and not _pick(raw, FIELD_PATHS["status"]):
        raw = {**raw, "status": "cancelled"}
    return ingest(db, raw, tz, "webhook", action)


# ------------------------------------------------------------------ CSV import
CSV_ALIASES = {
    "id": ["appointment id", "booking id", "id", "appointment number"],
    "datetime": ["start", "start date", "starts at", "booked from", "date and time", "appointment date and time"],
    "date": ["date", "appointment date", "day"],
    "time": ["time", "start time", "hour", "appointment time"],
    "end": ["end", "end time", "booked till", "finish time"],
    "duration": ["duration", "duration (min)", "duration min", "length"],
    "client": ["client", "customer", "client name", "customer name", "name"],
    "phone": ["phone", "client phone", "customer phone", "mobile", "phone number", "cell phone"],
    "email": ["email", "client email", "customer email"],
    "service": ["service", "service name", "services"],
    "staff": ["staff", "staffer", "employee", "barber", "staff member", "provider"],
    "price": ["price", "total", "amount", "value", "service price"],
    "status": ["status", "appointment status"],
    "arrived": ["check-in", "check in", "checked in", "check-in time", "arrived", "arrival time", "arrived at"],
}


def _csv_col(headers: List[str], key: str) -> Optional[str]:
    norm = {h.strip().lower(): h for h in headers}
    return next((norm[a] for a in CSV_ALIASES[key] if a in norm), None)


def import_csv(db: Db, text: str, tz: ZoneInfo) -> dict:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = reader.fieldnames or []
    col = {k: _csv_col(headers, k) for k in CSV_ALIASES}
    if not (col["datetime"] or col["date"]) or not col["client"]:
        raise BooksyError("CSV needs a date (or start) column and a client column. Found: " + ", ".join(headers))
    counts = {"rows": 0, "created": 0, "updated": 0, "unchanged": 0, "error": 0}
    errors = []
    for i, row in enumerate(reader, start=2):
        counts["rows"] += 1
        get = lambda k: (row.get(col[k]) or "").strip() if col[k] else ""   # noqa: E731
        try:
            when = get("datetime") or f"{get('date')} {get('time')}".strip()
            start = _to_local(when, tz)
            def at_day(v):   # arrival/end columns may hold just a time, or a yes/no flag (no time -> unknown)
                if not v or not re.search(r"\d{1,2}:\d{2}", v):
                    return None
                if re.fullmatch(r"\d{1,2}:\d{2}(\s?[AaPp][Mm])?", v):
                    return _to_local(f"{start.date().isoformat()} {v}", tz)
                return _to_local(v, tz)
            end = at_day(get("end"))
            if not end and get("duration"):
                end = start + timedelta(minutes=int(float(re.sub(r"[^\d.]", "", get("duration")) or 0)))
            ext_id = get("id") or "csv-" + hashlib.sha1(
                f"{start.isoformat()}|{get('client').lower()}|{get('service').lower()}".encode()).hexdigest()[:16]
            raw = {"id": ext_id, "booked_from": start.isoformat(), "booked_till": end.isoformat() if end else None,
                   "status": get("status") or ("finished" if start < datetime.now() else "accepted"),
                   "checked_in_at": (a.isoformat() if (a := at_day(get("arrived"))) else None),
                   "total_price": get("price") or None,
                   "customer": {"name": get("client"), "phone": get("phone") or None, "email": get("email") or None},
                   "service": {"name": get("service") or None}, "staffer": {"name": get("staff") or None}}
        except Exception as exc:
            counts["error"] += 1
            errors.append({"row": i, "error": str(exc)})
            continue
        result = ingest(db, raw, tz, "csv_import")
        counts[result] += 1
        if result == "error":
            errors.append({"row": i, "error": db.scalar(
                "SELECT error FROM integration_events WHERE source = %s ORDER BY id DESC LIMIT 1", [SOURCE])})
    return {**counts, "errors": errors[:20], "columns": {k: v for k, v in col.items() if v}}


def status(db: Db, settings: Settings) -> dict:
    b = settings.booksy
    state = db.one("SELECT * FROM integration_state WHERE source = %s", [SOURCE]) or {}
    return {
        "api_configured": bool(b.api_url and b.api_token and b.business_id),
        "webhook_configured": bool(b.webhook_secret),
        "webhook_path": "/api/integrations/booksy/webhook",
        "last_sync_at": state.get("last_sync_at"), "last_sync_summary": state.get("last_sync_summary") or {},
        "booksy_appointments": db.scalar("SELECT count(*) FROM appointments WHERE external_source = %s", [SOURCE]),
        "with_arrival_time": db.scalar("SELECT count(*) FROM appointments WHERE arrived_at IS NOT NULL"),
        "recent_events": db.all("""SELECT id, kind, action, external_id, received_at, result, error
                                   FROM integration_events WHERE source = %s ORDER BY id DESC LIMIT 20""", [SOURCE]),
    }


def sync_booksy_if_configured(db: Db, settings: Settings) -> Optional[dict]:
    """Default-window sync when API credentials exist; a no-op otherwise. Never raises (logs instead)."""
    try:
        api = BooksyApi(settings)
    except BooksyError:
        return None
    today = date.today()
    try:
        return sync(db, api, ZoneInfo(settings.shop_timezone), today - timedelta(days=settings.booksy.sync_days_back),
                    today + timedelta(days=settings.booksy.sync_days_ahead))
    except Exception as exc:
        _log(db, "api_sync", "sync", None, {}, "error", f"{type(exc).__name__}: {exc}")
        return {"error": str(exc)}
