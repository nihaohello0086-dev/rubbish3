# app/main.py
import os

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.utils.logger import logger
from app.api.routes.system import router as system_router
from app.api.routes.grade_single import router as grade_single_router
from app.api.routes.grade_batch import router as grade_batch_router
from app.api.routes.grade_strict import router as grade_strict_router
from app.api.routes.grade_batch_strict import router as grade_batch_strict_router

# -----------------------------
# App init & config
# -----------------------------
load_dotenv()
APP_NAME = os.getenv("APP_NAME", "AI Grading System")
APP_VERSION = os.getenv("APP_VERSION", "10.6.0")

logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
logger.info(
    f"Environment: OpenAI API Key configured: {bool(os.getenv('OPENAI_API_KEY'))}"
)

app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="AI-powered assignment grading system with document processing",
)

# -----------------------------
# Request logging middleware
# -----------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有HTTP请求"""
    import time

    start_time = time.time()

    # 记录请求信息
    logger.info(f"Request started: {request.method} {request.url.path}")
    logger.debug(f"Request headers: {dict(request.headers)}")

    try:
        response = await call_next(request)
        process_time = time.time() - start_time

        # 记录响应信息
        logger.info(
            f"Request completed: {request.method} {request.url.path} "
            f"- Status: {response.status_code} - Time: {process_time:.3f}s"
        )

        response.headers["X-Process-Time"] = str(process_time)
        return response

    except Exception as e:
        process_time = time.time() - start_time
        logger.error(
            f"Request failed: {request.method} {request.url.path} "
            f"- Error: {str(e)} - Time: {process_time:.3f}s",
            exc_info=True,
        )
        raise


# -----------------------------
# CORS
# -----------------------------
_allow_origins = os.getenv("ALLOW_ORIGINS", "*")
logger.info(f"CORS configured for origins: {_allow_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        [o.strip() for o in _allow_origins.split(",")] if _allow_origins else ["*"]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Global exception handlers
# -----------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Request validation error: {exc.errors()}")
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "field": " -> ".join(str(x) for x in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
        )

    return JSONResponse(
        status_code=422,
        content={"error": "Request validation failed", "details": errors},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP exception: {exc.status_code} - {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


# -----------------------------
# Routers
# -----------------------------
app.include_router(system_router)
app.include_router(grade_single_router)
app.include_router(grade_batch_router)
app.include_router(grade_strict_router)
app.include_router(grade_batch_strict_router)


# -----------------------------
# Development server entry point
# -----------------------------
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting development server")

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )
