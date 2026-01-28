# app/services/ocr.py
import base64
import os
import re
import time
from typing import Optional

import requests
from PIL import Image
from openai import OpenAI
from app.utils.logger import logger  # 导入日志器

# ---------------- Config ----------------
OCR_BACKEND = (os.getenv("OCR_BACKEND", "auto") or "auto").lower()
logger.info(f"OCR service initialized with backend: {OCR_BACKEND}")

# Mathpix
_MATHPIX_APP_ID = os.getenv("MATHPIX_APP_ID")
_MATHPIX_APP_KEY = os.getenv("MATHPIX_APP_KEY")
_MATHPIX_ENDPOINT = os.getenv("MATHPIX_ENDPOINT", "https://api.mathpix.com/v3/text")

if _MATHPIX_APP_ID and _MATHPIX_APP_KEY:
    logger.info("Mathpix credentials configured")
else:
    logger.warning("Mathpix credentials not configured")

# OpenAI
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
_OPENAI_MODEL_VISION = os.getenv("OPENAI_OCR_MODEL", "gpt-5.2")
_client = OpenAI(api_key=_OPENAI_API_KEY)

logger.info(f"OpenAI Vision model: {_OPENAI_MODEL_VISION}")


# ---------------- Helpers ----------------
def _img_to_b64(img_path: str) -> str:
    logger.debug(f"Converting image to base64: {img_path}")
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _validate_backend(name: str) -> str:
    name = (name or "").lower()
    if name not in ("auto", "mathpix", "openai"):
        logger.warning(f"Unknown OCR backend '{name}', defaulting to 'openai'")
        return "openai"
    return name


def _looks_math_heavy(pil_img: Image.Image) -> bool:
    # 非严格启发式：尺寸较大/草稿概率高的先走 mathpix
    w, h = pil_img.size
    is_math = min(w, h) >= 600
    logger.debug(f"Image size: {w}x{h}, looks math-heavy: {is_math}")
    return is_math


# ---------------- Backends ----------------
def _mathpix_image_to_text(
    img_path: str, timeout_s: int = 30, max_retries: int = 2
) -> str:
    logger.info(f"Starting Mathpix OCR for image: {img_path}")

    if not (_MATHPIX_APP_ID and _MATHPIX_APP_KEY):
        logger.error("Mathpix credentials not configured")
        raise RuntimeError("MATHPIX_APP_ID / MATHPIX_APP_KEY not set")

    headers = {
        "app_id": _MATHPIX_APP_ID,
        "app_key": _MATHPIX_APP_KEY,
        "Content-type": "application/json",
    }
    payload = {
        "src": f"data:image/png;base64,{_img_to_b64(img_path)}",
        "formats": ["latex_styled", "text"],
        "ocr": ["math", "text"],
        "include_line_data": False,
        "confidence": True,
    }

    for attempt in range(max_retries + 1):
        try:
            logger.debug(f"Mathpix API call attempt {attempt + 1}/{max_retries + 1}")
            resp = requests.post(
                _MATHPIX_ENDPOINT, json=payload, headers=headers, timeout=timeout_s
            )
            resp.raise_for_status()

            data = resp.json()
            latex = (data.get("latex_styled") or "").strip()
            text = (data.get("text") or "").strip()

            result = latex if latex else text
            logger.info(f"Mathpix OCR successful, extracted {len(result)} characters")
            return result

        except requests.exceptions.Timeout:
            logger.warning(f"Mathpix API timeout on attempt {attempt + 1}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"Mathpix API HTTP error: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Mathpix API error: {str(e)}")

        if attempt < max_retries:
            sleep_time = 0.8 * (attempt + 1)
            logger.debug(f"Retrying Mathpix in {sleep_time} seconds...")
            time.sleep(sleep_time)
        else:
            logger.error("Mathpix OCR failed after all retries")
            raise

    return ""


def _openai_image_to_text(img_path: str, max_retries: int = 2) -> str:
    logger.info(f"Starting OpenAI Vision OCR for image: {img_path}")

    if not _OPENAI_API_KEY:
        logger.error("OpenAI API key not configured")
        raise RuntimeError("OPENAI_API_KEY not set")

    b64 = _img_to_b64(img_path)
    system_prompt = (
        "You are an expert OCR and visual analyzer for STEM assignments.\n"
        "Your task: Extract content from the image for grading purposes.\n\n"
        "Rules:\n"
        "1. TEXT & MATH: Transcribe text and formulas EXACTLY as seen. "
        "Use inline LaTeX for math (e.g., $x^2$). Do not solve the problems.\n"
        "2. CHARTS & GRAPHS: If the image contains charts, graphs, or diagrams:\n"
        "   - Describe the type (e.g., 'Linear graph of Voltage vs Current').\n"
        "   - Extract axis labels, units, and key data trends (e.g., 'slope is positive', 'intercept at 0').\n"
        "   - Describe structural diagrams clearly (e.g., 'Circuit with battery and two resistors in series').\n"
        "3. FORMAT: Return plain text. Keep the layout logical."
    )

    for attempt in range(max_retries + 1):
        try:
            logger.debug(
                f"OpenAI Vision API call attempt {attempt + 1}/{max_retries + 1}"
            )

            resp = _client.chat.completions.create(
                model=_OPENAI_MODEL_VISION,
                temperature=1,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Extract text from this exam page image.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                        ],
                    },
                ],
            )

            content = (resp.choices[0].message.content or "").strip()
            logger.info(
                f"OpenAI Vision OCR successful, extracted {len(content)} characters"
            )
            return content

        except Exception as e:
            logger.error(f"OpenAI Vision API error on attempt {attempt + 1}: {str(e)}")

            if attempt < max_retries:
                sleep_time = 0.8 * (attempt + 1)
                logger.debug(f"Retrying OpenAI Vision in {sleep_time} seconds...")
                time.sleep(sleep_time)
            else:
                logger.error("OpenAI Vision OCR failed after all retries")
                raise

    return ""


# ---------------- Public API ----------------
def image_to_text(img_path: str, force_backend: Optional[str] = None) -> str:
    """
    统一入口：根据 OCR_BACKEND 选择实现。
    - auto: 简单启发式（大尺寸 → mathpix；否则 openai）
    - mathpix: 强制 Mathpix
    - openai: 强制 OpenAI (GPT-5/mini)
    - img_path: 图片路径
    - force_backend: 强制指定后端 ('openai' 或 'mathpix')，忽略自动判断逻辑
    """
    logger.info(f"Starting OCR process for image: {img_path} (force_backend={force_backend})")

    # 如果强制指定了后端，直接使用；否则使用配置默认值
    backend = _validate_backend(force_backend if force_backend else OCR_BACKEND)

    try:
        img = Image.open(img_path).convert("RGB")
        logger.debug(f"Image loaded successfully, size: {img.size}")
    except Exception as e:
        logger.error(f"Failed to load image: {str(e)}")
        raise

    # 只有在未强制指定且默认配置为 auto 时，才启用自动判断
    if not force_backend and backend == "auto":
        if _looks_math_heavy(img):
            backend = "mathpix"
            logger.info("Auto-selected Mathpix backend (image looks math-heavy)")
        else:
            backend = "openai"
            logger.info("Auto-selected OpenAI backend")

    if backend == "mathpix":
        try:
            text = _mathpix_image_to_text(img_path)
            if text.strip():
                return text
            else:
                logger.warning("Mathpix returned empty text, falling back to OpenAI")
                return _openai_image_to_text(img_path)
        except Exception as e:
            logger.warning(f"Mathpix failed: {str(e)}, falling back to OpenAI")
            return _openai_image_to_text(img_path)

    # backend == "openai"
    return _openai_image_to_text(img_path)
