import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.api import routes_calendar, routes_digest, routes_events, routes_feedback, routes_profile
from app.api.deps import current_user_id_middleware
from app.ingestion.scheduler import create_scheduler, run_ingestion

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Ingestion scheduler started (daily 04:00 Europe/Berlin)")
    yield
    scheduler.shutdown(wait=False)
    logger.info("Ingestion scheduler stopped")


app = FastAPI(title="Event Tracker API", lifespan=lifespan)
app.middleware("http")(current_user_id_middleware)
app.include_router(routes_profile.router)
app.include_router(routes_events.router)
app.include_router(routes_feedback.router)
app.include_router(routes_calendar.router)
app.include_router(routes_digest.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ingestion/run", status_code=200)
def trigger_ingestion() -> dict:
    try:
        report = run_ingestion()
        return {"inserted": report.inserted, "updated": report.updated, "skipped": report.skipped}
    except Exception as exc:
        logger.exception("Manual ingestion run failed")
        raise HTTPException(status_code=500, detail="Ingestion failed") from exc
