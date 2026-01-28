# app/api/deps.py
import os
from fastapi import HTTPException, status
from app.utils.logger import logger

def require_api_key():
    """Ensure OpenAI API key is available."""
    if not os.getenv("OPENAI_API_KEY"):
        logger.error("OpenAI API key not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenAI API key not configured",
        )
    logger.debug("OpenAI API key check passed")
