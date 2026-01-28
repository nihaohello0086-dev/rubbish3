# app/api/routes/grade_batch.py
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Request
from app.api.deps import require_api_key
from app.services.file_service import process_file, extract_texts_from_zip, extract_texts_from_files
from app.services.weighting_service import parse_weights, apply_weighted_overall
from app.services.stats_service import compute_batch_summary
from app.services.report_service import write_batch_reports
from app.services import grader
from app.utils.logger import logger
from datetime import datetime
import os
import asyncio

router = APIRouter()
_MAX_CONCURRENT_GRADING = int(os.getenv("MAX_CONCURRENT_GRADING", "10"))

@router.post("/grade-batch", dependencies=[Depends(require_api_key)])
async def grade_batch(
    request: Request,
    question_file: UploadFile = File(..., description="Question file"),
    reference_file: UploadFile = File(default=None, description="Optional reference answer file"),
    students_zip: UploadFile = File(default=None, description="ZIP file containing student answers"),
    students: list[UploadFile] | None = File(default=None, description="List of student answer files"),
    # 接收文本形式的参考答案，用于人工修改后的批量重判
    reference_text: str = Form(default="", description="Manual text override for reference answer"),
    rubric: str = Form(default="", description="Comma-separated rubric items"),
    rubric_weights: str = Form(default="", description="Weights for rubric items"),
    pass_threshold: float = Form(default=60.0, description="Passing score threshold"),
):
    logger.info(f"Batch grading start: {getattr(question_file, 'filename', 'unknown')}")

    if not students_zip and not students:
        raise HTTPException(400, "At least one of students_zip or students[] is required")

    # 1. 处理题目文本
    question_text = await process_file(question_file, is_question_file=True)

    # 2. 确定参考答案 (Reference Answer Handling)
    # 逻辑：对于批量批改，所有学生应该使用同一份标准答案。
    # 优先级: reference_text (人工修改) > reference_file (上传文件) > Auto-generate (自动生成)
    
    final_ref_text = ""
    reference_generated = False
    
    # 标记是否使用了人工提供的文本
    is_manual_ref = False

    if reference_text and reference_text.strip():
        # Case A: 使用前端传来的修改版参考答案
        final_ref_text = reference_text.strip()
        is_manual_ref = True
        logger.info("Batch grading: Using manual reference text provided by user.")
    elif reference_file and getattr(reference_file, "filename", ""):
        # Case B: 使用上传的文件
        final_ref_text = await process_file(reference_file)
        logger.info("Batch grading: Using uploaded reference file.")
    else:
        # Case C: 自动生成
        # 我们在这里生成一次，然后传给所有学生评分使用
        try:
            final_ref_text = grader.generate_reference_answer(question_text)
            reference_generated = True
            logger.info("Batch grading: Generated reference answer automatically.")
        except Exception as e:
            logger.error(f"Failed to generate reference answer: {e}")
            # 如果生成失败，可以选择报错，或者让后面 grade_once_auto 尝试兜底（通常在这里报错更好）
            raise HTTPException(500, f"Failed to generate reference answer: {str(e)}")

    # 3. 提取学生作业文本 (现在这里是并发的了!)
    items = []
    if students_zip and getattr(students_zip, "filename", ""):
        zbytes = await students_zip.read()
        items.extend(await extract_texts_from_zip(zbytes))

    if students:
        items.extend(await extract_texts_from_files(students))

    if not items:
        raise HTTPException(400, "No valid student files provided")

    # 4. 准备评分标准
    rubric_list = [x.strip() for x in rubric.split(",")] if rubric.strip() else \
        ["Completeness", "Method", "Final Answer", "Arithmetic", "Unit"]

    # 5. 对每个学生进行评分 (改造为并发)
    logger.info(f"Starting concurrent grading for {len(items)} items...")
    
    # 信号量控制 LLM 并发数
    sem = asyncio.Semaphore(_MAX_CONCURRENT_GRADING)
    
    # 定义单个打分任务
    async def _grade_student_task(idx, it):
        if it.get("error"):
            # 如果 OCR 阶段就出错了，直接返回错误结构
            return {"id": f"{idx:04d}", "file": it["file"], "ok": False, "error": it["error"]}

        async with sem:
            try:
                # [关键] 使用 to_thread 将同步的 grader.grade_once_auto 放入线程池运行
                # 这样不会阻塞主循环，允许其他任务同时进行
                raw_result, _actual_ref, _ = await asyncio.to_thread(
                    grader.grade_once_auto,
                    question_text, final_ref_text, it["text"], rubric_list
                )
                
                parsed = grader.parse_result(raw_result)
                weighted_overall = None
                weights_used_map = None

                if rubric_weights.strip():
                    rubric_items = [rs.item for rs in parsed["rubric_scores"]]
                    weights, mode = parse_weights(rubric_items, rubric_weights)
                    if mode in ("named", "positional"):
                        detail_scores = [rs.score for rs in parsed["rubric_scores"]]
                        weighted_overall = apply_weighted_overall(detail_scores, weights)
                        parsed["overall_score"] = weighted_overall
                        weights_used_map = dict(zip(rubric_items, weights))

                return {
                    "id": f"{idx:04d}",
                    "file": it["file"],
                    "ok": True,
                    "result": {
                        "overall_score": float(parsed["overall_score"]),
                        "weighted_overall": weighted_overall,
                        "rubric_scores": [rs.model_dump() for rs in parsed["rubric_scores"]],
                        "feedback": parsed["feedback"],
                    },
                    "weights_used_snapshot": weights_used_map # 暂存权重信息用于汇总
                }

            except Exception as e:
                return {"id": f"{idx:04d}", "file": it["file"], "ok": False, "error": str(e)}

    # 创建所有任务
    tasks = [_grade_student_task(idx, it) for idx, it in enumerate(items, start=1)]
    
    # 并发执行并保持顺序
    results = await asyncio.gather(*tasks)

    # 6. 计算统计摘要和后处理
    success = sum(1 for r in results if r["ok"])
    fail = len(results) - success
    
    # 从成功的结果中提取最后一次使用的权重配置
    last_weights_used_map = None
    for r in results:
        if r.get("weights_used_snapshot"):
            last_weights_used_map = r.pop("weights_used_snapshot") # 取出后删除，不返回给前端多余字段
        elif "weights_used_snapshot" in r:
            del r["weights_used_snapshot"] # 失败的任务可能没有这个字段，但也可能有 Key 

    summary = compute_batch_summary(results, pass_threshold)

    # 7. 生成报告并返回
    batch_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    should_return_ref = reference_generated or is_manual_ref

    payload = {
        "count": len(results),
        "success_count": success,
        "fail_count": fail,
        "rubric_used": rubric_list,
        "weights_used": last_weights_used_map,
        "reference_answer": final_ref_text if should_return_ref else None,
        "reference_answer_generated": reference_generated,
        "items": results,
        "summary": summary,
    }

    report_paths = write_batch_reports(batch_id, payload)
    payload["report_files"] = report_paths

    return payload