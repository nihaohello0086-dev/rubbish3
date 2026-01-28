# app/services/strict_rubric_service.py
from __future__ import annotations

import json
import os
from typing import List, Tuple, Optional, Dict, Any

from fastapi import HTTPException, status
from openai import OpenAI

from app.utils.logger import logger

# 独立一个用于 rubric 解析的模型（也可以和评分同一个）
_RUBRIC_MODEL = os.getenv("OPENAI_RUBRIC_MODEL", "gpt-5")
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def parse_strict_rubric(
    strict_rubric: str,
) -> Tuple[List[str], str, Optional[List[float]]]:
    """
    解析“严格模式”下的富 Rubric JSON 字符串。

    预期格式（示例）：
    [
      {
        "name": "Completeness",
        "description": "检查是否回答了题目要求的所有小问...",
        "weight": 2.0,                # 可选
        "levels": {                   # 可选
          "1.0": "所有小问都作答，步骤完整",
          "0.5": "大部分作答但有缺失",
          "0.0": "只作答部分或严重缺失"
        }
      },
      ...
    ]

    返回：
        rubric_names:   ["Completeness", "Method", ...]
        rubric_block:   一大段给 LLM 的文本说明，用于 prompt
        base_weights:   若 JSON 中有 weight，则返回对应列表；否则返回 None
    """

    try:
        data = json.loads(strict_rubric)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse strict_rubric JSON: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strict_rubric must be a valid JSON array.",
        )

    if not isinstance(data, list) or not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strict_rubric must be a non-empty JSON array.",
        )

    rubric_names: List[str] = []
    lines: List[str] = []
    base_weights: List[float] = []
    any_weight = False

    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "").strip()
        desc = str(item.get("description") or "").strip()
        levels = item.get("levels") or {}

        if not name:
            continue

        rubric_names.append(name)

        header = f"{idx}. {name}"
        body_lines = []
        if desc:
            body_lines.append(f"   Description: {desc}")

        if isinstance(levels, dict) and levels:
            body_lines.append("   Scoring guide:")
            for k, v in sorted(levels.items(), key=lambda kv: kv[0], reverse=True):
                body_lines.append(f"     - Score {k}: {v}")

        if body_lines:
            lines.append(header + "\n" + "\n".join(body_lines))
        else:
            lines.append(header)

        w = item.get("weight")
        if isinstance(w, (int, float)):
            base_weights.append(float(w))
            any_weight = True
        else:
            base_weights.append(0.0)

    if not rubric_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strict_rubric contains no valid items with 'name'.",
        )

    rubric_block = "\n".join(lines)
    logger.debug(f"Strict rubric parsed with {len(rubric_names)} items.")

    return rubric_names, rubric_block, (base_weights if any_weight else None)


def _convert_rubric_text_to_json(rubric_text: str) -> str:
    """
    使用 GPT 将自然语言描述的 rubric 文本转换为严格 JSON：
    [
      {"name": "...", "description": "...", "weight": 2.0, "levels": { ... }},
      ...
    ]
    """
    system_prompt = (
        "You are an assistant that converts grading rubrics into a structured JSON format.\n"
        "The JSON schema must be:\n"
        "[\n"
        "  {\n"
        "    \"name\": string,\n"
        "    \"description\": string,\n"
        "    \"weight\": number (optional),\n"
        "    \"levels\": { \"1.0\": string, \"0.5\": string, \"0.0\": string } (optional)\n"
        "  }, ...\n"
        "]\n"
        "Return ONLY valid JSON. Do not include comments or extra text."
    )

    resp = _client.chat.completions.create(
        model=_RUBRIC_MODEL,
        temperature=1,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Convert the following grading rubric description into the JSON format:\n\n"
                    f"{rubric_text}"
                ),
            },
        ],
    )

    content = (resp.choices[0].message.content or "").strip()
    logger.info(
        f"[strict_rubric] Converted rubric text to JSON, length={len(content)}"
    )
    return content


def load_strict_rubric_from_any_source(
    rubric_text: str | None,
) -> Tuple[List[str], str, Optional[List[float]]]:
    """
    统一入口：
    - rubric_text 可以是：
        1) JSON 字符串：直接作为 strict_rubric 解析
        2) 自然语言描述的 rubric 文本：调用 GPT 转换为 JSON，再解析
    返回：
        rubric_names, rubric_block, base_weights
    """

    if not rubric_text or not rubric_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strict rubric is required, either as text or as an uploaded file.",
        )

    text = rubric_text.strip()

    # 1) 尝试直接当 JSON 解析（导师/你自己已经写好了 JSON）
    try:
        json.loads(text)
        logger.info("[strict_rubric] Parsed as JSON directly.")
        return parse_strict_rubric(text)
    except Exception:
        logger.info(
            "[strict_rubric] Not valid JSON, will try to convert from natural language."
        )

    # 2) 当作自然语言 rubric，调用 GPT 解析成 JSON
    json_str = _convert_rubric_text_to_json(text)
    return parse_strict_rubric(json_str)
