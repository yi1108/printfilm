from fastapi import APIRouter

from app.api.v1 import generation

router = APIRouter()
router.include_router(generation.router)
