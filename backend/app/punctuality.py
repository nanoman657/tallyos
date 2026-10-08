"""
Who shows up late, how late, and what it costs in chair time.

Arrival time comes from Booksy (check-in timestamp, if the account exposes
one), a CSV column, or the "Arrived" button in the app. A client counts as
late when they arrive more than LATE_GRACE_MIN after their booked start.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from .db import Db
from .erp import ErpError

LATE_GRACE_MIN = 5
CHRONIC_MIN_VISITS = 3          # need this many tracked arrivals before labelling someone
CHRONIC_LATE_SHARE = 0.5        # late to at least half of them

# minutes late, floored at 0 (early arrivals don't earn credit)
LATE_SQL = "greatest(0, extract(epoch FROM (a.arrived_at - a.start_at)) / 60.0)"


def check_in(db: Db, appointment_id: int, at: Optional[datetime] = None) -> dict:
    appt = db.one("SELECT * FROM appointments WHERE id = %s", [appointment_id])
    if not appt:
        raise ErpError("Unknown appointment")
    if appt["status"] in ("cancelled", "no_show"):
        raise ErpError(f"Appointment is {appt['status']}")
    appt = db.update("appointments", appointment_id, {"arrived_at": at or datetime.now()})
    appt["minutes_late"] = minutes_late(appt)
    return appt


def minutes_late(appt: dict) -> Optional[int]:
    if not appt.get("arrived_at"):
        return None
    return max(0, round((appt["arrived_at"] - appt["start_at"]).total_seconds() / 60))


def client_punctuality(db: Db, client_id: int) -> dict:
    r = db.one(
        f"""SELECT count(*) FILTER (WHERE a.arrived_at IS NOT NULL) AS tracked,
                   count(*) FILTER (WHERE {LATE_SQL} > %s) AS late,
                   avg({LATE_SQL}) FILTER (WHERE {LATE_SQL} > %s) AS avg_late_when_late,
                   max({LATE_SQL}) AS worst,
                   count(*) FILTER (WHERE a.status = 'no_show') AS no_shows,
                   count(*) FILTER (WHERE a.status IN ('completed','no_show')) AS past_visits
            FROM appointments a WHERE a.client_id = %s""",
        [LATE_GRACE_MIN, LATE_GRACE_MIN, client_id],
    )
    tracked = r["tracked"] or 0
    late_share = r["late"] / tracked if tracked else None
    return {
        "tracked_arrivals": tracked, "late_count": r["late"], "late_share": late_share,
        "avg_minutes_late_when_late": round(r["avg_late_when_late"], 1) if r["avg_late_when_late"] else None,
        "worst_minutes_late": round(r["worst"]) if r["worst"] is not None else None,
        "no_shows": r["no_shows"],
        "no_show_rate": r["no_shows"] / r["past_visits"] if r["past_visits"] else None,
        "chronic": tracked >= CHRONIC_MIN_VISITS and (late_share or 0) >= CHRONIC_LATE_SHARE,
        "grace_minutes": LATE_GRACE_MIN,
    }


def shop_report(db: Db, start: date, end: date) -> dict:
    s = db.one(
        f"""SELECT count(*) FILTER (WHERE a.status IN ('completed','no_show')) AS past,
                   count(*) FILTER (WHERE a.arrived_at IS NOT NULL) AS tracked,
                   count(*) FILTER (WHERE {LATE_SQL} > %s) AS late,
                   coalesce(sum({LATE_SQL}) FILTER (WHERE {LATE_SQL} > %s), 0) AS minutes_lost,
                   avg({LATE_SQL}) FILTER (WHERE {LATE_SQL} > %s) AS avg_late,
                   count(*) FILTER (WHERE a.status = 'no_show') AS no_shows,
                   coalesce(sum(a.duration_min) FILTER (WHERE a.status = 'no_show'), 0) AS no_show_minutes
            FROM appointments a WHERE a.start_at >= %s AND a.start_at < %s""",
        [LATE_GRACE_MIN] * 3 + [start, end],
    )
    by_weekday = db.all(
        f"""SELECT extract(isodow FROM a.start_at)::int - 1 AS weekday,
                   count(*) FILTER (WHERE a.arrived_at IS NOT NULL) AS tracked,
                   count(*) FILTER (WHERE {LATE_SQL} > %s) AS late
            FROM appointments a WHERE a.start_at >= %s AND a.start_at < %s GROUP BY 1 ORDER BY 1""",
        [LATE_GRACE_MIN, start, end],
    )
    chronic = db.all(
        f"""SELECT c.id, c.name, c.phone, count(*) AS tracked,
                   count(*) FILTER (WHERE {LATE_SQL} > %s) AS late,
                   round(avg({LATE_SQL}) FILTER (WHERE {LATE_SQL} > %s)) AS avg_late
            FROM appointments a JOIN clients c ON c.id = a.client_id
            WHERE a.arrived_at IS NOT NULL AND a.start_at >= %s
            GROUP BY c.id
            HAVING count(*) >= %s AND count(*) FILTER (WHERE {LATE_SQL} > %s) >= %s * count(*)
            ORDER BY late DESC, avg_late DESC NULLS LAST LIMIT 15""",
        [LATE_GRACE_MIN, LATE_GRACE_MIN, end - timedelta(days=180), CHRONIC_MIN_VISITS, LATE_GRACE_MIN, CHRONIC_LATE_SHARE],
    )
    tracked = s["tracked"] or 0
    return {
        "start": start, "end": end, "grace_minutes": LATE_GRACE_MIN,
        "past_appointments": s["past"], "tracked_arrivals": tracked,
        "on_time_share": (tracked - s["late"]) / tracked if tracked else None,
        "late_count": s["late"], "avg_minutes_late_when_late": round(s["avg_late"], 1) if s["avg_late"] else None,
        "chair_minutes_lost_to_lateness": round(s["minutes_lost"]),
        "no_shows": s["no_shows"], "no_show_rate": s["no_shows"] / s["past"] if s["past"] else None,
        "chair_minutes_lost_to_no_shows": s["no_show_minutes"],
        "late_share_by_weekday": [
            {"weekday": r["weekday"], "tracked": r["tracked"], "late_share": r["late"] / r["tracked"] if r["tracked"] else None}
            for r in by_weekday],
        "chronic_latecomers": chronic,
    }
