from typing import Iterator, Protocol

from sqlalchemy.orm import Session

from app.ingestion.logging_util import FetchContext
from app.ingestion.normalize import NormalizedEvent


class SourceAdapter(Protocol):
    name: str

    def fetch(
        self,
        session: Session,
        ctx: FetchContext | None = None,
    ) -> Iterator[NormalizedEvent]: ...
