"""
Pagination utilities for list endpoints.

All potentially large collections must be paginated.
Never return unbounded database query results to clients.

Usage:
    from backend.schemas_pagination import PaginationParams, PaginatedResponse

    @router.get("/posts", response_model=PaginatedResponse[PostResponse])
    def list_posts(
        pagination: PaginationParams = Depends(),
        db: Session = Depends(get_db),
    ):
        query = db.query(Post).order_by(Post.created_at.desc())
        return paginate(query, pagination)
"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field
from pydantic.generics import GenericModel

T = TypeVar("T")

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class PaginationParams(BaseModel):
    """Standard pagination query parameters injected as a Depends()."""
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Items per page (max {MAX_PAGE_SIZE})",
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size

    class Config:
        # Allow use as FastAPI dependency
        populate_by_name = True


class PageMeta(BaseModel):
    """Pagination metadata included in every list response."""
    total: int = Field(description="Total number of items across all pages")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether a next page exists")
    has_prev: bool = Field(description="Whether a previous page exists")


class PaginatedResponse(GenericModel, Generic[T]):
    """Standard paginated list response envelope."""
    items: list[T]
    meta: PageMeta


def paginate(query, params: PaginationParams) -> dict:
    """
    Apply pagination to a SQLAlchemy query and return a dict suitable for
    PaginatedResponse.

    Args:
        query: SQLAlchemy Query object (not yet fetched)
        params: PaginationParams from the request

    Returns:
        dict with 'items' and 'meta' keys
    """
    total = query.count()
    items = query.offset(params.offset).limit(params.limit).all()
    total_pages = max(1, (total + params.page_size - 1) // params.page_size)
    return {
        "items": items,
        "meta": PageMeta(
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
            has_next=params.page < total_pages,
            has_prev=params.page > 1,
        ),
    }


def pagination_params(
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        alias="page_size",
        description=f"Items per page (max {MAX_PAGE_SIZE})",
    ),
) -> PaginationParams:
    """FastAPI dependency for pagination query params."""
    return PaginationParams(page=page, page_size=page_size)
