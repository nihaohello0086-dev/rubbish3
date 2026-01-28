// src/components/BatchGradingCard.tsx
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { FileUp, Loader2, Archive, Files, CheckCircle2, AlertCircle, Download, UploadCloud, X } from "lucide-react";
import type { BatchGradeResponse, RubricScore, GradeResponse } from "../types/grading";

// --- PDF & Zip Imports ---
import { pdf } from "@react-pdf/renderer";
import { saveAs } from "file-saver";
import JSZip from "jszip";
import { BatchSummaryPDF } from "./pdf/BatchSummaryPDF";
import { GradingReportPDF } from "./pdf/GradingReportPDF";

interface BatchGradingCardProps {
  // Files
  questionFile: File | null;
  referenceFile: File | null;
  zipFile: File | null;
  studentFiles: File[];
  onQuestionFileChange: (file: File | null) => void;
  onReferenceFileChange: (file: File | null) => void;
  onZipFileChange: (file: File | null) => void;
  onStudentFilesChange: (files: File[]) => void;

  // Options
  passThreshold: string;
  onPassThresholdChange: (value: string) => void;

  // State
  canSubmit: boolean;
  grading: boolean;
  error: string | null;
  result: BatchGradeResponse | null;

  // Actions
  onSubmit: () => void;
  onExportJson: () => void;
  onResultChange?: (updated: BatchGradeResponse) => void;
  onRegradeWithRef?: (text: string) => void;
}

// 辅助函数：重算单个学生分数
function recomputeOverallManualForItem(scores: RubricScore[], weightsUsed?: Record<string, number> | null): number {
    if (!scores.length) return 0;
    const hasWeights = !!weightsUsed && Object.keys(weightsUsed).length > 0;
    let sumW = 0; let sumScoreW = 0;
    for (const s of scores) {
        const rawW = hasWeights ? Number(weightsUsed![s.criterion] ?? 1) : 1;
        const w = Number.isFinite(rawW) && rawW > 0 ? rawW : 1;
        const score = Number.isFinite(s.score) ? s.score : 0;
        sumW += w; sumScoreW += score * w;
    }
    if (sumW === 0) return 0;
    const avg = sumScoreW / sumW;
    const maxScore = Math.max(...scores.map((s) => Number.isFinite(s.score) ? (s.score as number) : 0));
    const scale = maxScore <= 1 ? 100 : 1;
    return Math.round(avg * scale * 10) / 10;
}

// 辅助函数：重算批量统计
function recomputeBatchSummary(items: BatchGradeResponse["items"], passThreshold: string): BatchGradeResponse["summary"] {
    const scores: number[] = [];
    for (const it of items) { if (it.ok && it.result && typeof it.result.overall_score === "number") { scores.push(it.result.overall_score); } }
    if (!scores.length) return { avg: 0, min: 0, max: 0, stdev: 0, pass_rate: 0 };
    const n = scores.length; const sum = scores.reduce((a, b) => a + b, 0); const avg = sum / n; const min = Math.min(...scores); const max = Math.max(...scores); const mean = avg; const stdev = Math.sqrt(scores.reduce((acc, x) => acc + (x - mean) * (x - mean), 0) / n);
    const th = Number(passThreshold); const threshold = Number.isFinite(th) ? th : 60; const passCount = scores.filter((s) => s >= threshold).length; const passRate = (passCount / n) * 100;
    return { avg: Math.round(avg * 10) / 10, min, max, stdev: Math.round(stdev * 10) / 10, pass_rate: Math.round(passRate * 10) / 10 };
}

export const BatchGradingCard: React.FC<BatchGradingCardProps> = ({
  questionFile,
  referenceFile,
  zipFile,
  studentFiles,
  onQuestionFileChange,
  onReferenceFileChange,
  onZipFileChange,
  onStudentFilesChange,
  passThreshold,
  onPassThresholdChange,
  canSubmit,
  grading,
  error,
  result,
  onSubmit,
  onExportJson,
  onResultChange,
  onRegradeWithRef,
}) => {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  
  // 编辑单个学生状态
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [editedFeedback, setEditedFeedback] = useState<string>("");
  const [editedRubricScores, setEditedRubricScores] = useState<RubricScore[]>([]);
  
  // 批量参考答案编辑状态
  const [isEditingBatchRef, setIsEditingBatchRef] = useState(false);
  const [editedBatchRefAnswer, setEditedBatchRefAnswer] = useState("");
  
  // PDF 导出状态
  const [exportingPdf, setExportingPdf] = useState(false);
  const [includeRef, setIncludeRef] = useState(false);

  useEffect(() => {
    if (result?.reference_answer) {
      setEditedBatchRefAnswer(result.reference_answer);
    }
  }, [result]);

  // --- 智能文件上传处理逻辑 ---
  const handleStudentFilesUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) {
        onZipFileChange(null);
        onStudentFilesChange([]);
        return;
    }

    const fileList = Array.from(files);
    // 检查是否包含 ZIP 文件
    const zipFileFound = fileList.find(f => f.name.toLowerCase().endsWith('.zip'));

    if (zipFileFound) {
        // 规则：如果选中了 ZIP，则不允许与其他文件混选（或选多个 ZIP）
        if (fileList.length > 1) {
            alert("Upload Error: You cannot upload a ZIP file mixed with other files.\n\nPlease select either a SINGLE ZIP file OR multiple document files.");
            e.target.value = ""; // 清空选择
            return;
        }
        // ZIP 模式
        onZipFileChange(zipFileFound);
        onStudentFilesChange([]); 
    } else {
        // 多文件模式
        onZipFileChange(null);
        onStudentFilesChange(fileList);
    }
  };

  const clearSelection = () => {
    onZipFileChange(null);
    onStudentFilesChange([]);
  };

  // Review logic
  const beginReviewForItem = (id: string) => {
    if (!result) return;
    const item = result.items.find((it) => it.id === id);
    if (!item || !item.result) return;
    setExpandedId(id);
    setEditingItemId(id);
    setEditedFeedback(item.result.feedback ?? "");
    setEditedRubricScores(item.result.rubric_scores ? [...item.result.rubric_scores] : []);
  };

  const cancelReviewForItem = () => { setEditingItemId(null); setEditedFeedback(""); setEditedRubricScores([]); };

  const handleEditRubricScore = (index: number, field: "score" | "comment", value: string) => {
    setEditedRubricScores((prev) => {
      const next = [...prev]; const item = { ...next[index] };
      if (field === "score") { const n = Number(value); item.score = Number.isFinite(n) ? n : 0; } else { item.comment = value; }
      next[index] = item; return next;
    });
  };

  const applyReviewForItem = () => {
    if (!result || !editingItemId) return;
    const idx = result.items.findIndex((it) => it.id === editingItemId);
    if (idx === -1) return;
    const item = result.items[idx]; if (!item.result) return;
    const newOverall = recomputeOverallManualForItem(editedRubricScores, result.weights_used ?? undefined);
    const updatedItem = { ...item, result: { ...item.result, overall_score: newOverall, weighted_overall: newOverall, feedback: editedFeedback, rubric_scores: editedRubricScores } };
    const newItems = [...result.items]; newItems[idx] = updatedItem;
    const newSummary = recomputeBatchSummary(newItems, passThreshold);
    onResultChange?.({ ...result, items: newItems, summary: newSummary });
    cancelReviewForItem();
  };

  const handleBatchRegradeClick = () => {
    if (onRegradeWithRef) { onRegradeWithRef(editedBatchRefAnswer); setIsEditingBatchRef(false); }
  };

  // --- Batch PDF Export ---
  const handleBatchExportPDF = async () => {
    if (!result) return;
    setExportingPdf(true);
    
    try {
      const zip = new JSZip();
      
      const summaryBlob = await pdf(
         <BatchSummaryPDF data={result} showReference={includeRef} />
      ).toBlob();
      zip.file("Batch_Summary_Report.pdf", summaryBlob);
      
      const studentsFolder = zip.folder("individual_reports");
      
      const promises = result.items.map(async (item) => {
        if (item.ok && item.result) {
          const pdfData: GradeResponse = {
             overall_score: item.result.overall_score,
             overall_comment: item.result.feedback,
             rubric_scores: item.result.rubric_scores || [],
             weighted_overall: item.result.weighted_overall,
             reference_answer: result.reference_answer 
          };

          const studentBlob = await pdf(
            <GradingReportPDF data={pdfData} fileName={item.file} showReference={includeRef} />
          ).toBlob();
          
          const safeName = item.file.replace(/\.[^/.]+$/, "") + ".pdf";
          studentsFolder?.file(safeName, studentBlob);
        }
      });
      
      await Promise.all(promises);
      
      const content = await zip.generateAsync({ type: "blob" });
      const dateStr = new Date().toISOString().slice(0, 10);
      saveAs(content, `Batch_Grading_Results_${dateStr}.zip`);
      
    } catch (e) {
      console.error("Batch PDF export failed", e);
      alert("Error generating batch report");
    } finally {
      setExportingPdf(false);
    }
  };

  return (
    <>
      {/* 1. Upload Card */}
      <Card className="shadow-md border-0 bg-white">
        <CardHeader className="pb-3 border-b border-slate-100">
          <CardTitle className="flex items-center gap-2 text-slate-800">
            <Files className="h-5 w-5 text-indigo-600" /> Batch Processing Setup
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6 pt-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            {/* Question File */}
            <div className="space-y-2">
              <Label>Question File <span className="text-rose-500">*</span></Label>
              <div className="relative">
                <Input 
                  type="file" 
                  onChange={(e) => onQuestionFileChange(e.target.files?.[0] || null)} 
                  className="cursor-pointer file:cursor-pointer pr-10" 
                />
                {questionFile && <CheckCircle2 className="absolute right-3 top-2.5 h-4 w-4 text-emerald-500 pointer-events-none" />}
              </div>
            </div>

            {/* Reference File */}
            <div className="space-y-2">
              <div className="flex justify-between">
                <Label>Reference Answer (Optional)</Label>
                <span className="text-[10px] text-slate-400">If skipped, AI will generate one.</span>
              </div>
              <div className="relative">
                <Input 
                  type="file" 
                  onChange={(e) => onReferenceFileChange(e.target.files?.[0] || null)} 
                  className="cursor-pointer file:cursor-pointer pr-10" 
                />
                {referenceFile && <CheckCircle2 className="absolute right-3 top-2.5 h-4 w-4 text-emerald-500 pointer-events-none" />}
              </div>
            </div>
            
            {/* Unified Student Files Area */}
            <div className="md:col-span-2 space-y-2">
                <div className="flex justify-between items-end">
                    <Label className="flex items-center gap-2">
                        <UploadCloud className="h-4 w-4 text-indigo-600" /> Student Submissions <span className="text-rose-500">*</span>
                    </Label>
                    {(zipFile || studentFiles.length > 0) && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-1 rounded-full border border-emerald-100">
                                {zipFile 
                                    ? `ZIP Mode: ${zipFile.name}` 
                                    : `Multi-File Mode: ${studentFiles.length} files selected`
                                }
                            </span>
                            <button onClick={clearSelection} className="text-slate-400 hover:text-rose-500 transition-colors" title="Clear selection">
                                <X className="h-4 w-4" />
                            </button>
                        </div>
                    )}
                </div>

                <div className="relative group">
                    <div className="absolute inset-0 bg-slate-50 rounded-xl border border-dashed border-slate-300 group-hover:border-indigo-400 group-hover:bg-indigo-50/10 transition-colors pointer-events-none" />
                    
                    <div className="relative z-10 p-8 flex flex-col items-center justify-center text-center cursor-pointer">
                        <Input 
                            type="file" 
                            multiple 
                            accept=".zip,.pdf,.doc,.docx,.txt,.jpg,.jpeg,.png"
                            onChange={handleStudentFilesUpload} 
                            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" 
                        />
                        
                        {!zipFile && studentFiles.length === 0 ? (
                            <>
                                <div className="p-3 bg-white rounded-full shadow-sm mb-3">
                                    <Archive className="h-6 w-6 text-indigo-500" />
                                </div>
                                <p className="text-sm font-medium text-slate-700">
                                    Drag & drop or click to upload submissions
                                </p>
                                <p className="text-xs text-slate-500 mt-1 max-w-md">
                                    Supports: <b>Single ZIP file</b> (recommended for batch) <br/>
                                    OR <b>Multiple individual files</b> (PDF, Word, Images).
                                </p>
                                <div className="mt-3 text-[10px] text-amber-600 bg-amber-50 px-2 py-1 rounded border border-amber-100 flex items-center gap-1">
                                    <AlertCircle className="h-3 w-3" />
                                    Note: ZIP file cannot be selected together with other files.
                                </div>
                            </>
                        ) : (
                            <div className="flex flex-col items-center animate-in fade-in zoom-in duration-300">
                                {zipFile ? (
                                    <>
                                        <Archive className="h-10 w-10 text-emerald-500 mb-2" />
                                        <p className="text-sm font-semibold text-emerald-700">Ready to upload ZIP</p>
                                        <p className="text-xs text-slate-500">{zipFile.name}</p>
                                    </>
                                ) : (
                                    <>
                                        <Files className="h-10 w-10 text-emerald-500 mb-2" />
                                        <p className="text-sm font-semibold text-emerald-700">Ready to upload {studentFiles.length} files</p>
                                        <p className="text-xs text-slate-500">Click to change selection</p>
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
          </div>

          {/* Action Bar */}
          <div className="flex items-end gap-4 mt-2">
            <div className="w-32">
              <Label>Pass Threshold</Label>
              <Input type="number" step="0.1" min="0" max="100" value={passThreshold} onChange={(e) => onPassThresholdChange(e.target.value)} className="mt-1" />
            </div>
            <Button disabled={!canSubmit} onClick={onSubmit} className="flex-1 shadow-indigo-200 shadow-lg hover:shadow-indigo-300">
              {grading ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Batch Processing...</>
              ) : (
                <><FileUp className="mr-2 h-4 w-4" /> Start Batch Grading</>
              )}
            </Button>
          </div>
          
          {error && (
            <div className="p-3 bg-rose-50 text-rose-600 rounded-lg text-sm border border-rose-100 flex items-center gap-2">
              <AlertCircle className="h-4 w-4"/> {error}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 2. Results Card */}
      {result && (
        <Card className="shadow-lg border-0 ring-1 ring-slate-100 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <CardHeader className="border-b border-slate-100 bg-slate-50/50">
            <CardTitle className="flex items-center gap-2">
              <Files className="h-5 w-5 text-indigo-600" /> Batch Analysis Results
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-8 pt-6">
            
            {/* Global Reference Answer (Editable) */}
            <div className={`rounded-xl border p-5 transition-all ${isEditingBatchRef ? 'border-indigo-200 bg-indigo-50/30' : 'border-slate-100 bg-slate-50/30'}`}>
              <div className="flex items-center justify-between mb-3">
                <div className="font-semibold text-slate-700 flex items-center gap-2">
                  Global Reference Answer
                  {result.reference_answer_generated && (
                    <span className="text-[10px] uppercase tracking-wider bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                      Auto-Generated
                    </span>
                  )}
                </div>
                <Button 
                  variant={isEditingBatchRef ? "secondary" : "outline"} 
                  size="sm" 
                  onClick={() => setIsEditingBatchRef(!isEditingBatchRef)} 
                  disabled={grading} 
                  className="h-7 text-xs"
                >
                  {isEditingBatchRef ? "Cancel" : "Edit & Re-grade All"}
                </Button>
              </div>
              
              {isEditingBatchRef ? (
                <div className="space-y-4 animate-in fade-in slide-in-from-top-2">
                  <p className="text-xs text-indigo-600 font-medium bg-indigo-50 p-2 rounded border border-indigo-100 flex items-center gap-2">
                    <AlertCircle className="h-3 w-3" />
                    <b>Warning:</b> Modifying this answer will trigger a re-grading process for all <b>{result.count} items</b>.
                  </p>
                  <Textarea 
                    value={editedBatchRefAnswer} 
                    onChange={(e) => setEditedBatchRefAnswer(e.target.value)} 
                    className="min-h-[150px] bg-white font-mono text-sm shadow-sm" 
                  />
                  <div className="flex justify-end">
                    <Button onClick={handleBatchRegradeClick} disabled={grading} className="bg-indigo-600 hover:bg-indigo-700 h-8 text-xs">
                      {grading ? <><Loader2 className="mr-2 h-3 w-3 animate-spin"/> Processing...</> : "Confirm & Re-grade Batch"}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="prose prose-sm max-w-none text-slate-600 bg-white p-4 rounded-lg border border-slate-100 max-h-40 overflow-y-auto custom-scrollbar">
                  <pre className="whitespace-pre-wrap font-sans text-sm">{result.reference_answer || "(No reference text)"}</pre>
                </div>
              )}
            </div>

            {/* Stats Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: "Total Items", val: result.count, sub: `Success: ${result.success_count} · Fail: ${result.fail_count}` },
                { label: "Average Score", val: result.summary?.avg ?? "—", sub: `Min: ${result.summary?.min ?? 0} · Max: ${result.summary?.max ?? 0}` },
                { label: "Std Deviation", val: result.summary?.stdev ?? "—", sub: "Variability" },
                { label: "Pass Rate", val: result.summary ? `${result.summary.pass_rate.toFixed(1)}%` : "—", sub: `Threshold: ${passThreshold}` },
              ].map((stat, i) => (
                <div key={i} className="p-4 rounded-xl border border-slate-100 bg-white shadow-sm flex flex-col hover:shadow-md transition-shadow">
                  <span className="text-slate-500 text-xs uppercase tracking-wider font-semibold">{stat.label}</span>
                  <span className="text-2xl font-bold text-slate-800 my-1">{stat.val}</span>
                  <span className="text-xs text-slate-400">{stat.sub}</span>
                </div>
              ))}
            </div>

            {/* Rubric Tags */}
            <div className="flex flex-wrap gap-2">
              <span className="text-xs text-slate-400 self-center">Rubric:</span>
              {result.rubric_used.map(r => (
                <span key={r} className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">
                  {r}
                </span>
              ))}
            </div>

            {/* Table */}
            <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="py-3 px-4 text-left text-slate-500 font-semibold w-16">ID</th>
                    <th className="py-3 px-4 text-left text-slate-500 font-semibold w-1/4">File</th>
                    <th className="py-3 px-4 text-left text-slate-500 font-semibold w-20">Status</th>
                    <th className="py-3 px-4 text-left text-slate-500 font-semibold w-20">Score</th>
                    <th className="py-3 px-4 text-left text-slate-500 font-semibold w-20">Weighted</th>
                    <th className="py-3 px-4 text-left text-slate-500 font-semibold">Feedback Summary</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {result.items.map((it, idx) => {
                    const isExpanded = expandedId === it.id;
                    const isEditing = editingItemId === it.id;
                    return (
                      <React.Fragment key={idx}>
                        <tr className={`group transition-colors ${isExpanded ? 'bg-slate-50' : 'hover:bg-slate-50/50'}`}>
                          <td className="py-3 px-4 font-mono text-xs text-slate-400">{it.id}</td>
                          <td className="py-3 px-4 text-slate-700 font-medium truncate max-w-[150px]" title={it.file}>{it.file}</td>
                          <td className="py-3 px-4">
                            {it.ok ? (
                              <span className="text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded text-xs font-semibold">OK</span>
                            ) : (
                              <span className="text-rose-700 bg-rose-50 border border-rose-100 px-2 py-0.5 rounded text-xs font-semibold">FAIL</span>
                            )}
                          </td>
                          <td className="py-3 px-4 font-bold text-slate-800">{it.result?.overall_score ?? "—"}</td>
                          <td className="py-3 px-4 text-slate-500">{it.result?.weighted_overall ?? "—"}</td>
                          <td className="py-3 px-4">
                            <div className="flex flex-col gap-1">
                              <span className="text-slate-600 line-clamp-1 text-xs">{it.result?.feedback || it.error}</span>
                              {it.result && (
                                <div className="flex gap-3 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                  <button 
                                    onClick={() => setExpandedId(prev => prev === it.id ? null : it.id)} 
                                    className="text-[10px] font-semibold text-indigo-600 hover:text-indigo-800"
                                  >
                                    {isExpanded ? "Hide Details" : "View Details"}
                                  </button>
                                  <button 
                                    onClick={() => beginReviewForItem(it.id)} 
                                    className="text-[10px] font-semibold text-amber-600 hover:text-amber-800"
                                  >
                                    Review
                                  </button>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                        {/* Detail Row */}
                        {isExpanded && it.result && (
                          <tr className="bg-slate-50/50 shadow-inner">
                            <td colSpan={6} className="p-4">
                              <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-4">
                                {isEditing ? (
                                  <div className="space-y-1">
                                    <Label className="text-xs text-amber-600 font-semibold">Editing Feedback</Label>
                                    <Textarea value={editedFeedback} onChange={(e) => setEditedFeedback(e.target.value)} className="text-xs min-h-[80px]" />
                                  </div>
                                ) : (
                                  <div className="text-xs text-slate-600 bg-slate-50 p-3 rounded border border-slate-100">
                                    <b>Feedback:</b> {it.result.feedback}
                                  </div>
                                )}
                                
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="text-slate-400 border-b border-slate-100">
                                      <th className="text-left py-2 font-medium">Criteria</th>
                                      <th className="text-left py-2 font-medium w-16">Score</th>
                                      <th className="text-left py-2 font-medium">Comment</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {(isEditing ? editedRubricScores : it.result.rubric_scores || []).map((r, i) => (
                                      <tr key={i} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                                        <td className="py-2 font-medium text-slate-700 w-1/4">{r.criterion}</td>
                                        <td className="py-2">
                                          {isEditing ? (
                                            <Input 
                                              type="number" 
                                              min={0}
                                              max={1}
                                              step={0.1}
                                              className="h-6 w-14 text-xs" 
                                              value={r.score} 
                                              onChange={(e) => handleEditRubricScore(i, "score", e.target.value)} 
                                            />
                                          ) : (
                                            <span className={`inline-flex px-1.5 py-0.5 rounded font-semibold ${r.score === 1 ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'}`}>{r.score}</span>
                                          )}
                                        </td>
                                        <td className="py-2 text-slate-500">
                                          {isEditing ? (
                                            <Textarea className="h-10 text-xs" value={r.comment} onChange={(e) => handleEditRubricScore(i, "comment", e.target.value)} />
                                          ) : (
                                            r.comment
                                          )}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                                
                                {isEditing && (
                                  <div className="flex gap-2 justify-end pt-2">
                                    <Button variant="ghost" size="sm" onClick={cancelReviewForItem} className="h-7 text-xs">Cancel</Button>
                                    <Button size="sm" onClick={applyReviewForItem} className="h-7 text-xs bg-amber-500 hover:bg-amber-600 text-white">Save Changes</Button>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

             {/* Export Actions Footer */}
             <div className="flex flex-col sm:flex-row items-center justify-between gap-4 p-6 border-t border-slate-100 bg-slate-50/50 rounded-b-xl mt-4">
                {/* 左侧：参考答案开关 */}
                <div className="flex items-center gap-2">
                    <input 
                      type="checkbox" 
                      id="includeRefBatch"
                      className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600 cursor-pointer"
                      checked={includeRef}
                      onChange={(e) => setIncludeRef(e.target.checked)}
                    />
                    <Label htmlFor="includeRefBatch" className="text-sm text-slate-600 cursor-pointer select-none">
                      Include Reference Answer in All Reports
                    </Label>
                </div>

                {/* 右侧：按钮 */}
                <div className="flex gap-2">
                    <Button variant="outline" onClick={onExportJson}>
                      JSON
                    </Button>
                    <Button 
                      variant="outline" 
                      onClick={handleBatchExportPDF}
                      disabled={exportingPdf}
                      className="border-indigo-200 text-indigo-700 hover:bg-indigo-50 shadow-sm"
                    >
                      {exportingPdf ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <><Download className="mr-2 h-4 w-4" /> Export Report (ZIP)</>
                      )}
                    </Button>
                 </div>
             </div>

          </CardContent>
        </Card>
      )}
    </>
  );
};