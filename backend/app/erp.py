"""
Core ERP domain logic: shop hours & chair capacity, booking with conflict
checks, checkout (point of sale), inventory movements and the P&L / tax view.
Routers stay thin and call into these functions; the growth loop reuses the
capacity math so "unfilled chair time" means the same thing everywhere.
"""

from datetime import date, datetime, timedelta
from typing import List, Optional

from .db import Db
from .taxes import compute_true_take_home

SLOT_STEP_MIN = 15
LIVE_STATUSES = ("booked", "completed")


class ErpError(ValueError):
    """Business-rule violation; routers turn it into HTTP 400/409."""


# ------------------------------------------------------------------ shop & capacity
def get_shop(db: Db) -> dict:
    shop = db.one("SELECT * FROM shop WHERE id = 1")
    if not shop:
        raise ErpError("Shop is not set up yet")
    return shop


def is_open(shop: dict, day: date) -> bool:
    return day.weekday() in shop["open_weekdays"]


def active_barber_count(db: Db) -> int:
    return int(db.scalar("SELECT count(*) FROM staff WHERE active AND role = 'barber'") or 0)


def bookable_minutes(shop: dict, barbers: int, day: date) -> float:
    if not is_open(shop, day):
        return 0.0
    per_chair = shop["close_minute"] - shop["open_minute"] - shop["break_minutes"]
    return max(0.0, per_chair) * barbers


def avg_service_minutes(db: Db, as_of: date, lookback_days: int = 90) -> float:
    """Booking-mix-weighted service length; falls back to the menu average."""
    avg = db.scalar(
        """SELECT avg(duration_min) FROM appointments
           WHERE status IN ('booked','completed') AND start_at >= %s AND start_at < %s""",
        [as_of - timedelta(days=lookback_days), as_of],
    )
    if avg is None:
        avg = db.scalar("SELECT avg(duration_min) FROM services WHERE active")
    return float(avg or 40.0)


def capacity_slots(db: Db, shop: dict, day: date, avg_minutes: float, barbers: Optional[int] = None) -> float:
    barbers = active_barber_count(db) if barbers is None else barbers
    return bookable_minutes(shop, barbers, day) / avg_minutes


# ------------------------------------------------------------------ scheduling
def _overlaps(db: Db, staff_id: int, start: datetime, minutes: int, ignore_id: Optional[int] = None) -> bool:
    end = start + timedelta(minutes=minutes)
    return bool(db.scalar(
        """SELECT count(*) FROM appointments
           WHERE staff_id = %s AND status IN ('booked','completed') AND id <> %s
             AND start_at < %s AND start_at + duration_min * interval '1 minute' > %s""",
        [staff_id, ignore_id or 0, end, start],
    ))


def _within_hours(shop: dict, start: datetime, minutes: int) -> bool:
    start_min = start.hour * 60 + start.minute
    return (is_open(shop, start.date())
            and start_min >= shop["open_minute"]
            and start_min + minutes <= shop["close_minute"])


def availability(db: Db, day: date, service_id: int, staff_id: Optional[int] = None) -> List[dict]:
    """Free start times for a service on a day, per barber."""
    shop = get_shop(db)
    service = db.one("SELECT * FROM services WHERE id = %s", [service_id])
    if not service:
        raise ErpError("Unknown service")
    if not is_open(shop, day):
        return []
    barbers = db.all(
        "SELECT id, name FROM staff WHERE active AND role = 'barber'" + (" AND id = %s" if staff_id else "") + " ORDER BY id",
        [staff_id] if staff_id else [],
    )
    booked = db.all(
        """SELECT staff_id, start_at, duration_min FROM appointments
           WHERE status IN ('booked','completed') AND start_at::date = %s""",
        [day],
    )
    slots = []
    midnight = datetime.combine(day, datetime.min.time())
    for barber in barbers:
        busy = [(b["start_at"], b["start_at"] + timedelta(minutes=b["duration_min"]))
                for b in booked if b["staff_id"] == barber["id"]]
        minute = shop["open_minute"]
        while minute + service["duration_min"] <= shop["close_minute"]:
            start = midnight + timedelta(minutes=minute)
            end = start + timedelta(minutes=service["duration_min"])
            if all(end <= s or start >= e for s, e in busy):
                slots.append({"staff_id": barber["id"], "staff_name": barber["name"], "start_at": start})
            minute += SLOT_STEP_MIN
    return slots


def book_appointment(db: Db, client_id: int, service_id: int, start_at: datetime,
                     staff_id: Optional[int] = None, created_at: Optional[datetime] = None) -> dict:
    shop = get_shop(db)
    service = db.one("SELECT * FROM services WHERE id = %s AND active", [service_id])
    if not service:
        raise ErpError("Unknown or inactive service")
    if not db.one("SELECT id FROM clients WHERE id = %s", [client_id]):
        raise ErpError("Unknown client")
    minutes = service["duration_min"]
    if not _within_hours(shop, start_at, minutes):
        raise ErpError("Outside opening hours")
    if staff_id is None:
        candidates = [r["id"] for r in db.all("SELECT id FROM staff WHERE active AND role = 'barber' ORDER BY id")]
        staff_id = next((s for s in candidates if not _overlaps(db, s, start_at, minutes)), None)
        if staff_id is None:
            raise ErpError("No barber free at that time")
    elif _overlaps(db, staff_id, start_at, minutes):
        raise ErpError("That barber is already booked at that time")
    row = {
        "client_id": client_id, "staff_id": staff_id, "service_id": service_id,
        "start_at": start_at, "duration_min": minutes, "price": service["price"], "status": "booked",
    }
    if created_at:
        row["created_at"] = created_at
    return db.insert("appointments", row)


def first_free_slot(db: Db, service_id: int, earliest: date, weekdays: Optional[List[int]] = None,
                    search_days: int = 14) -> Optional[dict]:
    for offset in range(search_days):
        day = earliest + timedelta(days=offset)
        if weekdays and day.weekday() not in weekdays:
            continue
        slots = availability(db, day, service_id)
        if slots:
            return slots[0]
    return None


# ------------------------------------------------------------------ point of sale & inventory
def adjust_stock(db: Db, product_id: int, delta: int, reason: str, at: Optional[datetime] = None) -> dict:
    product = db.one("UPDATE products SET on_hand = on_hand + %s WHERE id = %s RETURNING *", [delta, product_id])
    if not product:
        raise ErpError("Unknown product")
    move = {"product_id": product_id, "qty_delta": delta, "reason": reason}
    if at:
        move["at"] = at
    db.insert("stock_moves", move)
    return product


def record_sale(db: Db, *, client_id: Optional[int], staff_id: Optional[int], items: List[dict],
                tip: float = 0.0, payment_method: str = "card", appointment_id: Optional[int] = None,
                sold_at: Optional[datetime] = None) -> dict:
    """items: [{kind: 'service'|'product', ref_id, qty}] -- prices come from the catalog."""
    if not items:
        raise ErpError("A sale needs at least one item")
    shop = get_shop(db)
    priced, subtotal, cogs = [], 0.0, 0.0
    for item in items:
        qty = int(item.get("qty", 1))
        if item["kind"] == "service":
            ref = db.one("SELECT price, cogs FROM services WHERE id = %s", [item["ref_id"]])
            price = float(item.get("unit_price") or (ref or {}).get("price", 0))
            cost = (ref or {}).get("cogs", 0.0)
        elif item["kind"] == "product":
            ref = db.one("SELECT retail_price, unit_cost, on_hand FROM products WHERE id = %s", [item["ref_id"]])
            if ref and ref["retail_price"] is None:
                raise ErpError("That product is back-bar supply and not for sale")
            if ref and ref["on_hand"] < qty:
                raise ErpError("Not enough stock")
            price, cost = (ref or {}).get("retail_price", 0.0), (ref or {}).get("unit_cost", 0.0)
        else:
            raise ErpError("Unknown item kind")
        if not ref:
            raise ErpError(f"Unknown {item['kind']} {item['ref_id']}")
        priced.append({"kind": item["kind"], "ref_id": item["ref_id"], "qty": qty, "unit_price": price, "unit_cost": cost})
        subtotal += price * qty
        cogs += cost * qty
    card_fee = round((subtotal + tip) * shop["card_fee_rate"], 2) if payment_method == "card" else 0.0
    sale = {
        "appointment_id": appointment_id, "client_id": client_id, "staff_id": staff_id,
        "subtotal": round(subtotal, 2), "tip": round(tip, 2), "card_fee": card_fee,
        "cogs": round(cogs, 2), "payment_method": payment_method,
    }
    if sold_at:
        sale["sold_at"] = sold_at
    sale = db.insert("sales", sale)
    for item in priced:
        db.insert("sale_items", {"sale_id": sale["id"], **item})
        if item["kind"] == "product":
            adjust_stock(db, item["ref_id"], -item["qty"], "sale", sold_at)
    sale["items"] = priced
    return sale


def complete_appointment(db: Db, appointment_id: int, tip: float = 0.0, payment_method: str = "card",
                         products: Optional[List[dict]] = None, sold_at: Optional[datetime] = None) -> dict:
    appt = db.one("SELECT * FROM appointments WHERE id = %s", [appointment_id])
    if not appt:
        raise ErpError("Unknown appointment")
    if appt["status"] != "booked":
        raise ErpError(f"Appointment is already {appt['status']}")
    db.update("appointments", appointment_id, {"status": "completed"})
    items = [{"kind": "service", "ref_id": appt["service_id"], "qty": 1, "unit_price": appt["price"]}]
    items += [{"kind": "product", "ref_id": p["product_id"], "qty": p.get("qty", 1)} for p in products or []]
    return record_sale(db, client_id=appt["client_id"], staff_id=appt["staff_id"], items=items, tip=tip,
                       payment_method=payment_method, appointment_id=appointment_id,
                       sold_at=sold_at or appt["start_at"] + timedelta(minutes=appt["duration_min"]))


def low_stock(db: Db) -> List[dict]:
    return db.all("SELECT * FROM products WHERE on_hand <= reorder_point ORDER BY name")


# ------------------------------------------------------------------ finance
def finance_summary(db: Db, start: date, end: date) -> dict:
    """P&L for [start, end) plus an annualized tax waterfall (via taxes.py)."""
    shop = get_shop(db)
    days = max(1, (end - start).days)
    s = db.one(
        """SELECT coalesce(sum(subtotal),0) AS revenue, coalesce(sum(tip),0) AS tips,
                  coalesce(sum(card_fee),0) AS card_fees, coalesce(sum(cogs),0) AS cogs,
                  count(*) AS tickets
           FROM sales WHERE sold_at >= %s AND sold_at < %s""",
        [start, end],
    )
    service_revenue = db.scalar(
        """SELECT coalesce(sum(si.unit_price * si.qty),0) FROM sale_items si JOIN sales s ON s.id = si.sale_id
           WHERE si.kind = 'service' AND s.sold_at >= %s AND s.sold_at < %s""", [start, end])
    commissions = db.scalar(
        """SELECT coalesce(sum(si.unit_price * si.qty * st.commission_rate),0)
           FROM sale_items si JOIN sales s ON s.id = si.sale_id JOIN staff st ON st.id = s.staff_id
           WHERE si.kind = 'service' AND s.sold_at >= %s AND s.sold_at < %s""", [start, end])
    ad_spend = db.scalar("SELECT coalesce(sum(cost),0) FROM ad_metrics_daily WHERE date >= %s AND date < %s", [start, end])
    other = db.all("""SELECT category, sum(amount) AS amount FROM expenses
                      WHERE at >= %s AND at < %s GROUP BY category ORDER BY category""", [start, end])
    other_total = sum(r["amount"] for r in other)
    fixed = (shop["monthly_rent"] + shop["monthly_software"]) * 12 * days / 365

    gross_profit = s["revenue"] - s["cogs"] - s["card_fees"] - commissions
    operating_profit = gross_profit - fixed - ad_spend - other_total
    annualized = operating_profit * 365 / days
    taxes = compute_true_take_home(annualized, shop["state_city_tax_rate"],
                                   shop["health_insurance_annual"], shop["filing_status"])
    scale = days / 365
    return {
        "start": start, "end": end, "days": days, "tickets": s["tickets"],
        "revenue": s["revenue"], "service_revenue": service_revenue, "product_revenue": s["revenue"] - service_revenue,
        "tips": s["tips"], "card_fees": s["card_fees"], "cogs": s["cogs"], "commissions": commissions,
        "gross_profit": gross_profit, "rent_and_software": fixed, "ad_spend": ad_spend,
        "other_expenses": other, "operating_profit": operating_profit,
        "taxes": {k: v * scale for k, v in taxes.items()},
        "annualized_take_home": taxes["true_take_home"],
        "avg_ticket": s["revenue"] / s["tickets"] if s["tickets"] else 0.0,
    }
