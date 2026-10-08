"""ERP endpoints: shop, staff, services, clients, appointments, POS, inventory, expenses, finance."""

from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import erp
from ..db import Db, get_db
from ..growth.forecast import build_forecast

router = APIRouter(prefix="/api")


def _or_404(row, what="Not found"):
    if not row:
        raise HTTPException(404, what)
    return row


# ------------------------------------------------------------------ shop
class ShopIn(BaseModel):
    name: str
    address: str = ""
    open_weekdays: List[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    open_minute: int = 540
    close_minute: int = 1020
    break_minutes: int = 30
    monthly_rent: float = 0
    monthly_software: float = 0
    card_fee_rate: float = 0.03
    state_city_tax_rate: float = 0
    health_insurance_annual: float = 0
    filing_status: str = "head_of_household"


@router.get("/shop")
def get_shop(db: Db = Depends(get_db)):
    return _or_404(db.one("SELECT * FROM shop WHERE id = 1"), "Shop not set up")


@router.put("/shop")
def put_shop(body: ShopIn, db: Db = Depends(get_db)):
    if db.one("SELECT id FROM shop WHERE id = 1"):
        return db.update("shop", 1, body.model_dump())
    return db.insert("shop", {"id": 1, **body.model_dump()})


# ------------------------------------------------------------------ staff & services
class StaffIn(BaseModel):
    name: str
    role: str = "barber"
    commission_rate: float = 0
    active: bool = True


class ServiceIn(BaseModel):
    name: str
    price: float = Field(gt=0)
    duration_min: int = Field(gt=0)
    cogs: float = 0
    active: bool = True


@router.get("/staff")
def list_staff(db: Db = Depends(get_db)):
    return db.all("SELECT * FROM staff ORDER BY active DESC, name")


@router.post("/staff", status_code=201)
def create_staff(body: StaffIn, db: Db = Depends(get_db)):
    return db.insert("staff", body.model_dump())


@router.put("/staff/{staff_id}")
def update_staff(staff_id: int, body: StaffIn, db: Db = Depends(get_db)):
    return _or_404(db.update("staff", staff_id, body.model_dump()))


@router.get("/services")
def list_services(db: Db = Depends(get_db)):
    return db.all("SELECT * FROM services ORDER BY active DESC, price")


@router.post("/services", status_code=201)
def create_service(body: ServiceIn, db: Db = Depends(get_db)):
    return db.insert("services", body.model_dump())


@router.put("/services/{service_id}")
def update_service(service_id: int, body: ServiceIn, db: Db = Depends(get_db)):
    return _or_404(db.update("services", service_id, body.model_dump()))


# ------------------------------------------------------------------ clients
class ClientIn(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    source: str = "walk_in"
    sms_opt_in: bool = True
    notes: str = ""


@router.get("/clients")
def list_clients(q: str = "", limit: int = 100, db: Db = Depends(get_db)):
    return db.all(
        """SELECT c.*, v.visits, v.last_visit, v.spend, n.next_at
           FROM clients c
           LEFT JOIN (SELECT client_id, count(*) AS visits, max(start_at) AS last_visit, sum(price) AS spend
                      FROM appointments WHERE status = 'completed' GROUP BY client_id) v ON v.client_id = c.id
           LEFT JOIN (SELECT client_id, min(start_at) AS next_at FROM appointments
                      WHERE status = 'booked' AND start_at >= now() GROUP BY client_id) n ON n.client_id = c.id
           WHERE c.name ILIKE %s OR coalesce(c.phone,'') ILIKE %s OR coalesce(c.email,'') ILIKE %s
           ORDER BY v.last_visit DESC NULLS LAST, c.id DESC LIMIT %s""",
        [f"%{q}%"] * 3 + [limit],
    )


@router.post("/clients", status_code=201)
def create_client(body: ClientIn, db: Db = Depends(get_db)):
    return db.insert("clients", body.model_dump())


@router.put("/clients/{client_id}")
def update_client(client_id: int, body: ClientIn, db: Db = Depends(get_db)):
    return _or_404(db.update("clients", client_id, body.model_dump()))


@router.get("/clients/{client_id}")
def client_detail(client_id: int, db: Db = Depends(get_db)):
    client = _or_404(db.one(
        """SELECT c.*, ac.name AS campaign_name FROM clients c
           LEFT JOIN ad_campaigns ac ON ac.id = c.campaign_id WHERE c.id = %s""", [client_id]))
    client["appointments"] = db.all(
        """SELECT a.*, s.name AS service_name, st.name AS staff_name FROM appointments a
           JOIN services s ON s.id = a.service_id JOIN staff st ON st.id = a.staff_id
           WHERE a.client_id = %s ORDER BY a.start_at DESC""", [client_id])
    fc = build_forecast(db, date.today(), 30, include_clients=True)
    client["outlook"] = next((o for o in fc.clients if o.client_id == client_id), None)
    return client


# ------------------------------------------------------------------ appointments
class AppointmentIn(BaseModel):
    client_id: int
    service_id: int
    start_at: datetime
    staff_id: Optional[int] = None


class CheckoutIn(BaseModel):
    tip: float = 0
    payment_method: str = "card"
    products: List[dict] = Field(default_factory=list)   # [{product_id, qty}]


class StatusIn(BaseModel):
    status: str


@router.get("/appointments")
def list_appointments(start: date, end: Optional[date] = None, db: Db = Depends(get_db)):
    end = end or start + timedelta(days=1)
    return db.all(
        """SELECT a.*, c.name AS client_name, c.phone AS client_phone, c.source AS client_source,
                  s.name AS service_name, st.name AS staff_name
           FROM appointments a JOIN clients c ON c.id = a.client_id
           JOIN services s ON s.id = a.service_id JOIN staff st ON st.id = a.staff_id
           WHERE a.start_at >= %s AND a.start_at < %s ORDER BY a.start_at""", [start, end])


@router.get("/availability")
def get_availability(day: date, service_id: int, staff_id: Optional[int] = None, db: Db = Depends(get_db)):
    return erp.availability(db, day, service_id, staff_id)


@router.post("/appointments", status_code=201)
def create_appointment(body: AppointmentIn, db: Db = Depends(get_db)):
    return erp.book_appointment(db, body.client_id, body.service_id, body.start_at, body.staff_id)


@router.post("/appointments/{appointment_id}/checkout")
def checkout(appointment_id: int, body: CheckoutIn, db: Db = Depends(get_db)):
    return erp.complete_appointment(db, appointment_id, body.tip, body.payment_method, body.products,
                                    sold_at=datetime.now())


@router.post("/appointments/{appointment_id}/status")
def set_status(appointment_id: int, body: StatusIn, db: Db = Depends(get_db)):
    if body.status not in ("cancelled", "no_show", "booked"):
        raise HTTPException(400, "Use checkout to complete an appointment")
    appt = _or_404(db.one("SELECT * FROM appointments WHERE id = %s", [appointment_id]))
    if appt["status"] == "completed":
        raise HTTPException(409, "Appointment already checked out")
    return db.update("appointments", appointment_id, {"status": body.status})


# ------------------------------------------------------------------ point of sale
class SaleIn(BaseModel):
    client_id: Optional[int] = None
    staff_id: Optional[int] = None
    items: List[dict]                  # [{kind, ref_id, qty}]
    tip: float = 0
    payment_method: str = "card"


@router.post("/sales", status_code=201)
def create_sale(body: SaleIn, db: Db = Depends(get_db)):
    return erp.record_sale(db, **body.model_dump())


@router.get("/sales")
def list_sales(start: date, end: Optional[date] = None, db: Db = Depends(get_db)):
    end = end or start + timedelta(days=1)
    return db.all(
        """SELECT s.*, c.name AS client_name, st.name AS staff_name FROM sales s
           LEFT JOIN clients c ON c.id = s.client_id LEFT JOIN staff st ON st.id = s.staff_id
           WHERE s.sold_at >= %s AND s.sold_at < %s ORDER BY s.sold_at DESC""", [start, end])


# ------------------------------------------------------------------ inventory
class ProductIn(BaseModel):
    sku: str
    name: str
    unit_cost: float
    retail_price: Optional[float] = None
    on_hand: int = 0
    reorder_point: int = 0
    reorder_qty: int = 0


class StockIn(BaseModel):
    delta: int
    reason: str = "adjustment"


@router.get("/products")
def list_products(db: Db = Depends(get_db)):
    return db.all("SELECT *, on_hand <= reorder_point AS low FROM products ORDER BY name")


@router.post("/products", status_code=201)
def create_product(body: ProductIn, db: Db = Depends(get_db)):
    return db.insert("products", body.model_dump())


@router.post("/products/{product_id}/stock")
def move_stock(product_id: int, body: StockIn, db: Db = Depends(get_db)):
    if body.reason not in ("purchase", "usage", "adjustment"):
        raise HTTPException(400, "reason must be purchase, usage or adjustment")
    return erp.adjust_stock(db, product_id, body.delta, body.reason)


# ------------------------------------------------------------------ expenses & finance
class ExpenseIn(BaseModel):
    at: date
    category: str
    amount: float
    memo: str = ""


@router.get("/expenses")
def list_expenses(start: date, end: date, db: Db = Depends(get_db)):
    return db.all("SELECT * FROM expenses WHERE at >= %s AND at < %s ORDER BY at DESC", [start, end])


@router.post("/expenses", status_code=201)
def create_expense(body: ExpenseIn, db: Db = Depends(get_db)):
    return db.insert("expenses", body.model_dump())


@router.get("/finance/summary")
def finance(start: date, end: date, db: Db = Depends(get_db)):
    return erp.finance_summary(db, start, end)


@router.get("/dashboard")
def dashboard(db: Db = Depends(get_db)):
    today = date.today()
    shop = erp.get_shop(db)
    todays = list_appointments(today, None, db)
    sales = db.one("SELECT coalesce(sum(subtotal),0) AS revenue, coalesce(sum(tip),0) AS tips, count(*) AS tickets "
                   "FROM sales WHERE sold_at::date = %s", [today])
    fc = build_forecast(db, today, 7)
    month = erp.finance_summary(db, today.replace(day=1), today + timedelta(days=1))
    return {
        "shop": shop["name"], "today": today, "open_today": erp.is_open(shop, today),
        "appointments": todays, "sales_today": sales,
        "week_forecast": fc.days,
        "month_to_date": {k: month[k] for k in ("revenue", "operating_profit", "ad_spend", "tickets", "avg_ticket")},
        "low_stock": erp.low_stock(db),
        "new_signups_7d": db.scalar("SELECT count(*) FROM signups WHERE at >= %s", [today - timedelta(days=7)]),
    }
