from typing import Iterator, Protocol

from app.ingestion.normalize import NormalizedEvent


class SourceAdapter(Protocol):
    name: str

    def fetch(self) -> Iterator[NormalizedEvent]: ...
