import logging
import logging.config
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_appointments, routes_calendar, routes_chat, routes_digest, routes_events, routes_feedback, routes_profile
from app.api.deps import current_user_id_middleware
from app.config import settings
from app.db.models import User
from app.db.session import SessionLocal
from app.ingestion.scheduler import create_scheduler, run_ingestion

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"}
    },
    "root": {"level": "INFO", "handlers": ["console"]},
})

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _run_migrations() -> None:
    logger.info("Applying database migrations…")
    command.upgrade(Config(_ALEMBIC_INI), "head")
    logger.info("Database migrations up to date")


def _ensure_default_user() -> None:
    user_id = settings.default_user_id
    with SessionLocal() as db:
        if db.query(User).filter_by(id=user_id).one_or_none() is not None:
            return
        db.add(User(id=user_id))
        db.commit()
        logger.info("Bootstrapped default user %r", user_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    _ensure_default_user()
    logger.info("Starting ingestion scheduler…")
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Ingestion scheduler started (daily 04:00 Europe/Berlin)")
    yield
    scheduler.shutdown(wait=False)
    logger.info("Ingestion scheduler stopped")


app = FastAPI(title="Event Tracker API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.middleware("http")(current_user_id_middleware)
app.include_router(routes_profile.router)
app.include_router(routes_events.router)
app.include_router(routes_feedback.router)
app.include_router(routes_appointments.router)
app.include_router(routes_calendar.router)
app.include_router(routes_digest.router)
app.include_router(routes_chat.router)


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
