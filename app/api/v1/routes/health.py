from fastapi import APIRouter
from datetime import datetime

from app.core.config import get_app_settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """gives Docker and operators a cheap liveness check."""
    return {
        "status": "healthy",
        "service": "project-swift",
        "timestamp": datetime.utcnow().isoformat(),
        "integrations": get_app_settings().public_dict(),
    }
