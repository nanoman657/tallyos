"""Booksy integration endpoints plus arrival check-in and the punctuality report."""

import hmac
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import booksy, punctuality
from ..config import get_settings
from ..db import Db, get_db

router = APIRouter(prefix="/api")
MAX_CSV_BYTES = 5_000_000


def _tz() -> ZoneInfo:
    return ZoneInfo(get_settings().shop_timezone)


def _api_or_none() -> Optional[booksy.BooksyApi]:
    try:
        return booksy.BooksyApi(get_settings())
    except booksy.BooksyError:
        return None


@router.get("/integrations/booksy")
def booksy_status(db: Db = Depends(get_db)):
    return booksy.status(db, get_settings())


@router.post("/integrations/booksy/sync")
def booksy_sync(days_back: Optional[int] = None, days_ahead: Optional[int] = None, db: Db = Depends(get_db)):
    api = _api_or_none()
    if not api:
        raise HTTPException(400, "Booksy API isn't configured on the server. Use CSV import, or set BOOKSY_API_URL, "
                                 "BOOKSY_API_TOKEN and BOOKSY_BUSINESS_ID.")
    cfg = get_settings().booksy
    today = date.today()
    try:
        return booksy.sync(db, api, _tz(), today - timedelta(days=days_back or cfg.sync_days_back),
                           today + timedelta(days=days_ahead or cfg.sync_days_ahead))
    except OSError as exc:   # network / HTTP errors from urllib
        raise HTTPException(502, f"Booksy API request failed: {exc}")


@router.post("/integrations/booksy/webhook")
async def booksy_webhook(request: Request, secret: str = "", db: Db = Depends(get_db)):
    """Give Booksy this URL with ?secret=... (or send it in X-Webhook-Secret). Unsigned calls are refused."""
    expected = get_settings().booksy.webhook_secret
    if not expected:
        raise HTTPException(503, "Set BOOKSY_WEBHOOK_SECRET on the server before enabling Booksy webhooks")
    supplied = request.headers.get("x-webhook-secret") or secret
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "Bad webhook secret")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "Expected a JSON body")
    events = body if isinstance(body, list) else [body]
    results = [booksy.handle_webhook(db, e, _tz(), _api_or_none()) for e in events if isinstance(e, dict)]
    return {"received": len(results), "results": results}


@router.post("/integrations/booksy/import")
async def booksy_import(request: Request, db: Db = Depends(get_db)):
    """Body: the raw CSV text of a Booksy appointments export."""
    raw = await request.body()
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, "CSV is larger than 5 MB")
    try:
        return booksy.import_csv(db, raw.decode("utf-8-sig", errors="replace"), _tz())
    except booksy.BooksyError as exc:
        raise HTTPException(400, str(exc))


class CheckInIn(BaseModel):
    arrived_at: Optional[datetime] = None


@router.post("/appointments/{appointment_id}/checkin")
def check_in(appointment_id: int, body: CheckInIn, db: Db = Depends(get_db)):
    return punctuality.check_in(db, appointment_id, body.arrived_at)


@router.get("/punctuality")
def punctuality_report(days: int = 28, db: Db = Depends(get_db)):
    today = date.today()
    return punctuality.shop_report(db, today - timedelta(days=days), today + timedelta(days=1))
