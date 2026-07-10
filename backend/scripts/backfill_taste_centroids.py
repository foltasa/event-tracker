"""One-shot backfill: recompute per-category centroids for every user.

Idempotent — safe to re-run. Does not touch taste_facets or active_categories."""
import logging

from app.agent.memory import refresh_taste_centroids
from app.db.models import User
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("backfill_taste_centroids")


def main() -> None:
    with SessionLocal() as session:
        users = session.query(User).all()
        logger.info("Refreshing centroids for %d user(s)", len(users))
        for u in users:
            refresh_taste_centroids(session, u.id)
            session.commit()
            logger.info("user=%s categories=%s", u.id, list(u.taste_centroids.keys()))


if __name__ == "__main__":
    main()
