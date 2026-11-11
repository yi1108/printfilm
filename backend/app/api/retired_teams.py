"""Explicitly retire organization teams without deleting historical ledgers/tasks."""
from fastapi import APIRouter, Depends, HTTPException
from app.deps import get_current_user
router = APIRouter(dependencies=[Depends(get_current_user)])

@router.api_route('/teams', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
@router.api_route('/teams/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
@router.api_route('/team-invitations', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
@router.api_route('/team-invitations/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
async def retired(path: str = ''):
    raise HTTPException(status_code=410, detail='独立团队已停用，请在画布项目的分享中管理成员；生成费用由发起人支付')
