# app/services/file_service.py
import os
import tempfile
import asyncio
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Optional, cast

from fastapi import UploadFile, HTTPException, status
from starlette.datastructures import UploadFile as StarletteUploadFile, Headers

from app.services import ocr, document_processor
from app.utils.logger import logger

# -----------------------------
# Configuration (local to this module)
# -----------------------------
_ALLOWED_FILE_TYPES = tuple(
    s.strip()
    for s in os.getenv(
        "ALLOWED_FILE_TYPES",
        "image/png,image/jpeg,image/webp,application/pdf,text/plain,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/msword",
    ).split(",")
    if s.strip()
)
_MAX_FILE_SIZE_MB = float(os.getenv("MAX_FILE_SIZE_MB", "10"))
_MAX_CONCURRENT_FILE_PROCESS = int(os.getenv("MAX_CONCURRENT_FILE_PROCESS", "5"))

def _validate_file(file: UploadFile, content: bytes) -> None:
    """Validate file type and size."""
    logger.debug(
        f"[file_service] Validating file: {file.filename}, "
        f"Type: {file.content_type}, Size: {len(content)} bytes"
    )

    if file.content_type not in _ALLOWED_FILE_TYPES:
        logger.warning(
            f"[file_service] Rejected file with unsupported type: {file.content_type}"
        )
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type: {file.content_type}. "
                f"Supported types: {', '.join(_ALLOWED_FILE_TYPES)}"
            ),
        )

    size_mb = len(content) / (1024 * 1024)
    if size_mb > _MAX_FILE_SIZE_MB:
        logger.warning(f"[file_service] Rejected file too large: {size_mb:.1f}MB")
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {size_mb:.1f}MB (max: {_MAX_FILE_SIZE_MB}MB)",
        )

    logger.debug(f"[file_service] File validation passed: {file.filename}")


async def process_file(file: UploadFile, is_question_file: bool = False) -> str:
    """
    Process uploaded file and extract text content.
    内部的耗时操作(OCR/PDF解析)现在通过 asyncio.to_thread 运行，
    以免阻塞 Event Loop，从而实现真正的并发。
    Args:
        file: The uploaded file object
        is_question_file: If True, non-text/word files (PDFs, Images) will be forced to use OpenAI Vision OCR.
    """
    logger.info(f"[file_service] Processing file: {file.filename} ({file.content_type})")

    content = await file.read()
    _validate_file(file, content)

    suffix = Path(file.filename).suffix.lower() if file.filename else ".tmp"
    tmp_path: Optional[str] = None

    try:
        # Write to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(content)
            logger.debug(f"[file_service] Created temporary file: {tmp_path}")

        # ---------------------------------------------------------
        # 核心逻辑修改：
        # 1. 优先处理 TXT 和 Word (无论是否为题目，都尽量提取原生文本)
        # ---------------------------------------------------------
        if file.content_type == "text/plain":
            text = await asyncio.to_thread(document_processor.txt_to_text, tmp_path)
            logger.info(f"[file_service] Extracted {len(text)} chars from text file")
            
        elif file.content_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            text = await asyncio.to_thread(document_processor.docx_to_text, tmp_path)
            logger.info(f"[file_service] Extracted {len(text)} chars from Word document")

        # ---------------------------------------------------------
        # 2. 如果是题目 (且不是上面的 TXT/Word)，则强制使用 OpenAI Vision
        #    覆盖范围：PDF 和 所有图片格式
        # ---------------------------------------------------------
        elif is_question_file:
            logger.info(f"[file_service] Processing Question File ({file.content_type}) with Vision Strategy")
            
            # Case A: PDF -> 转图 -> OpenAI
            if file.content_type == "application/pdf":
                img_path = await asyncio.to_thread(document_processor.pdf_to_image_file, tmp_path)
                try:
                    text = await asyncio.to_thread(ocr.image_to_text, img_path, force_backend="openai")
                    logger.info(f"[file_service] Vision OCR extracted {len(text)} chars from PDF Question")
                finally:
                    if os.path.exists(img_path):
                        await asyncio.to_thread(os.unlink, img_path)

            # Case B: 图片 -> 直接 OpenAI (强制)
            elif file.content_type in ("image/png", "image/jpeg", "image/webp"):
                text = await asyncio.to_thread(ocr.image_to_text, tmp_path, force_backend="openai")
                logger.info(f"[file_service] Vision OCR extracted {len(text)} chars from Image Question")
            
            else:
                # 理论上 _ALLOWED_FILE_TYPES 会拦截，但作为兜底
                logger.warning(f"Unsupported question file type: {file.content_type}, trying fallback")
                raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")

        # ---------------------------------------------------------
        # 3. 普通文件处理 (学生作业/参考答案) - 保持原有逻辑
        # ---------------------------------------------------------
        elif file.content_type == "application/pdf":
            # PDF 默认提取文本
            text = await asyncio.to_thread(document_processor.pdf_to_text, tmp_path)
            logger.info(f"[file_service] Extracted {len(text)} chars from PDF")

        elif file.content_type in ("image/png", "image/jpeg", "image/webp"):
            # 图片默认自动选择 (Auto: Mathpix/OpenAI)
            text = await asyncio.to_thread(ocr.image_to_text, tmp_path)
            logger.info(f"[file_service] OCR extracted {len(text)} chars from image")

        else:
            logger.error(f"[file_service] Cannot process file type: {file.content_type}")
            raise HTTPException(status_code=415, detail=f"Cannot process file type: {file.content_type}")

        # ---------------------------------------------------------

        if not text.strip():
            logger.warning(f"[file_service] No text content found in file: {file.filename}")
            raise HTTPException(status_code=422, detail="No text content found in file")

        return text.strip()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[file_service] File processing failed for {file.filename}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"File processing failed: {str(e)}")
    finally:
        if tmp_path and Path(tmp_path).exists():
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass


def _guess_mime_from_suffix(suffix: str) -> Optional[str]:
    """Guess MIME type by file suffix for ZIP entries."""
    suffix = (suffix or "").lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    return mime_map.get(suffix)


async def extract_texts_from_zip(zip_bytes: bytes) -> List[Dict[str, str]]:
    """
    Parse a ZIP into a list of {'file': name, 'text': extracted_text} or
    {'file': name, 'error': error_message}. 
    [修改说明] 使用 Semaphore + gather 实现并发处理
    """
    from zipfile import ZipFile, is_zipfile
    from fastapi import UploadFile as FastAPIUploadFile

    if not is_zipfile(BytesIO(zip_bytes)):
        raise HTTPException(
            status_code=400, detail="students_zip is not a valid ZIP file"
        )

    # 1. 创建信号量
    sem = asyncio.Semaphore(_MAX_CONCURRENT_FILE_PROCESS)
    tasks = []

    # 2. 定义单个文件的处理任务
    async def _process_zip_entry(name: str, content: bytes, mime: str):
        async with sem:  # 限制并发数
            try:
                # 构造 UploadFile 对象
                upload = StarletteUploadFile(
                    file=BytesIO(content),
                    filename=name,
                    headers=Headers({"content-type": mime}),
                )
                upload_for_proc = cast(FastAPIUploadFile, upload)
                
                # 调用 process_file (内部已经是线程安全的并发调用)
                text = await process_file(upload_for_proc)
                return {"file": name, "text": text}
            except Exception as e:
                logger.warning(f"[file_service] Failed to process ZIP entry {name}: {e}")
                return {"file": name, "error": str(e)}

    # 3. 读取 Zip 并分发任务
    with ZipFile(BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith("/") or name.startswith("__MACOSX/"):
                continue

            suffix = Path(name).suffix.lower()
            content_type = _guess_mime_from_suffix(suffix)
            if not content_type or content_type not in _ALLOWED_FILE_TYPES:
                logger.warning(f"[file_service] Skipping unsupported ZIP entry: {name}")
                continue

            data = zf.read(name)
            if (len(data) / (1024 * 1024)) > _MAX_FILE_SIZE_MB:
                logger.warning(f"[file_service] ZIP entry too large, skipped: {name}")
                continue

            # 创建任务但不等待
            tasks.append(_process_zip_entry(name, data, content_type))

    # 4. 并发执行所有任务
    logger.info(f"[file_service] Starting concurrent extraction for {len(tasks)} zip entries...")
    results = await asyncio.gather(*tasks)
    return list(results)


async def extract_texts_from_files(files: List[UploadFile]) -> List[Dict[str, str]]:
    """
    Process multiple UploadFile objects concurrently.
    """
    # 1. 创建信号量
    sem = asyncio.Semaphore(_MAX_CONCURRENT_FILE_PROCESS)
    tasks = []

    # 2. 定义单个任务
    async def _process_upload_file(f: UploadFile):
        filename = str(getattr(f, "filename", "") or "unknown")
        async with sem:
            try:
                text = await process_file(f)
                return {"file": filename, "text": str(text or "")}
            except Exception as e:
                logger.warning(f"[file_service] Failed to process student file {filename}: {e}")
                return {"file": filename, "error": str(e)}

    # 3. 创建并执行任务
    for f in (files or []):
        tasks.append(_process_upload_file(f))
    
    logger.info(f"[file_service] Starting concurrent extraction for {len(tasks)} files...")
    results = await asyncio.gather(*tasks)
    return list(results)