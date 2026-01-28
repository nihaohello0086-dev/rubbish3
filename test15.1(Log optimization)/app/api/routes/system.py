# app/api/routes/system.py
from fastapi import APIRouter
from app.schemas import SystemStatusResponse
from app.services import document_processor
import os
from app.utils.logger import logger

router = APIRouter()

@router.get("/system-status", response_model=SystemStatusResponse)
async def system_status():
    logger.info("System status check requested")

    openai_available = bool(os.getenv("OPENAI_API_KEY"))
    mathpix_available = bool(os.getenv("MATHPIX_APP_ID") and os.getenv("MATHPIX_APP_KEY"))
    ocr_backend = os.getenv("OCR_BACKEND", "auto").lower()
    doc_capabilities = document_processor.get_processing_capabilities()

    critical_services = [openai_available]
    system_healthy = all(critical_services)

    return SystemStatusResponse(
        system_healthy=system_healthy,
        openai_available=openai_available,
        mathpix_available=mathpix_available,
        ocr_backend=ocr_backend,
        supported_file_types=(os.getenv("ALLOWED_FILE_TYPES") or "").split(","),
        max_file_size_mb=float(os.getenv("MAX_FILE_SIZE_MB", 10)),
        document_processing=doc_capabilities,
        default_rubric=["Completeness", "Method", "Final Answer", "Arithmetic", "Unit"],
        version=os.getenv("APP_VERSION", "10.6.0"),
    )
