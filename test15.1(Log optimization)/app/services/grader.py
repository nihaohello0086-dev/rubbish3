# app/services/grader.py
import os
import json
import time
import hashlib
from typing import List, Optional, Any, Dict, Tuple

from dotenv import load_dotenv
from openai import OpenAI
from app.schemas import RubricScore
from app.utils.logger import logger  # 导入日志器

load_dotenv()
_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")

logger.info(f"Grader service initialized with model: {_MODEL}")

# ---------------------------
# Configuration
# ---------------------------

_DEFAULT_RUBRIC = ["Completeness", "Method", "Final Answer", "Arithmetic", "Unit"]
_MAX_RETRIES = 3
_RETRY_BASE_SLEEP = 0.6  # seconds, exponential backoff
_REQUEST_TEMPERATURE = 0.2
_MAX_TOKENS = 5000  # 防 "话多" & 节约成本；按需调整
_SCORE_DECIMALS = 1
_RUBRIC_DECIMALS = 2

# 参考答案生成配置
_REF_MAX_TOKENS = 5000  # 参考答案生成的token限制
_REF_MAX_RETRIES = 2    # 参考答案生成的重试次数

SYSTEM_PROMPT = """You are a teaching assistant for an Electrical Engineering course.
You must grade a student's answer with concise, formative feedback.

Scoring dimensions: {rubric}.
Rules:
- Score each dimension in {{0.0, 0.5, 1.0}}. Allow equivalent methods, numeric formats (fractions/decimals), and minor rounding.
- Accept equivalent unit forms (e.g., 0.264 dollars == 26.4 cents).
- Be factual and brief. No extra pedagogy beyond requested feedback.
- IMPORTANT: Output ONLY one JSON object and nothing else.

JSON schema to return:
{{
  "overall_score": <number 0..100>,
  "rubric_scores": [
    {{"item": "<string>", "score": <0|0.5|1>, "comment": "<string>"}}
  ],
  "feedback": "<string>"
}}
"""

# ---------------------------
# Custom Exceptions
# ---------------------------


class GradingError(Exception):
    """Base exception for grading errors"""

    pass


class ReferenceGenerationError(GradingError):
    """Error generating reference answer"""

    pass


class APICallError(GradingError):
    """Error calling OpenAI API"""

    pass


class JSONParsingError(GradingError):
    """Error parsing grading result JSON"""

    pass


class InvalidGradingResultError(GradingError):
    """Grading result doesn't meet requirements"""

    pass


# ---------------------------
# Auto reference-answer generation
# ---------------------------

# 简单内存缓存：同题目多次调用不重复花费
_REF_CACHE: Dict[str, str] = {}

_REF_SYSTEM_PROMPT = """You are an expert instructor. Generate a concise, correct reference solution
for the following problem. Requirements:
- Show key steps and formulas (succinctly).
- Provide the final numeric result with correct SI units when applicable.
- Do NOT invent missing data. If underdetermined, state necessary assumptions explicitly, then solve.
- Keep it rigorous but brief. Return plain text only.
"""

# 备用方案：更简化的提示词
_REF_SYSTEM_PROMPT_SIMPLE = """Solve this engineering problem step by step:
1. Identify what is given and what is asked
2. Select appropriate formulas
3. Perform calculations
4. State the final answer with units

Be concise and direct."""

# 最后的备用方案：极简提示词
_REF_SYSTEM_PROMPT_MINIMAL = """Solve this problem and show the answer with units."""


def _hash_question(q: str) -> str:
    """Generate hash for question to use as cache key"""
    return hashlib.sha1(q.strip().encode("utf-8")).hexdigest()


def _generate_reference_single_attempt(
    question: str, 
    system_prompt: str, 
    max_tokens: int = _REF_MAX_TOKENS,
    temperature: float = 0.1
) -> str:
    """
    单次参考答案生成尝试
    
    Args:
        question: 题目文本
        system_prompt: 系统提示词
        max_tokens: 最大token数
        temperature: 温度参数
    
    Returns:
        生成的参考答案文本
    
    Raises:
        ReferenceGenerationError: 生成失败
    """
    logger.debug(f"Attempting reference generation with {len(system_prompt)} char prompt")
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (question or "").strip()},
    ]
    
    kwargs: Dict[str, Any] = {"model": _MODEL, "messages": messages}
    if _supports_temperature(_MODEL):
        kwargs["temperature"] = temperature
    kwargs["max_completion_tokens"] = max_tokens
    
    # 关键修复：参考答案生成不使用JSON格式
    # 移除了 response_format 设置

    try:
        start_time = time.time()
        resp = _client.chat.completions.create(**kwargs)
        elapsed = time.time() - start_time

        # 详细记录API响应信息
        logger.debug(f"API response received in {elapsed:.2f}s")
        if hasattr(resp, "usage") and resp.usage:
            logger.debug(f"Token usage - Prompt: {resp.usage.prompt_tokens}, Completion: {resp.usage.completion_tokens}")

        # 检查响应结构
        if not resp.choices or len(resp.choices) == 0:
            logger.error("API returned no choices")
            raise ReferenceGenerationError("API returned no choices")
            
        choice = resp.choices[0]
        if not hasattr(choice, 'message') or not choice.message:
            logger.error("API choice has no message")
            raise ReferenceGenerationError("API choice has no message")

        # 检查完成原因 - 关键修复
        finish_reason = getattr(choice, 'finish_reason', None)
        logger.debug(f"API finish_reason: {finish_reason}")
        
        if finish_reason == "length":
            logger.warning("Response was truncated due to max_tokens limit")
            # 继续处理，但记录警告
        elif finish_reason == "tool_calls":
            logger.error("Unexpected tool call triggered in reference generation")
            raise ReferenceGenerationError("Model triggered tool call instead of text response")
        elif finish_reason == "content_filter":
            logger.error("Response blocked by content filter")
            raise ReferenceGenerationError("Response blocked by content filter")
        elif finish_reason not in ["stop", "length"]:
            logger.warning(f"Unexpected finish_reason: {finish_reason}")

        text = (choice.message.content or "").strip()
        
        # 详细记录内容信息
        logger.debug(f"Raw API response content length: {len(choice.message.content or '')}")
        logger.debug(f"Stripped content length: {len(text)}")
        if text:
            logger.debug(f"Content preview: {text[:100]}...")
        else:
            logger.warning("API returned empty content")
            logger.debug(f"Full choice object: {choice}")

        if not text:
            raise ReferenceGenerationError("API returned empty content")

        logger.info(f"Reference answer generated successfully ({len(text)} characters)")
        return text

    except ReferenceGenerationError:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.error(f"API call failed: {error_msg}", exc_info=True)
        raise ReferenceGenerationError(f"API call failed: {error_msg}") from e


def generate_reference_answer(question: str, *, max_tokens: int = _REF_MAX_TOKENS) -> str:
    """
    生成参考答案，包含多级备用方案
    
    Args:
        question: 题目文本
        max_tokens: 最大token数
    
    Returns:
        生成的参考答案
        
    Raises:
        ReferenceGenerationError: 所有方案都失败
    """
    question_hash = _hash_question(question)
    logger.debug(f"Generating reference answer for question (hash: {question_hash})")

    # 检查缓存
    cache_key = question_hash
    if cache_key in _REF_CACHE:
        logger.debug("Reference answer found in cache")
        return _REF_CACHE[cache_key]

    logger.info("Calling OpenAI API to generate reference answer")

    # 定义多个备用方案
    fallback_strategies = [
        {
            "name": "standard",
            "prompt": _REF_SYSTEM_PROMPT,
            "max_tokens": max_tokens,
            "temperature": 1
        },
        {
            "name": "simplified", 
            "prompt": _REF_SYSTEM_PROMPT_SIMPLE,
            "max_tokens": max_tokens * 2,
            "temperature": 1
        },
        {
            "name": "minimal",
            "prompt": _REF_SYSTEM_PROMPT_MINIMAL,
            "max_tokens": max_tokens * 4,
            "temperature": 1
        }
    ]

    last_error = None
    
    # 尝试每个备用方案
    for i, strategy in enumerate(fallback_strategies):
        try:
            logger.info(f"Trying strategy {i+1}/{len(fallback_strategies)}: {strategy['name']}")
            
            text = _generate_reference_single_attempt(
                question=question,
                system_prompt=strategy["prompt"],
                max_tokens=strategy["max_tokens"],
                temperature=strategy["temperature"]
            )
            
            # 成功生成，缓存并返回
            _REF_CACHE[cache_key] = text
            logger.info(f"Reference answer generated using {strategy['name']} strategy")
            return text
            
        except ReferenceGenerationError as e:
            last_error = e
            logger.warning(f"Strategy '{strategy['name']}' failed: {str(e)}")
            
            # 如果不是最后一个策略，继续尝试
            if i < len(fallback_strategies) - 1:
                logger.info("Trying next fallback strategy...")
                time.sleep(0.5)  # 短暂延迟
                continue
    
    # 所有策略都失败了
    logger.error("All reference generation strategies failed")
    raise ReferenceGenerationError(
        f"All reference generation strategies failed. Last error: {last_error}"
    )


# ---------------------------
# Helpers
# ---------------------------


def _rubric_to_list(rubric: Optional[List[str]]) -> List[str]:
    """Convert rubric to list, using default if None"""
    result = rubric if rubric else _DEFAULT_RUBRIC
    logger.debug(f"Using rubric: {result}")
    return result


def _supports_temperature(model: str) -> bool:
    """
    Check whether the given model is known to support the temperature parameter.

    White-list approach:
    - Only explicitly verified models are allowed to use temperature.
    - All other models default to NOT supporting temperature (safe behavior).
    """
    if not model:
        return False

    m = model.lower()

    # Known models that DO support temperature
    TEMPERATURE_SUPPORTED_PREFIXES = (
        "gpt-4.1",
        "gpt-4.0",
        "gpt-4-turbo",
        "gpt-3.5",
        "gpt-4o",
    )

    supports = m.startswith(TEMPERATURE_SUPPORTED_PREFIXES)

    logger.debug(f"Model {model} supports temperature: {supports}")
    return supports


def _clamp(v: float, lo: float, hi: float) -> float:
    """Clamp value between lo and hi"""
    return max(lo, min(hi, v))


def _round(v: float, ndigits: int) -> float:
    """Round to specified decimal places"""
    return float(f"{v:.{ndigits}f}")


def _safe_message_block(title: str, content: str) -> str:
    """
    降低提示注入：把用户内容标注为"数据"，而非"指令"
    """
    return f"[{title}]\nBEGIN_DATA\n{content}\nEND_DATA\n"


# ---------------------------
# LLM Call + Retry
# ---------------------------


def _chat_once(payload: Dict[str, Any]) -> str:
    """
    Execute single LLM call

    Raises:
        APICallError: If API call fails
    """
    logger.debug("Making OpenAI API call for grading")
    logger.debug(
        f"API call config - Model: {payload.get('model')}, Temperature: {payload.get('temperature', 'N/A')}"
    )

    try:
        start_time = time.time()
        resp = _client.chat.completions.create(**payload)
        elapsed = time.time() - start_time

        # 检查响应结构 - 关键修复
        if not resp.choices or len(resp.choices) == 0:
            logger.error("API returned no choices for grading")
            raise APICallError("API returned no choices")
            
        choice = resp.choices[0]
        if not hasattr(choice, 'message') or not choice.message:
            logger.error("API choice has no message for grading")
            raise APICallError("API choice has no message")

        # 检查完成原因 - 关键修复
        finish_reason = getattr(choice, 'finish_reason', None)
        logger.debug(f"Grading API finish_reason: {finish_reason}")
        
        if finish_reason == "length":
            logger.warning("Grading response was truncated due to max_tokens limit")
        elif finish_reason == "tool_calls":
            logger.error("Unexpected tool call triggered in grading")
            raise APICallError("Model triggered tool call instead of JSON response")
        elif finish_reason == "content_filter":
            logger.error("Grading response blocked by content filter")
            raise APICallError("Response blocked by content filter")

        result = choice.message.content or ""

        # Log token usage if available
        if hasattr(resp, "usage") and resp.usage:
            logger.debug(
                f"Token usage - Prompt: {resp.usage.prompt_tokens}, "
                f"Completion: {resp.usage.completion_tokens}, "
                f"Total: {resp.usage.total_tokens}"
            )

        logger.debug(
            f"OpenAI API response received ({len(result)} characters, {elapsed:.2f}s)"
        )

        if not result:
            logger.error("OpenAI returned empty response for grading")
            logger.debug(f"Full choice object: {choice}")
            raise APICallError("OpenAI returned empty response")

        return result

    except APICallError:
        raise
    except Exception as e:
        # 不假设异常有特定属性，直接使用str()
        error_msg = str(e)
        logger.error(f"OpenAI API call error: {error_msg}", exc_info=True)
        raise APICallError(f"API call failed: {error_msg}") from e


def _build_payload(
    question: str, reference_answer: str, student_answer: str, rubric: List[str]
) -> Dict[str, Any]:
    """Build OpenAI API payload for grading"""
    logger.debug("Building grading payload")

    user_prompt = (
        _safe_message_block("Problem", question)
        + "\n"
        + _safe_message_block("Reference Answer", reference_answer)
        + "\n"
        + _safe_message_block("Student Answer", student_answer)
    ).strip()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(rubric="、".join(rubric))},
        {"role": "user", "content": user_prompt},
    ]

    logger.debug(
        f"Prompt size - Question: {len(question)}, Reference: {len(reference_answer)}, Student: {len(student_answer)}"
    )

    kwargs: Dict[str, Any] = {
        "model": _MODEL,
        "messages": messages,
        "max_completion_tokens": _MAX_TOKENS,
    }
    if _supports_temperature(_MODEL):
        kwargs["temperature"] = _REQUEST_TEMPERATURE

    # 评分时使用强制 JSON格式 - 这里保持不变
    kwargs["response_format"] = {"type": "json_object"}
    logger.debug("JSON response format enabled for grading")

    return kwargs


def grade_once(
    question: str,
    reference_answer: str,
    student_answer: str,
    rubric: Optional[List[str]],
) -> str:
    """
    Single LLM attempt; returns raw text (ideally JSON).

    Raises:
        APICallError: If grading fails
    """
    logger.debug("Starting single grading attempt")

    payload = _build_payload(
        question, reference_answer, student_answer, _rubric_to_list(rubric)
    )
    result = _chat_once(payload)

    logger.debug("Grading attempt successful")
    logger.debug(f"Raw grading result preview: {result[:200]}...")

    return result


def grade_once_auto(
    question: str,
    reference_answer: Optional[str],
    student_answer: str,
    rubric: Optional[List[str]],
) -> Tuple[str, str, bool]:
    """
    与 grade_once 类似；当 reference_answer 为空/全空白时，会先自动生成参考答案再评分。
    
    Returns:
        Tuple of (grading_result, actual_reference_answer, was_generated)
        - grading_result: 原始的评分结果JSON字符串
        - actual_reference_answer: 实际使用的参考答案
        - was_generated: 是否为AI生成的参考答案

    Raises:
        ReferenceGenerationError: If reference generation fails
        APICallError: If grading fails
    """
    logger.info("Starting auto-grading process")
    logger.debug(
        f"Input sizes - Question: {len(question)}, Student: {len(student_answer)}"
    )

    ref = (reference_answer or "").strip()
    was_generated = False
    
    if not ref:
        logger.info("No reference answer provided, generating one")
        try:
            ref = generate_reference_answer(question)
            was_generated = True
        except ReferenceGenerationError as e:
            logger.error(f"Failed to generate reference answer: {str(e)}")
            # 作为最后的备用方案，使用一个通用的参考答案提示
            ref = "Reference answer generation failed. Evaluating based on general engineering principles."
            was_generated = True
            logger.warning("Using fallback reference answer")
    else:
        logger.debug(f"Using provided reference answer ({len(ref)} characters)")

    grading_result = grade_once(question, ref, student_answer, rubric)
    return grading_result, ref, was_generated


def grade_with_retry(
    question: str,
    reference_answer: str,
    student_answer: str,
    rubric: Optional[List[str]],
    retries: int = _MAX_RETRIES,
) -> str:
    """
    LLM with retry & exponential backoff.

    Raises:
        APICallError: If all attempts fail
    """
    logger.info(f"Starting grading with retry (max retries: {retries})")

    attempt = 0
    last_err: Optional[Exception] = None

    while attempt <= retries:
        try:
            logger.debug(f"Grading attempt {attempt + 1}/{retries + 1}")
            result = grade_once(question, reference_answer, student_answer, rubric)
            logger.info("Grading successful")
            return result

        except Exception as e:
            last_err = e
            logger.warning(f"Grading attempt {attempt + 1} failed: {str(e)}")

            if attempt < retries:
                sleep = _RETRY_BASE_SLEEP * (2**attempt)
                logger.debug(f"Retrying in {sleep:.1f} seconds...")
                time.sleep(sleep)

            attempt += 1

    logger.error(
        f"All grading attempts failed after {retries + 1} tries. Last error: {last_err}"
    )
    raise APICallError(
        f"All {retries + 1} grading attempts failed. Last error: {last_err}"
    ) from last_err


# ---------------------------
# JSON Extraction & Normalization
# ---------------------------


def _json_candidates(text: str) -> List[str]:
    """
    从任意文本中提取形如 {...} 的候选 JSON 片段（支持嵌套）。
    """
    logger.debug(f"Extracting JSON candidates from text ({len(text)} characters)")

    s = text
    n = len(s)
    i = 0
    level = 0
    start = -1
    in_str = False
    esc = False
    out: List[str] = []

    while i < n:
        ch = s[i]

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                if level == 0:
                    start = i
                level += 1
            elif ch == "}":
                if level > 0:
                    level -= 1
                    if level == 0 and start != -1:
                        out.append(s[start : i + 1])
                        start = -1
        i += 1

    logger.debug(f"Found {len(out)} JSON candidates")
    return out


def _extract_json(text: str) -> Dict[str, Any]:
    """
    Extract JSON from text with multiple strategies.

    Raises:
        JSONParsingError: If no valid JSON can be extracted
    """
    logger.debug(f"Attempting to extract JSON from text ({len(text)} characters)")

    text = (text or "").strip()
    if not text:
        logger.error("Empty response text for JSON extraction")
        raise JSONParsingError("Empty response text")

    # Log the raw text for debugging
    logger.debug(f"Raw text to parse: {text[:500]}...")

    # 1) 直接解析
    try:
        result = json.loads(text)
        logger.debug("Direct JSON parsing successful")
        return result
    except json.JSONDecodeError as e:
        logger.debug(f"Direct JSON parsing failed at position {e.pos}: {e.msg}")
    except Exception as e:
        logger.debug(f"Direct JSON parsing failed: {str(e)}")

    # 2) 片段解析
    cands = _json_candidates(text)

    for i, frag in enumerate(sorted(cands, key=len)):
        try:
            result = json.loads(frag)
            logger.debug(f"Successfully parsed JSON candidate {i+1} of {len(cands)}")
            return result
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse candidate {i+1}: {e.msg}")
        except Exception as e:
            logger.debug(f"Failed to parse candidate {i+1}: {str(e)}")

    # 3) 兜底：first '{' 到 last '}'
    try:
        first = text.index("{")
        last = text.rindex("}")
        substring = text[first : last + 1]
        result = json.loads(substring)
        logger.debug("Fallback JSON extraction successful")
        return result    
    except json.JSONDecodeError as e:
        logger.error(f"Fallback JSON parsing failed: {e.msg}")
    except ValueError as e:
        logger.error(f"Could not find JSON boundaries: {e}")
    except Exception as e:
        logger.error(f"Fallback JSON parsing failed: {str(e)}")

    # 记录完整的失败文本以便调试
    logger.error(f"All JSON extraction methods failed. Full text:\n{text}")
    raise JSONParsingError(
        f"No valid JSON found in response. Response length: {len(text)} chars"
    )


def _normalize_rubric_items(items: Any) -> List[RubricScore]:
    """
    统一转为 List[RubricScore]（Pydantic 模型），并做合法化处理。

    Raises:
        InvalidGradingResultError: If rubric items are invalid
    """
    logger.debug("Normalizing rubric items")

    result: List[RubricScore] = []

    if not isinstance(items, list):
        logger.error(f"Rubric items is not a list, got type: {type(items)}")
        raise InvalidGradingResultError(
            f"Rubric items must be a list, got {type(items).__name__}"
        )

    if len(items) == 0:
        logger.error("Empty rubric items list")
        raise InvalidGradingResultError("Rubric items list is empty")

    def clamp_to_half_steps(s: float) -> float:
        candidates = [0.0, 0.5, 1.0]
        clamped = min(candidates, key=lambda x: abs(x - s))
        if clamped != s:
            logger.debug(f"Clamped score {s} to {clamped}")
        return clamped

    for idx, it in enumerate(items):
        try:
            if isinstance(it, RubricScore):
                s = clamp_to_half_steps(float(it.score))
                name = (it.item or "").strip()
                if not name:
                    logger.warning(f"Empty item name at index {idx}, using 'Unknown'")
                    name = "Unknown"
                if name.lower() == "units":
                    name = "Unit"
                result.append(RubricScore(item=name, score=s, comment=it.comment or ""))

            elif isinstance(it, dict):
                # Try multiple possible field names
                name = (
                    it.get("item") or it.get("dimension") or it.get("name") or ""
                ).strip()
                if not name:
                    logger.warning(
                        f"No valid item name found at index {idx}, using 'Unknown'"
                    )
                    name = "Unknown"
                if name.lower() == "units":
                    name = "Unit"

                raw_score = it.get("score")
                if raw_score is None:
                    logger.error(f"No score found for rubric item {idx}: {it}")
                    raise InvalidGradingResultError(
                        f"No score found for rubric item at index {idx}"
                    )

                try:
                    s = clamp_to_half_steps(float(raw_score))
                except (ValueError, TypeError) as e:
                    logger.error(f"Invalid score value at index {idx}: {raw_score}")
                    raise InvalidGradingResultError(
                        f"Invalid score '{raw_score}' at index {idx}"
                    ) from e

                comment = (
                    it.get("comment")
                    or it.get("comments")
                    or it.get("rationale")
                    or it.get("explanation")
                    or ""
                )
                result.append(RubricScore(item=name, score=s, comment=comment))
            else:
                logger.error(f"Invalid rubric item type at index {idx}: {type(it)}")
                raise InvalidGradingResultError(
                    f"Invalid rubric item type at index {idx}: {type(it).__name__}"
                )

        except InvalidGradingResultError:
            raise
        except Exception as e:
            logger.error(f"Error processing rubric item {idx}: {str(e)}", exc_info=True)
            raise InvalidGradingResultError(
                f"Error processing rubric item {idx}: {str(e)}"
            ) from e

    logger.debug(f"Normalized {len(result)} rubric items")
    return result


def _compute_overall_if_missing(
    overall: Optional[float], rubric_scores: List[RubricScore]
) -> float:
    """
    当 overall_score 缺失或无效时，根据 rubric 均值 × 100 计算。

    Raises:
        InvalidGradingResultError: If cannot compute valid overall score
    """
    try:
        v = float(overall) if overall is not None else float("nan")
    except (ValueError, TypeError):
        v = float("nan")

    if not (v == v) or v < 0 or v > 100:
        logger.debug("Overall score missing or invalid, computing from rubric scores")

        if not rubric_scores:
            logger.error("Cannot compute overall score: no rubric scores available")
            raise InvalidGradingResultError(
                "Cannot compute overall score without rubric scores"
            )

        avg = sum(rs.score for rs in rubric_scores) / len(rubric_scores)
        logger.debug(f"Computed average rubric score: {avg}")
        v = avg * 100.0

    return _clamp(v, 0.0, 100.0)


def parse_result(text: Optional[str]) -> Dict[str, Any]:
    """
    解析 LLM 返回的评分结果。

    返回格式：
      { "overall_score": float, "rubric_scores": List[RubricScore], "feedback": str }

    Raises:
        JSONParsingError: If JSON extraction fails
        InvalidGradingResultError: If result doesn't meet requirements
    """
    logger.debug("Parsing grading result")

    if not text:
        logger.error("No text to parse")
        raise JSONParsingError("No grading result text to parse")

    # Extract JSON
    data = _extract_json(text)
    logger.debug("Successfully extracted JSON from response")

    # Log the extracted JSON for debugging (限制长度)
    json_str = json.dumps(data, indent=2)
    if len(json_str) > 500:
        logger.debug(f"Extracted JSON structure: {json_str[:500]}...")
    else:
        logger.debug(f"Extracted JSON structure: {json_str}")

    # Extract fields with multiple possible names
    raw_overall = data.get("overall_score", data.get("score"))
    rubric_any = data.get("rubric_scores") or data.get("rubric") or data.get("scores")
    feedback = (
        data.get("feedback")
        or data.get("feedbacks")
        or data.get("comment")
        or data.get("notes")
        or ""
    )

    # Validate required fields
    if rubric_any is None:
        logger.error("No rubric scores found in grading result")
        logger.error(f"Available keys in result: {list(data.keys())}")
        raise InvalidGradingResultError("No rubric scores found in grading result")

    logger.debug(
        f"Extracted fields - Overall: {raw_overall}, Rubric items: {len(rubric_any) if isinstance(rubric_any, list) else 'not a list'}, Has feedback: {bool(feedback)}"
    )

    # Process rubric scores
    rubric_scores = _normalize_rubric_items(rubric_any)

    # Compute or validate overall score
    overall = _compute_overall_if_missing(raw_overall, rubric_scores)

    # Round scores
    overall = _round(overall, _SCORE_DECIMALS)
    rubric_scores = [
        RubricScore(
            item=rs.item,
            score=_round(_clamp(rs.score, 0.0, 1.0), _RUBRIC_DECIMALS),
            comment=rs.comment or "",
        )
        for rs in rubric_scores
    ]

    # Validate feedback
    if not feedback:
        logger.warning("No feedback in grading result")
        feedback = "No specific feedback provided."

    logger.info(
        f"Successfully parsed result - Score: {overall}, Rubric items: {len(rubric_scores)}"
    )

    # Log rubric details
    for rs in rubric_scores:
        comment_preview = (
            rs.comment[:50] + "..." if len(rs.comment) > 50 else rs.comment
        )
        logger.debug(f"  {rs.item}: {rs.score} - {comment_preview}")

    return {
        "overall_score": overall,
        "rubric_scores": rubric_scores,
        "feedback": feedback,

    }
