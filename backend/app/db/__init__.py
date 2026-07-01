import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


def run_migrations() -> None:
    logger.info("Applying database migrations…")
    command.upgrade(Config(str(_ALEMBIC_INI)), "head")
    logger.info("Database migrations up to date")
