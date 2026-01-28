# app/api/routes/grade_strict.py
from __future__ import annotations

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, Depends
from fastapi import HTTPException, status

from app.api.deps import require_api_key
from app.schemas import GradeResponse
from app.services.file_service import process_file
from app.services.strict_rubric_service import load_strict_rubric_from_any_source
from app.services.weighting_service import parse_weights, apply_weighted_overall
from app.services import grader
from app.utils.logger import logger

router = APIRouter()


@router.post(
    "/grade-strict",
    response_model=GradeResponse,
    dependencies=[Depends(require_api_key)],
    tags=["grading"],
)
async def grade_assignment_strict(
    question_file: UploadFile = File(..., description="Question file"),
    student_file: UploadFile = File(..., description="Student answer file"),
    reference_file: UploadFile = File(
        default=None, description="Reference answer file (optional)"
    ),

    # 方式 1：直接在表单中传文本（可以是 JSON，也可以是自然语言）
    strict_rubric: str = Form(
        default="",
        description="Strict rubric as JSON or natural language text.",
    ),

    # 方式 2：上传一个 rubric 文件（PDF/Word/TXT/图片/手写等）
    strict_rubric_file: Optional[UploadFile] = File(
        default=None,
        description="Strict rubric document (PDF/Word/TXT/Image) to be OCR'ed and parsed.",
    ),

    # 可选：仍然允许通过 rubric_weights 覆盖权重
    rubric_weights: str = Form(
        default="",
        description="Optional override weights for strict rubric items. "
                    "'2,1,3' | JSON '[2,1,3]' | 'Name:2,Other:1'",
    ),
):
    """
    严格模式：使用详细评分标准（富 rubric）对单份作业进行评分。

    - strict_rubric 可以是 JSON 字符串（[{name,description,weight,levels}...]）
      也可以是自然语言描述（会自动调用 GPT 转成 JSON）
    - strict_rubric_file 则允许上传 PDF/Word/图片/手写扫描的 rubric 文档，
      后端会先抽取文字，再调用 GPT 转成结构化 JSON。
    """
    logger.info(
        f"[grade-strict] Q={getattr(question_file, 'filename', None)}, "
        f"S={getattr(student_file, 'filename', None)}"
    )

    # 1) 抽取题目和学生答案文本（复用现有文件处理流程）
    question_text = await process_file(question_file, is_question_file=True)
    student_text = await process_file(student_file)

    # 2) 参考答案：如果提供了文件就用文件，否则留空交给 grade_once_auto 自动生成
    reference_text = ""
    if (
        reference_file is not None
        and getattr(reference_file, "filename", "")
        and reference_file.filename.strip()
    ):
        reference_text = await process_file(reference_file)
        logger.info(
            f"[grade-strict] Reference answer loaded from file "
            f"({len(reference_text)} chars)"
        )
    else:
        logger.info("[grade-strict] No reference file provided, will allow auto generation")

    # 3) 决定 rubric 文本来源：优先使用上传的文件，没有文件再用 strict_rubric 文本
    rubric_text: Optional[str] = None

    if strict_rubric_file is not None and getattr(strict_rubric_file, "filename", ""):
        rubric_text = await process_file(strict_rubric_file)
        logger.info(
            f"[grade-strict] Rubric loaded from file "
            f"{strict_rubric_file.filename} ({len(rubric_text)} chars)"
        )
    elif strict_rubric and strict_rubric.strip():
        rubric_text = strict_rubric
        logger.info(
            f"[grade-strict] Rubric loaded from text field ({len(rubric_text)} chars)"
        )

    # 3.1 如果两者都没有，抛错
    if not rubric_text or not rubric_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strict rubric is required (either as text or uploaded file).",
        )

    # 4) 把 rubric 文本解析成：names + 详细文本 + 基础权重
    rubric_names, rubric_block, base_weights = load_strict_rubric_from_any_source(
        rubric_text
    )

    # 5) 把 rubric 说明拼到题目后面，让模型能看到详细打分标准
    question_with_rubric = (
        question_text
        + "\n\n[GRADING_RUBRIC_FOR_ASSISTANT_ONLY]\n"
        + rubric_block
        + "\n[END_GRADING_RUBRIC]"
    )

    # 6) 使用原有 grade_once_auto 进行评分（让它根据需要生成参考答案）
    raw_result, actual_ref, was_generated = grader.grade_once_auto(
        question_with_rubric,
        reference_text,
        student_text,
        rubric_names,
    )
    parsed_result = grader.parse_result(raw_result)

    # 7) 处理权重：优先使用 rubric_weights，其次使用 strict_rubric 中的 weight
    weighted_overall: Optional[float] = None
    weights_used_map: Optional[Dict[str, float]] = None

    try:
        rubric_items_returned: List[str] = [
            getattr(rs, "item", "") for rs in parsed_result["rubric_scores"]
        ]

        weights: List[float] = []

        if rubric_weights and rubric_weights.strip():
            # 用户显式传入权重，走原有解析逻辑
            weights, _mode = parse_weights(rubric_items_returned, rubric_weights)
        elif base_weights is not None and sum(base_weights) > 0:
            # 否则，如果严格 rubric 中已经定义了 weight，就用它
            weights = list(base_weights[: len(rubric_items_returned)])

        if weights:
            detail_scores = [
                float(getattr(rs, "score", 0.0))
                for rs in parsed_result["rubric_scores"]
            ]
            weighted_overall = apply_weighted_overall(detail_scores, weights)
            parsed_result["overall_score"] = weighted_overall
            weights_used_map = {
                name: float(w) for name, w in zip(rubric_items_returned, weights)
            }
            logger.info(
                f"[grade-strict] Weighted overall applied: {weighted_overall}"
            )

    except Exception as e:
        logger.warning(f"[grade-strict] Weight application skipped: {e}")

    # 8) 返回结果（结构与 /grade 保持一致）
    return GradeResponse(
        overall_score=float(parsed_result["overall_score"]),
        rubric_scores=parsed_result["rubric_scores"],
        feedback=parsed_result["feedback"],
        reference_answer=actual_ref,
        reference_answer_generated=was_generated,
        weights_used=weights_used_map,
        weighted_overall=weighted_overall,
    )
