# app/schemas.py
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class RubricScore(BaseModel):
    """Individual rubric criterion score."""
    item: str = Field(..., description="Grading criterion name")
    score: float = Field(..., ge=0.0, le=1.0, description="Score for this criterion (0.0-1.0)")
    comment: str = Field(..., description="Feedback comment for this criterion")


class GradeResponse(BaseModel):
    """Grading result response."""
    overall_score: float = Field(..., ge=0.0, le=100.0, description="Overall score (0-100)")
    rubric_scores: List[RubricScore] = Field(..., description="Detailed scores for each criterion")
    feedback: str = Field(..., description="Overall feedback for the student")
    reference_answer: Optional[str] = Field(None, description="AI-generated reference answer (if generated)")
    reference_answer_generated: bool = Field(False, description="Whether the reference answer was AI-generated")
    weights_used: Optional[Dict[str, float]] = Field(None, description="Mapping from rubric item name to the weight actually used for computing the overall score")
    weighted_overall: Optional[float] = Field(None, ge=0.0, le=100.0, description="Weighted overall score (0-100) if custom weights were applied")


class SystemStatusResponse(BaseModel):
    """System health and capabilities status."""
    system_healthy: bool = Field(..., description="Overall system health status")
    openai_available: bool = Field(..., description="OpenAI API key configured and accessible")
    mathpix_available: bool = Field(..., description="Mathpix credentials configured")
    ocr_backend: str = Field(..., description="Active OCR backend (auto, mathpix, openai)")
    supported_file_types: List[str] = Field(..., description="Supported file MIME types")
    max_file_size_mb: float = Field(10, description="Maximum file size in MB")
    document_processing: Dict[str, Any] = Field(..., description="Document processing capabilities")
    default_rubric: List[str] = Field(..., description="Default grading criteria used when none provided")
    version: str = Field(..., description="Application version")


class ItemGradeResult(BaseModel):
    overall_score: float
    weighted_overall: Optional[float] = None
    rubric_scores: List[RubricScore]
    feedback: str

class BatchItem(BaseModel):
    id: str
    file: str
    ok: bool
    result: Optional[ItemGradeResult] = None
    error: Optional[str] = None

class BatchSummary(BaseModel):
    avg: float
    min: float
    max: float
    stdev: float
    pass_rate: float

class GradeBatchResponse(BaseModel):
    count: int
    success_count: int
    fail_count: int
    rubric_used: List[str]
    weights_used: Optional[Dict[str, float]] = None  # 若这批应用了统一权重可返回
    reference_answer: str
    reference_answer_generated: bool
    items: List[BatchItem]
    summary: Optional[BatchSummary] = None
    report_files: Optional[Dict[str, str]] = None    # {"txt": "...", "csv": "..."}
