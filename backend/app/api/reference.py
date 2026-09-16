from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import require_bot_service_or_human_viewer, require_viewer
from app.schemas.post_condition import PostConditionResponse
from app.services import reference as reference_service

router = APIRouter(tags=["reference"])


@router.get(
    "/post-conditions",
    response_model=list[PostConditionResponse],
    dependencies=[Depends(require_bot_service_or_human_viewer)],
)
async def get_post_conditions(
    stronghold_level: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await reference_service.get_post_conditions(db, stronghold_level)


@router.get("/building-types", dependencies=[Depends(require_viewer)])
async def get_building_types(db: AsyncSession = Depends(get_db)):
    return await reference_service.get_building_types(db)


@router.get("/member-roles", dependencies=[Depends(require_viewer)])
async def get_member_roles():
    return await reference_service.get_member_roles()
