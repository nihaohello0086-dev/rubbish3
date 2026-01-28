// src/types/grading.ts

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [k: string]: JsonValue };

// 通用的“松散对象”类型
export type Loose = Record<string, unknown>;

// 单条 rubric 打分
export interface RubricScore {
  criterion: string;
  score: number;
  weight?: number;
  comment?: string;
}

// 单次评分结果（/grade）
export interface GradeResponse {
  overall_score: number;
  overall_comment: string;
  rubric_scores?: RubricScore[];
  reference_answer?: string | null;
  reference_answer_generated?: boolean;
  weighted_overall?: number | null;
  weights_used?: Record<string, number> | null;
}

// 系统状态（/system-status）
export interface SystemStatus {
  status: "ok" | "degraded" | "down";
  version?: string;
  default_rubric?: string[];
  ocr?: { mathpix?: boolean; vision?: boolean };
  limits?: { max_file_mb?: number; allowed_types?: string[] };
  model?: string;
}

// ---- 批量打分相关类型（/grade-batch） ----

// 每个学生的简化结果（只保留前端展示需要的字段）
export interface ItemGradeResult {
  overall_score: number;
  weighted_overall?: number | null;
  feedback: string;
  rubric_scores?: RubricScore[];
}

// 批量结果中的一个元素
export interface BatchItem {
  id: string;
  file: string;
  ok: boolean;
  result?: ItemGradeResult | null;
  error?: string | null;
}

// 批量统计信息
export interface BatchSummary {
  avg: number;
  min: number;
  max: number;
  stdev: number;
  pass_rate: number; // 已经是百分比数值（0~100），方便前端直接渲染
}

// 批量评分响应
export interface BatchGradeResponse {
  count: number;
  success_count: number;
  fail_count: number;
  rubric_used: string[];
  weights_used?: Record<string, number> | null;
  reference_answer: string;
  reference_answer_generated: boolean;
  items: BatchItem[];
  summary?: BatchSummary | null;
  report_files?: {
    txt?: string;
    csv?: string;
  } | null;
}
