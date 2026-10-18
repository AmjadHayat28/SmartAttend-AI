"""Reusable query parameters for list endpoints."""

from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel


class PageParams(BaseModel):
    page: int
    page_size: int
    q: str | None


def _page_params(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    q: str | None = Query(None, max_length=100, description="Free-text search"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size, q=(q or "").strip() or None)


Paging = Annotated[PageParams, Depends(_page_params)]
