from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.config import Settings, get_settings
from storymaker_api.db import get_session

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    env: str


@router.get("/healthz")
async def healthz(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from None
    return HealthResponse(status="ok", env=settings.app_env)
