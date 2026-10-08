"""
FastAPI application: JSON API under /api, the mobile web app (PWA) at /.

    uvicorn app.main:app --reload

Set TALLYOS_LOOP_HOURS=24 to have the server run the sense-think-act cycle
on its own every N hours (or call `python -m app.cli run-loop` from cron).
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .ads import get_platform
from .config import get_settings
from .db import connect, init_schema, session
from .erp import ErpError
from .growth.loop import run_cycle
from .routers import erp as erp_routes
from .routers import growth as growth_routes

log = logging.getLogger("tallyos")


async def _loop_scheduler(hours: float) -> None:
    while True:
        await asyncio.sleep(hours * 3600)
        try:
            settings = get_settings()
            with session() as db:
                result = await asyncio.to_thread(run_cycle, db, get_platform(db, settings), settings)
            log.info("growth loop run %s: %s", result["run_id"], [d["action"] for d in result["think"]["decisions"]])
        except Exception:
            log.exception("scheduled growth loop failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    init_schema(conn)
    conn.close()
    task = None
    hours = float(os.environ.get("TALLYOS_LOOP_HOURS", "0") or 0)
    if hours > 0:
        task = asyncio.create_task(_loop_scheduler(hours))
    yield
    if task:
        task.cancel()


app = FastAPI(title="TallyOS", version="0.1.0", lifespan=lifespan)
app.include_router(erp_routes.router)
app.include_router(growth_routes.router)


@app.exception_handler(ErpError)
async def erp_error(_: Request, exc: ErpError):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.get("/api/health")
def health():
    return {"ok": True, "ads_backend": get_settings().ads_backend}


frontend = Path(get_settings().frontend_dir).resolve()
if frontend.is_dir():
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
