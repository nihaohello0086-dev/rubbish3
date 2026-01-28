// src/App.tsx
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Link as LinkIcon, Layers, FileSignature } from "lucide-react";

import { SystemStatusCard } from "./components/SystemStatusCard";
import { SingleGradingCard } from "./components/SingleGradingCard";
import { BatchGradingCard } from "./components/BatchGradingCard";
import { RubricSettings } from "./components/RubricSettings";

import type {
  SystemStatus,
  GradeResponse,
  BatchGradeResponse,
  BatchItem,
  BatchSummary,
  JsonValue,
  Loose,
} from "./types/grading";
import {
  buildRubricField,
  downloadJson,
  getRubricNamesFromUser,
  pick,
  toNum,
  toStr,
  tryParseJsonArray,
} from "./lib/grading";

// --- 1. 数据规范化辅助函数 (Helpers) ---

/**
 * 将后端返回的单次评分原始数据转换为前端使用的 GradeResponse
 */
const normalizeGradeResponse = (raw: Loose, userRubricNames: string[]): GradeResponse => {
  const weightsUsedMap =
    raw.weights_used && typeof raw.weights_used === "object"
      ? (raw.weights_used as Record<string, number>)
      : undefined;

  const normItem = (it: Loose, idx: number) => {
    const fromBackendRaw = pick(it, ["criterion", "item", "name", "title", "dimension", "aspect", "label"]);
    const fromBackend = toStr(fromBackendRaw)?.trim() ?? "";
    const fromUser = (userRubricNames[idx] ?? "").trim();

    let fallback = "";
    if (!fromBackend && !fromUser) {
      for (const [k, v] of Object.entries(it)) {
        if (typeof v === "string" && k !== "comment") {
          fallback = v.trim();
          break;
        }
      }
    }

    const criterion = fromBackend || fromUser || fallback || `Item ${idx + 1}`;
    let weight = toNum(pick(it, ["weight", "w", "weighting"]), 1);
    
    if (weightsUsedMap && criterion in weightsUsedMap) {
       const w = toNum(weightsUsedMap[criterion], NaN);
       if (Number.isFinite(w)) weight = w;
    }

    return {
      criterion,
      score: toNum(pick(it, ["score", "points", "value"]), 0),
      weight,
      comment: toStr(pick(it, ["comment", "feedback", "reason", "explanation", "notes"])) ?? "",
    };
  };

  const itemsSrc =
    (Array.isArray(raw.rubric_scores) && (raw.rubric_scores as Loose[])) ||
    (Array.isArray(raw.rubric) && (raw.rubric as Loose[])) ||
    (Array.isArray(raw.details) && (raw.details as Loose[])) ||
    [];

  return {
    overall_score: toNum(raw.overall_score ?? raw.total_score ?? raw.score, 0),
    overall_comment: toStr(pick(raw, ["feedback", "overall_comment", "summary", "comment"])) ?? "",
    rubric_scores: itemsSrc.map((it, idx) => normItem(it, idx)),
    reference_answer: toStr(pick(raw, ["reference_answer", "reference", "ref_answer"])),
    reference_answer_generated: Boolean(raw.reference_answer_generated ?? raw.generated_reference),
    weighted_overall: typeof raw.weighted_overall === "number" ? raw.weighted_overall : undefined,
    weights_used: weightsUsedMap,
  };
};

/**
 * 将后端返回的批量评分原始数据转换为前端使用的 BatchGradeResponse
 */
const normalizeBatchResponse = (raw: Loose, userRubricNames: string[]): BatchGradeResponse => {
  const rawItems = Array.isArray(raw.items) ? (raw.items as Loose[]) : [];
  const weightsUsedMapGlobal =
    raw.weights_used && typeof raw.weights_used === "object"
      ? (raw.weights_used as Record<string, number>)
      : undefined;

  const normRubricItem = (it: Loose, idx: number) => {
    const fromBackendRaw = pick(it, ["criterion", "item", "name", "title", "dimension", "aspect", "label"]);
    const fromBackend = toStr(fromBackendRaw)?.trim() ?? "";
    const fromUser = (userRubricNames[idx] ?? "").trim();
    
    let fallback = "";
    if (!fromBackend && !fromUser) {
        for (const [k, v] of Object.entries(it)) {
            if (typeof v === "string" && k !== "comment") { fallback = v.trim(); break; }
        }
    }
    const criterion = fromBackend || fromUser || fallback || `Item ${idx + 1}`;
    let weight = toNum(pick(it, ["weight", "w", "weighting"]), 1);
    if (weightsUsedMapGlobal && criterion in weightsUsedMapGlobal) {
        const w = toNum(weightsUsedMapGlobal[criterion], NaN);
        if (Number.isFinite(w)) weight = w;
    }

    return {
      criterion,
      score: toNum(pick(it, ["score", "points", "value"]), 0),
      weight,
      comment: toStr(pick(it, ["comment", "feedback", "reason", "explanation", "notes"])) ?? "",
    };
  };

  const items: BatchItem[] = rawItems.map((it) => {
    const id = toStr(it.id) ?? "";
    const file = toStr(it.file) ?? "";
    const ok = Boolean(it.ok);
    let resultItem: BatchItem["result"] = null;

    if (ok && it.result && typeof it.result === "object") {
      const r = it.result as Loose;
      let rubricScores;
      if (Array.isArray(r.rubric_scores)) {
        rubricScores = (r.rubric_scores as Loose[]).map((ri, idx) => normRubricItem(ri, idx));
      }
      resultItem = {
        overall_score: toNum(r.overall_score, 0),
        weighted_overall: typeof r.weighted_overall === "number" ? r.weighted_overall : undefined,
        feedback: toStr(pick(r, ["feedback", "overall_comment", "comment"])) ?? "",
        rubric_scores: rubricScores,
      };
    }
    const errorText = !ok && toStr(it.error) ? toStr(it.error) : undefined;
    return { id, file, ok, result: resultItem, error: errorText ?? null };
  });

  const summaryLoose = raw.summary && typeof raw.summary === "object" ? (raw.summary as Loose) : undefined;
  const summary: BatchSummary | null = summaryLoose
    ? {
        avg: toNum(summaryLoose.avg, 0),
        min: toNum(summaryLoose.min, 0),
        max: toNum(summaryLoose.max, 0),
        stdev: toNum(summaryLoose.stdev, 0),
        pass_rate: toNum(summaryLoose.pass_rate, 0) * 100,
      }
    : null;

  const rubricUsed: string[] = Array.isArray(raw.rubric_used) ? (raw.rubric_used.map((x) => toStr(x)).filter(Boolean) as string[]) : [];
  const reportFiles = raw.report_files && typeof raw.report_files === "object" ? (raw.report_files as Loose) : undefined;

  return {
    count: toNum(raw.count, rawItems.length),
    success_count: toNum(raw.success_count, 0),
    fail_count: toNum(raw.fail_count, 0),
    rubric_used: rubricUsed,
    weights_used: weightsUsedMapGlobal,
    reference_answer: toStr(raw.reference_answer) ?? "",
    reference_answer_generated: Boolean(raw.reference_answer_generated),
    items,
    summary: summary ?? undefined,
    report_files: reportFiles ? { txt: toStr(reportFiles.txt), csv: toStr(reportFiles.csv) } : undefined,
  };
};

// --- 2. 主组件 ---

export default function AIFeedbackFrontend() {
  // Navigation State
  const [activeTab, setActiveTab] = useState<"single" | "batch">("single");

  // System State
  const [apiBase, setApiBase] = useState<string>("");
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  // === Shared Configuration State (Rubric & Weights) ===
  const [rubricText, setRubricText] = useState<string>("");
  const [rubricParsed, setRubricParsed] = useState<JsonValue[] | null>(null);
  const [rubricWeightsText, setRubricWeightsText] = useState<string>("");
  const [rubricFile, setRubricFile] = useState<File | null>(null);
  const [useStrict, setUseStrict] = useState(false);

  // === Single Grading State ===
  const [questionFile, setQuestionFile] = useState<File | null>(null);
  const [studentFile, setStudentFile] = useState<File | null>(null);
  const [referenceFile, setReferenceFile] = useState<File | null>(null);
  const [grading, setGrading] = useState(false);
  const [gradeError, setGradeError] = useState<string | null>(null);
  const [result, setResult] = useState<GradeResponse | null>(null);

  // === Batch Grading State ===
  const [batchQuestionFile, setBatchQuestionFile] = useState<File | null>(null);
  const [batchReferenceFile, setBatchReferenceFile] = useState<File | null>(null);
  const [batchZipFile, setBatchZipFile] = useState<File | null>(null);
  const [batchStudentFiles, setBatchStudentFiles] = useState<File[]>([]);
  const [batchPassThreshold, setBatchPassThreshold] = useState<string>("60.0");
  const [batchGrading, setBatchGrading] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchResult, setBatchResult] = useState<BatchGradeResponse | null>(null);

  // --- Effects ---

  // Fetch System Status
  const fetchSystemStatus = useCallback(async (base: string) => {
    setLoadingStatus(true);
    setStatusError(null);
    try {
      const res = await fetch(`${base || ""}/system-status`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const raw: Loose = await res.json();
      
      const defaultRubricArray = Array.isArray(raw.default_rubric)
        ? (raw.default_rubric as string[])
        : [];

      setStatus({
        status: raw.system_healthy ? "ok" : "down",
        version: toStr(raw.version),
        default_rubric: defaultRubricArray,
        ocr: { mathpix: Boolean(raw.mathpix_available), vision: Boolean(raw.openai_available) },
        limits: { max_file_mb: toNum(raw.max_file_size_mb, 0), allowed_types: Array.isArray(raw.supported_file_types) ? raw.supported_file_types as string[] : undefined },
        model: toStr(raw.model),
      });

      // 如果当前没有设置 Rubric，且后端有默认值，则填充
      setRubricText((prev) => {
        if (!prev && defaultRubricArray.length) return defaultRubricArray.join(", ");
        return prev;
      });

    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatusError(msg);
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    fetchSystemStatus(apiBase);
  }, [apiBase, fetchSystemStatus]);

  // Parse rubric JSON for display status
  useEffect(() => {
    setRubricParsed(tryParseJsonArray(rubricText));
  }, [rubricText]);

  // --- Derived State for UI Control ---
  const strictHasRubricSource = rubricText.trim().length > 0 || rubricFile !== null;
  
  const canSubmitSingle = 
    !!questionFile && 
    !!studentFile && 
    !grading && 
    (!useStrict || strictHasRubricSource);
    
  const canSubmitBatch = 
    !!batchQuestionFile && 
    (!!batchZipFile || batchStudentFiles.length > 0) && 
    !batchGrading && 
    (!useStrict || strictHasRubricSource);

  const overallText = useMemo(() => {
    if (result?.overall_comment && result.overall_comment.trim()) return result.overall_comment;
    const items = (result?.rubric_scores ?? []).filter((r) => r?.comment && String(r.comment).trim()).map((r) => `• ${r.criterion}: ${r.comment}`);
    return items.length ? items.join("\n") : "—";
  }, [result]);

  // --- Handlers: Single Grading ---

  const onSubmitSingle = async () => {
    if (useStrict && !strictHasRubricSource) {
      setGradeError("Strict grading requires a rubric text or file.");
      return;
    }
    setGrading(true); setGradeError(null); setResult(null);
    try {
      const fd = new FormData();
      if (questionFile) fd.append("question_file", questionFile);
      if (studentFile) fd.append("student_file", studentFile);
      if (referenceFile) fd.append("reference_file", referenceFile);

      const weightsPayload = rubricWeightsText.trim();
      const endpoint = useStrict ? "/grade-strict" : "/grade";

      if (useStrict) {
        if (rubricText.trim()) fd.append("strict_rubric", rubricText.trim());
        if (rubricFile) fd.append("strict_rubric_file", rubricFile);
      } else {
        const rubricPayload = buildRubricField(rubricText);
        if (rubricPayload) fd.append("rubric", rubricPayload);
        if (rubricFile) fd.append("rubric_file", rubricFile);
      }
      if (weightsPayload) fd.append("rubric_weights", weightsPayload);

      const res = await fetch(`${apiBase || ""}${endpoint}`, { method: "POST", body: fd });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.error || `HTTP ${res.status}`);
      }

      const raw = await res.json();
      const userNames = getRubricNamesFromUser(rubricText);
      setResult(normalizeGradeResponse(raw, userNames));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setGradeError(msg);
    } finally {
      setGrading(false);
    }
  };

  const onRegradeSingleWithRef = async (newRefText: string) => {
    if (!questionFile || !studentFile) return;
    setGrading(true); setGradeError(null);
    try {
      const fd = new FormData();
      fd.append("question_file", questionFile);
      fd.append("student_file", studentFile);
      // [重点] 传入修改后的参考答案
      fd.append("reference_text", newRefText);

      const weightsPayload = rubricWeightsText.trim();
      const endpoint = useStrict ? "/grade-strict" : "/grade";

      if (useStrict) {
        if (rubricText.trim()) fd.append("strict_rubric", rubricText.trim());
        if (rubricFile) fd.append("strict_rubric_file", rubricFile);
      } else {
        const rubricPayload = buildRubricField(rubricText);
        if (rubricPayload) fd.append("rubric", rubricPayload);
        if (rubricFile) fd.append("rubric_file", rubricFile);
      }
      if (weightsPayload) fd.append("rubric_weights", weightsPayload);

      const res = await fetch(`${apiBase || ""}${endpoint}`, { method: "POST", body: fd });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.error || `HTTP ${res.status}`);
      }

      const raw = await res.json();
      const userNames = getRubricNamesFromUser(rubricText);
      setResult(normalizeGradeResponse(raw, userNames));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setGradeError(msg);
    } finally {
      setGrading(false);
    }
  };

  // --- Handlers: Batch Grading ---

  const onSubmitBatch = async () => {
    if (useStrict && !strictHasRubricSource) {
      setBatchError("Strict batch grading requires a rubric text or file.");
      return;
    }
    setBatchGrading(true); setBatchError(null); setBatchResult(null);
    try {
      const fd = new FormData();
      if (batchQuestionFile) fd.append("question_file", batchQuestionFile);
      if (batchReferenceFile) fd.append("reference_file", batchReferenceFile);
      if (batchZipFile) fd.append("students_zip", batchZipFile);
      for (const f of batchStudentFiles) fd.append("students", f);

      const weightsPayload = rubricWeightsText.trim();
      const threshold = batchPassThreshold.trim();
      const endpoint = useStrict ? "/grade-batch-strict" : "/grade-batch";

      if (useStrict) {
        if (rubricText.trim()) fd.append("strict_rubric", rubricText.trim());
        if (rubricFile) fd.append("strict_rubric_file", rubricFile);
      } else {
        const rubricPayload = buildRubricField(rubricText);
        if (rubricPayload) fd.append("rubric", rubricPayload);
        if (rubricFile) fd.append("rubric_file", rubricFile);
      }
      if (weightsPayload) fd.append("rubric_weights", weightsPayload);
      if (threshold) fd.append("pass_threshold", threshold);

      const res = await fetch(`${apiBase || ""}${endpoint}`, { method: "POST", body: fd });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.error || `HTTP ${res.status}`);
      }

      const raw = await res.json();
      const userNames = getRubricNamesFromUser(rubricText);
      setBatchResult(normalizeBatchResponse(raw, userNames));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setBatchError(msg);
    } finally {
      setBatchGrading(false);
    }
  };

  const onRegradeBatchWithRef = async (newRefText: string) => {
    if (!batchQuestionFile) return;
    if (!batchZipFile && batchStudentFiles.length === 0) return;
    setBatchGrading(true); setBatchError(null);
    try {
      const fd = new FormData();
      fd.append("question_file", batchQuestionFile);
      if (batchZipFile) fd.append("students_zip", batchZipFile);
      for (const f of batchStudentFiles) fd.append("students", f);
      
      // [重点] 传入修改后的参考答案
      fd.append("reference_text", newRefText);

      const weightsPayload = rubricWeightsText.trim();
      const threshold = batchPassThreshold.trim();
      const endpoint = useStrict ? "/grade-batch-strict" : "/grade-batch";

      if (useStrict) {
        if (rubricText.trim()) fd.append("strict_rubric", rubricText.trim());
        if (rubricFile) fd.append("strict_rubric_file", rubricFile);
      } else {
        const rubricPayload = buildRubricField(rubricText);
        if (rubricPayload) fd.append("rubric", rubricPayload);
        if (rubricFile) fd.append("rubric_file", rubricFile);
      }
      if (weightsPayload) fd.append("rubric_weights", weightsPayload);
      if (threshold) fd.append("pass_threshold", threshold);

      const res = await fetch(`${apiBase || ""}${endpoint}`, { method: "POST", body: fd });
      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || errJson.error || `HTTP ${res.status}`);
      }

      const raw = await res.json();
      const userNames = getRubricNamesFromUser(rubricText);
      setBatchResult(normalizeBatchResponse(raw, userNames));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setBatchError(msg);
    } finally {
      setBatchGrading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900 pb-20">
      
      {/* Top Navigation */}
      <div className="sticky top-0 z-30 bg-white/80 backdrop-blur-md border-b border-slate-200">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="bg-indigo-600 rounded-lg p-1.5 shadow-sm">
              <LinkIcon className="h-5 w-5 text-white" />
            </div>
            <h1 className="text-lg font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-600 to-purple-600">
              AI Grading System
            </h1>
          </div>
          
          <div className="flex bg-slate-100 p-1 rounded-xl shadow-inner">
            <button
              onClick={() => setActiveTab("single")}
              className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 ${activeTab === "single" ? "bg-white text-indigo-600 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
            >
              <FileSignature className="h-4 w-4" /> Single Mode
            </button>
            <button
              onClick={() => setActiveTab("batch")}
              className={`flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-200 ${activeTab === "batch" ? "bg-white text-indigo-600 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
            >
              <Layers className="h-4 w-4" /> Batch Mode
            </button>
          </div>
        </div>
      </div>

      <main className="max-w-7xl mx-auto px-6 py-8 space-y-8">
        
        {/* System Status */}
        <SystemStatusCard
          apiBase={apiBase} onApiBaseChange={setApiBase} status={status} loading={loadingStatus} error={statusError} onRefresh={() => fetchSystemStatus(apiBase)}
        />

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          
          {/* Left Column: Shared Configuration (Rubric & Weights) */}
          <div className="lg:col-span-4 space-y-6 lg:sticky lg:top-24">
             <RubricSettings 
                rubricText={rubricText}
                onRubricTextChange={setRubricText}
                rubricParsed={rubricParsed}
                rubricWeightsText={rubricWeightsText}
                onRubricWeightsTextChange={setRubricWeightsText}
                rubricFile={rubricFile}
                onRubricFileChange={setRubricFile}
                useStrict={useStrict}
                onUseStrictChange={setUseStrict}
                hasDefaultRubric={Boolean(status?.default_rubric?.length)}
                onUseDefaultRubric={() => status?.default_rubric && setRubricText(status.default_rubric.join(", "))}
             />
             
             <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-700 leading-relaxed shadow-sm">
               <p className="font-semibold mb-1 flex items-center gap-1">ℹ️ Configuration Tip</p>
               This configuration applies to both Single and Batch grading modes. Set up your criteria once and utilize it across different workflows.
             </div>
          </div>

          {/* Right Column: Active Workflow (Single or Batch) */}
          <div className="lg:col-span-8 min-h-[500px]">
            <AnimatePresence mode="wait">
              {activeTab === "single" ? (
                <motion.div
                  key="single"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.2 }}
                  className="space-y-6"
                >
                  <SingleGradingCard
                    // Files
                    questionFile={questionFile} onQuestionFileChange={setQuestionFile}
                    studentFile={studentFile} onStudentFileChange={setStudentFile}
                    referenceFile={referenceFile} onReferenceFileChange={setReferenceFile}
                    // State
                    canSubmit={canSubmitSingle} grading={grading} gradeError={gradeError}
                    result={result} overallText={overallText}
                    // Actions
                    onSubmit={onSubmitSingle}
                    onExportJson={() => result && downloadJson("result.json", result)}
                    onResultChange={(u) => setResult(u)}
                    onRegradeWithRef={onRegradeSingleWithRef}
                  />
                </motion.div>
              ) : (
                <motion.div
                  key="batch"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.2 }}
                  className="space-y-6"
                >
                  <BatchGradingCard
                    // Files
                    questionFile={batchQuestionFile} onQuestionFileChange={setBatchQuestionFile}
                    referenceFile={batchReferenceFile} onReferenceFileChange={setBatchReferenceFile}
                    zipFile={batchZipFile} onZipFileChange={setBatchZipFile}
                    studentFiles={batchStudentFiles} onStudentFilesChange={setBatchStudentFiles}
                    // Options
                    passThreshold={batchPassThreshold} onPassThresholdChange={setBatchPassThreshold}
                    // State
                    canSubmit={canSubmitBatch} grading={batchGrading} error={batchError} result={batchResult}
                    // Actions
                    onSubmit={onSubmitBatch}
                    onExportJson={() => batchResult && downloadJson("batch_result.json", batchResult)}
                    onResultChange={(u) => setBatchResult(u)}
                    onRegradeWithRef={onRegradeBatchWithRef}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>

        </div>
      </main>
    </div>
  );
}