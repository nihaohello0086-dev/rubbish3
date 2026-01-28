# app/api/routes/grade_single.py
from fastapi import APIRouter, UploadFile, File, Form, Depends
from app.api.deps import require_api_key
from app.schemas import GradeResponse
from app.services.file_service import process_file
from app.services import grader
from app.services.weighting_service import parse_weights, apply_weighted_overall
from app.utils.logger import logger

router = APIRouter()

@router.post("/grade", response_model=GradeResponse, dependencies=[Depends(require_api_key)])
async def grade_assignment(
    question_file: UploadFile = File(..., description="Question file"),
    student_file: UploadFile = File(..., description="Student answer file"),
    reference_file: UploadFile = File(default=None, description="Optional reference answer file"),
    # [新增] 接收文本形式的参考答案，用于人工修改后的重判
    reference_text: str = Form(default="", description="Manual text override for reference answer"),
    rubric: str = Form(default="", description="Comma-separated rubric items"),
    rubric_weights: str = Form(default="", description="Weights for rubric items"),
):
    logger.info(f"Grading request - Q={getattr(question_file, 'filename', 'unknown')}, S={getattr(student_file, 'filename', 'unknown')}")

    # 1. 提取题目和学生答案文本
    question_text = await process_file(question_file, is_question_file=True)
    student_text = await process_file(student_file)

    # 2. 确定参考答案 (Reference Answer Strategy)
    # 优先级: reference_text (人工修改) > reference_file (上传文件) > Auto-generate (自动生成)
    final_ref_text = ""
    
    # 标记是否使用了人工提供的文本（用于后续决定是否要在响应中返回该文本）
    is_manual_ref = False 

    if reference_text and reference_text.strip():
        # Case A: 使用前端传来的修改版参考答案
        final_ref_text = reference_text.strip()
        is_manual_ref = True
        logger.info("Using manual reference text provided by user.")
    elif reference_file and getattr(reference_file, "filename", "") and reference_file.size:
        # Case B: 使用上传的文件
        final_ref_text = await process_file(reference_file)
        logger.info("Using uploaded reference file.")
    else:
        # Case C: 留空，稍后让 grader 自动生成
        logger.info("No reference provided, will attempt auto-generation.")

    # 3. 解析评分标准 (Rubric)
    if rubric.strip():
        rubric_list = [x.strip() for x in rubric.split(",") if x.strip()]
    else:
        rubric_list = ["Completeness", "Method", "Final Answer", "Arithmetic", "Unit"]

    # 4. 执行评分
    # grade_once_auto 会检查 final_ref_text：
    # - 如果有值，直接使用（不消耗生成 Token）
    # - 如果为空，自动调用 LLM 生成，并返回生成的文本
    raw_result, actual_ref, was_generated = grader.grade_once_auto(
        question_text, 
        final_ref_text, 
        student_text, 
        rubric_list
    )

    parsed_result = grader.parse_result(raw_result)

    # 5. 应用权重 (Weighting)
    try:
        rubric_items = [rs.item for rs in parsed_result["rubric_scores"]]
        weights, _mode = parse_weights(rubric_items, rubric_weights)
        detail_scores = [rs.score for rs in parsed_result["rubric_scores"]]
        weighted_overall = apply_weighted_overall(detail_scores, weights)

        parsed_result["overall_score"] = weighted_overall
        weights_used = dict(zip(rubric_items, weights))
    except Exception as e:
        logger.warning(f"Weighting failed: {e}")
        weighted_overall = None
        weights_used = None

    # 6. 构造返回结果
    # 如果是自动生成的，或者用户手动传入了文本，我们都将其返回给前端，以便展示或再次编辑。
    # (如果原本是上传的文件，通常不需要回传内容，保持 None 即可，除非你也想让上传的文件内容可编辑)
    should_return_ref = was_generated or is_manual_ref

    return GradeResponse(
        overall_score=float(parsed_result["overall_score"]),
        rubric_scores=parsed_result["rubric_scores"],
        feedback=parsed_result["feedback"],
        # 确保前端拿到最新的参考答案文本
        reference_answer=actual_ref if should_return_ref else None,
        reference_answer_generated=was_generated,
        weights_used=weights_used,
        weighted_overall=weighted_overall,
    )