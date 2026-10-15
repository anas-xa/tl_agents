"""Routers contributed by feature modules. Each module appends its router here."""

from __future__ import annotations

from fastapi import APIRouter

ROUTERS: list[APIRouter] = []


def register(router: APIRouter) -> APIRouter:
    ROUTERS.append(router)
    return router
