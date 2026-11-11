"""Reusable, account-owned graph templates without project media/task references."""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.models_printfilm_studio import PrintfilmStudioRecipe
from app.printfilm_studio import ensure_enabled
from app.printfilm_studio.canvas.codec import decode_canvas_document
from app.printfilm_studio.canvas.service import get_project

router = APIRouter(prefix='/printfilm-studio', tags=['printfilm-studio-recipes'])
PORTABLE_DATA = {'label', 'name', 'text', 'prompt', 'hint', 'editor', 'modelId', 'ratio', 'resolution', 'duration', 'count', 'children', 'scene'}


def normalize_recipe(raw):
    if len(json.dumps(raw, ensure_ascii=False)) > 1_000_000:
        raise ValueError('配方超过 1MB 限制')
    doc = decode_canvas_document(raw)
    if not 1 <= len(doc['nodes']) <= 200:
        raise ValueError('配方需要 1 到 200 个节点')
    ids = {node['id'] for node in doc['nodes']}
    nodes = []
    for node in doc['nodes']:
        data = {key: value for key, value in node['data'].items() if key in PORTABLE_DATA}
        if isinstance(data.get('children'), list):
            data['children'] = [child for child in data['children'] if child in ids]
        clean = {key: node[key] for key in ('id', 'type', 'position', 'style', 'width', 'height') if key in node}
        clean['data'] = data
        parent = node.get('parentId')
        if parent:
            if parent not in ids or parent == node['id']:
                raise ValueError('配方分组引用无效')
            clean.update(parentId=parent, extent='parent')
        nodes.append(clean)
    parents = {n['id']: n.get('parentId') for n in nodes}
    for node in nodes:
        seen = set()
        parent = node['id']
        while parent:
            if parent in seen:
                raise ValueError('配方分组不能循环引用')
            seen.add(parent)
            parent = parents.get(parent)
    edges = [{key: edge[key] for key in ('id', 'source', 'target', 'sourceHandle', 'targetHandle', 'type') if key in edge} for edge in doc['edges']]
    return decode_canvas_document({'nodes': nodes, 'edges': edges})


class RecipeInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    document: dict


def recipe_out(row):
    return {'id': row.id, 'name': row.name, 'document': row.document}


@router.get('/projects/{project_id}/recipes')
async def list_recipes(project_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await get_project(db, project_id, user)
    rows = (await db.scalars(select(PrintfilmStudioRecipe).where(PrintfilmStudioRecipe.user_id == user.id).order_by(PrintfilmStudioRecipe.created_at.desc()).limit(200))).all()
    return {'recipes': [recipe_out(row) for row in rows]}


@router.post('/projects/{project_id}/recipes')
async def create_recipe(project_id: int, body: RecipeInput, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    await get_project(db, project_id, user)
    try:
        document = normalize_recipe(body.document)
    except (ValueError, TypeError, OverflowError) as error:
        raise HTTPException(422, str(error)) from error
    row = PrintfilmStudioRecipe(user_id=user.id, name=body.name.strip() or '未命名配方', document=document)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return recipe_out(row)


@router.delete('/recipes/{recipe_id}')
async def delete_recipe(recipe_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    ensure_enabled()
    row = await db.get(PrintfilmStudioRecipe, recipe_id)
    if not row or row.user_id != user.id:
        raise HTTPException(404, '配方不存在')
    await db.delete(row)
    await db.commit()
    return {'ok': True}
