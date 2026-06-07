from fastapi import APIRouter
from datetime import datetime

router = APIRouter()


@router.get("/health")
async def health_check():
    """gives Docker and operators a cheap liveness check."""
    return {
        "status": "healthy",
        "service": "project-swift",
        "timestamp": datetime.utcnow().isoformat(),
    }
