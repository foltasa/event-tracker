from typing import Iterator, Protocol

from sqlalchemy.orm import Session

from app.ingestion.normalize import NormalizedEvent


class SourceAdapter(Protocol):
    name: str

    def fetch(self, session: Session) -> Iterator[NormalizedEvent]: ...
