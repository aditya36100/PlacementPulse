import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.db import (
    acquire_instance_lock,
    get_all_placements,
    get_backfill_state_summary,
    get_placements_count,
    init_db,
    release_instance_lock,
)
from app.logos import fetch_logo
from app.telegram_client import start_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    lock_fd = None
    try:
        lock_fd = acquire_instance_lock()
        init_db()
        asyncio.create_task(start_listener())
        yield
    finally:
        if lock_fd is not None:
            release_instance_lock(lock_fd)


app = FastAPI(title="PlacementPulse", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/placements")
def api_placements():
    return get_all_placements()


@app.get("/api/status")
def api_status():
    return {
        "placements_count": get_placements_count(),
        "backfill_state": get_backfill_state_summary(),
    }


@app.get("/api/logo")
def api_logo(d: str):
    path = fetch_logo(d)
    if not path:
        raise HTTPException(404, "no logo found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


app.mount("/", StaticFiles(directory="static", html=True), name="static")
