# app/api/routes/grade_batch_strict.py
from __future__ import annotations

import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
import os

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    Depends,
    HTTPException,
    status,
)

from app.api.deps import require_api_key
from app.schemas import GradeBatchResponse
from app.services.file_service import (
    process_file,
    extract_texts_from_zip,
    extract_texts_from_files,
)
from app.services.strict_rubric_service import load_strict_rubric_from_any_source
from app.services.weighting_service import parse_weights, apply_weighted_overall
from app.services.stats_service import compute_batch_summary
from app.services.report_service import write_batch_reports
from app.services import grader
from app.utils.logger import logger

router = APIRouter()
# [新增] 并发限制
_MAX_CONCURRENT_GRADING = int(os.getenv("MAX_CONCURRENT_GRADING", "10"))

@router.post(
    "/grade-batch-strict",
    response_model=GradeBatchResponse,
    dependencies=[Depends(require_api_key)],
    tags=["grading"],
)
async def grade_batch_strict(
    question_file: UploadFile = File(..., description="Question file"),
    reference_file: UploadFile = File(
        default=None, description="Reference answer (optional)"
    ),
    students_zip: UploadFile = File(
        default=None, description="ZIP of student answers (optional)"
    ),
    students: Optional[List[UploadFile]] = File(
        default=None, description="Multiple student files (optional)"
    ),

    strict_rubric: str = Form(
        default="",
        description="Strict rubric as JSON or natural language text.",
    ),
    strict_rubric_file: Optional[UploadFile] = File(
        default=None,
        description="Strict rubric document (PDF/Word/TXT/Image) to be OCR'ed and parsed.",
    ),

    rubric_weights: str = Form(
        default="",
        description="Optional override weights for strict rubric items.",
    ),
    pass_threshold: float = Form(
        default=60.0,
        description="Pass threshold for summary stats (0-100)",
    ),
):
    """
    严格模式的批量评分接口。

    - 支持题目 + 参考答案 + 多个学生作业（ZIP 和/或多文件）
    - 严格 rubric 可以来自：
        * strict_rubric 文本字段（JSON 或自然语言）
        * strict_rubric_file 上传的文档（PDF/Word/图片/手写）
    """

    logger.info(
        f"[grade-batch-strict] question={getattr(question_file, 'filename', None)}"
    )

    if not students_zip and not students:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of students_zip or students[] is required.",
        )

    # 1) 题目文本
    question_text = await process_file(question_file, is_question_file=True)

    # 2) 参考答案：如果提供文件，用文件；否则尝试自动生成一次
    reference_text = ""
    reference_generated = False

    if (
        reference_file is not None
        and getattr(reference_file, "filename", "")
        and reference_file.filename.strip()
    ):
        reference_text = await process_file(reference_file)
        logger.info(
            f"[grade-batch-strict] Reference answer loaded from file "
            f"({len(reference_text)} chars)"
        )
    else:
        logger.info(
            "[grade-batch-strict] No reference file provided, will attempt to auto-generate"
        )
        try:
            reference_text = grader.generate_reference_answer(question_text)
            reference_generated = True
            logger.info(
                f"[grade-batch-strict] Reference answer generated "
                f"({len(reference_text)} chars)"
            )
        except Exception as e:
            logger.error(
                f"[grade-batch-strict] Failed to generate reference answer: {e}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to generate reference answer: {e}",
            )

    # 3) 决定 rubric 文本来源：文件优先，其次是 strict_rubric 文本
    rubric_text: Optional[str] = None
    if strict_rubric_file is not None and getattr(strict_rubric_file, "filename", ""):
        rubric_text = await process_file(strict_rubric_file)
        logger.info(
            f"[grade-batch-strict] Rubric loaded from file "
            f"{strict_rubric_file.filename} ({len(rubric_text)} chars)"
        )
    elif strict_rubric and strict_rubric.strip():
        rubric_text = strict_rubric
        logger.info(
            f"[grade-batch-strict] Rubric loaded from text field "
            f"({len(rubric_text)} chars)"
        )

    if not rubric_text or not rubric_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strict rubric is required (either as text or uploaded file).",
        )

    # 3.1 解析 rubric 为结构化信息
    rubric_names, rubric_block, base_weights = load_strict_rubric_from_any_source(
        rubric_text
    )

    # 3.2 拼接题目 + rubric 说明
    question_with_rubric = (
        question_text
        + "\n\n[GRADING_RUBRIC_FOR_ASSISTANT_ONLY]\n"
        + rubric_block
        + "\n[END_GRADING_RUBRIC]"
    )

    # 4) 收集学生作业文本 (这里的并发已经在 file_service.py 中实现)
    items: List[Dict[str, Any]] = []

    if students_zip and getattr(students_zip, "filename", ""):
        zbytes = await students_zip.read()
        items.extend(await extract_texts_from_zip(zbytes))

    if students:
        items.extend(await extract_texts_from_files(students))

    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid student files provided.",
        )

    max_items = int(os.getenv("BATCH_MAX_ITEMS", "50"))
    if len(items) > max_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many student files: {len(items)} (limit {max_items})",
        )

    # 5) 逐个学生评分 (改造为并发)
    logger.info(f"[grade-batch-strict] Starting concurrent grading for {len(items)} items...")
    
    sem = asyncio.Semaphore(_MAX_CONCURRENT_GRADING)

    async def _grade_student_strict_task(idx, it):
        # 错误检查
        if it.get("ok") is False and "error" in it:
            return {
                "id": f"{idx:04d}",
                "file": it.get("file"),
                "ok": False,
                "error": it.get("error"),
            }

        student_text = it["text"]
        
        async with sem:
            try:
                # [关键] 并发调用 LLM
                raw_result, _actual_ref, _was_gen = await asyncio.to_thread(
                    grader.grade_once_auto,
                    question_with_rubric,
                    reference_text,
                    student_text,
                    rubric_names,
                )
                
                parsed = grader.parse_result(raw_result)
                weighted_overall: Optional[float] = None
                local_weights_map: Optional[Dict[str, float]] = None

                # 权重逻辑
                try:
                    rubric_items_returned: List[str] = [
                        getattr(rs, "item", "") for rs in parsed["rubric_scores"]
                    ]

                    weights: List[float] = []
                    mode: str = "default"

                    if rubric_weights and rubric_weights.strip():
                        weights, mode = parse_weights(rubric_items_returned, rubric_weights)
                    elif base_weights is not None and sum(base_weights) > 0:
                        weights = list(base_weights[: len(rubric_items_returned)])
                        mode = "named"

                    if mode in ("positional", "named") and weights:
                        detail_scores = [
                            float(getattr(rs, "score", 0.0))
                            for rs in parsed["rubric_scores"]
                        ]
                        weighted_overall = apply_weighted_overall(detail_scores, weights)
                        parsed["overall_score"] = weighted_overall
                        local_weights_map = {
                            name: float(w)
                            for name, w in zip(rubric_items_returned, weights)
                        }
                except Exception as we:
                    logger.warning(
                        f"[grade-batch-strict] Weighting skipped for {it.get('file')}: {we}"
                    )

                return {
                    "id": f"{idx:04d}",
                    "file": it.get("file"),
                    "ok": True,
                    "result": {
                        "overall_score": float(parsed["overall_score"]),
                        "weighted_overall": weighted_overall,
                        "rubric_scores": [rs.model_dump() for rs in parsed["rubric_scores"]],
                        "feedback": str(parsed["feedback"]),
                    },
                    "weights_used_snapshot": local_weights_map
                }

            except Exception as e:
                logger.warning(f"[grade-batch-strict] Failed to grade {it.get('file')}: {e}")
                return {
                    "id": f"{idx:04d}",
                    "file": it.get("file"),
                    "ok": False,
                    "error": str(e),
                }

    # 创建并执行任务
    tasks = [_grade_student_strict_task(idx, it) for idx, it in enumerate(items, start=1)]
    results = await asyncio.gather(*tasks)

    # 6) 汇总统计
    success = sum(1 for r in results if r["ok"])
    fail = len(results) - success
    
    # 提取最后一份有效的权重配置用于返回
    weights_used_map: Optional[Dict[str, float]] = None
    for r in results:
        if r.get("weights_used_snapshot"):
            weights_used_map = r.pop("weights_used_snapshot")
        elif "weights_used_snapshot" in r:
            del r["weights_used_snapshot"]

    summary = compute_batch_summary(results, pass_threshold=pass_threshold)

    resp_payload: Dict[str, Any] = {
        "count": len(results),
        "success_count": success,
        "fail_count": fail,
        "rubric_used": rubric_names,
        "weights_used": weights_used_map,
        "reference_answer": reference_text,
        "reference_answer_generated": reference_generated,
        "items": results,
        "summary": summary,
    }

    # 7) 生成 TXT/CSV 报告
    batch_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    report_paths = write_batch_reports(batch_id, resp_payload)
    resp_payload["report_files"] = report_paths

    return resp_payload