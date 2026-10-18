"""Shared annotated types for response schemas."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def _assume_utc(value: datetime) -> datetime:
    # The app stores every timestamp in UTC. PostgreSQL (timestamptz) returns aware values,
    # but SQLite returns naive ones; without an offset, browsers would read them as local time.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


UTCDateTime = Annotated[datetime, AfterValidator(_assume_utc)]
