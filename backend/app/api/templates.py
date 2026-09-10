from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Template
from app.schemas import TemplateDetailOut, TemplateOut

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateDetailOut])
async def list_templates(db: AsyncSession = Depends(get_db)) -> list[Template]:
    result = await db.execute(
        select(Template).where(Template.is_active.is_(True)).order_by(Template.sort_order)
    )
    return list(result.scalars().all())


@router.get("/{template_id}", response_model=TemplateDetailOut)
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)) -> Template:
    tpl = await db.get(Template, template_id)
    if not tpl or not tpl.is_active:
        raise HTTPException(status_code=404, detail="模板不存在")
    return tpl
