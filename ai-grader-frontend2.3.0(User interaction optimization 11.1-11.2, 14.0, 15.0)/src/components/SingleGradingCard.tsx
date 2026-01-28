// src/components/SingleGradingCard.tsx
import React, { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { FileUp, Loader2, Upload, FileText, CheckCircle2, Download } from "lucide-react";
import type { GradeResponse, RubricScore } from "../types/grading";

// --- PDF Imports ---
import { pdf } from "@react-pdf/renderer";
import { saveAs } from "file-saver";
import { GradingReportPDF } from "./pdf/GradingReportPDF";

interface SingleGradingCardProps {
  // Files
  questionFile: File | null;
  studentFile: File | null;
  referenceFile: File | null;
  onQuestionFileChange: (file: File | null) => void;
  onStudentFileChange: (file: File | null) => void;
  onReferenceFileChange: (file: File | null) => void;

  // State
  canSubmit: boolean;
  grading: boolean;
  gradeError: string | null;
  result: GradeResponse | null;
  overallText: string;

  // Actions
  onSubmit: () => void;
  onExportJson: () => void;
  onResultChange?: (updated: GradeResponse) => void;
  onRegradeWithRef?: (text: string) => void;
}

/**
 * 辅助函数：重新计算人工修改后的总分
 */
function recomputeOverallManual(
  scores: RubricScore[],
  weightsUsed?: Record<string, number> | null
): number {
  if (!scores.length) return 0;

  const useWeights = !!weightsUsed && Object.keys(weightsUsed).length > 0;
  let sumW = 0;
  let sumScoreW = 0;

  for (const s of scores) {
    const rawW = useWeights ? Number(weightsUsed![s.criterion] ?? 1) : 1;
    const w = Number.isFinite(rawW) && rawW > 0 ? rawW : 1;
    const score = Number.isFinite(s.score) ? s.score : 0;

    sumW += w;
    sumScoreW += score * w;
  }

  if (sumW === 0) return 0;
  const avg = sumScoreW / sumW;
  
  // 如果分数是 0-1 范围，则转为百分制；如果是 0-100 则保持
  const maxScore = Math.max(...scores.map((s) => Number.isFinite(s.score) ? (s.score as number) : 0));
  const scale = maxScore <= 1 ? 100 : 1;

  const overall = avg * scale;
  return Math.round(overall * 10) / 10;
}

export const SingleGradingCard: React.FC<SingleGradingCardProps> = ({
  questionFile,
  studentFile,
  referenceFile,
  onQuestionFileChange,
  onStudentFileChange,
  onReferenceFileChange,
  canSubmit,
  grading,
  gradeError,
  result,
  overallText,
  onSubmit,
  onExportJson,
  onResultChange,
  onRegradeWithRef,
}) => {
  // --- Local State ---
  const [reviewMode, setReviewMode] = useState(false);
  const [editedOverallComment, setEditedOverallComment] = useState<string>("");
  const [editedRubricScores, setEditedRubricScores] = useState<RubricScore[]>([]);
  
  // 参考答案编辑状态
  const [isEditingRef, setIsEditingRef] = useState(false);
  const [editedRefAnswer, setEditedRefAnswer] = useState("");
  
  // PDF 导出状态
  const [exportingPdf, setExportingPdf] = useState(false);
  const [includeRef, setIncludeRef] = useState(false); // 控制导出时是否包含参考答案

  // 当结果更新时，同步本地状态
  useEffect(() => {
    if (!result) {
      setEditedOverallComment("");
      setEditedRubricScores([]);
      setReviewMode(false);
      setIsEditingRef(false);
      setEditedRefAnswer("");
      return;
    }
    if (!reviewMode) {
      setEditedOverallComment(result.overall_comment ?? "");
      setEditedRubricScores(result.rubric_scores ? [...result.rubric_scores] : []);
    }
    if (result.reference_answer) {
      setEditedRefAnswer(result.reference_answer);
    }
  }, [result, reviewMode]);

  // --- Handlers: Manual Review ---

  const handleEditRubricScore = (index: number, field: "score" | "comment", value: string) => {
    setEditedRubricScores((prev) => {
      const next = [...prev];
      const item = { ...next[index] };
      if (field === "score") {
        const n = Number(value);
        item.score = Number.isFinite(n) ? n : 0;
      } else {
        item.comment = value;
      }
      next[index] = item;
      return next;
    });
  };

  const applyManualReview = () => {
    if (!result) return;
    const newOverall = recomputeOverallManual(editedRubricScores, result.weights_used);
    const updated: GradeResponse = {
      ...result,
      overall_score: newOverall,
      weighted_overall: newOverall,
      overall_comment: editedOverallComment,
      rubric_scores: editedRubricScores,
    };
    onResultChange?.(updated);
  };

  const cancelManualReview = () => {
    if (!result) { setReviewMode(false); return; }
    setEditedOverallComment(result.overall_comment ?? "");
    setEditedRubricScores(result.rubric_scores ? [...result.rubric_scores] : []);
    setReviewMode(false);
  };

  const handleRegradeClick = () => {
    if (onRegradeWithRef) {
      onRegradeWithRef(editedRefAnswer);
      setIsEditingRef(false);
    }
  };

  // --- Handler: PDF Export ---
  const handleExportPDF = async () => {
    if (!result) return;
    setExportingPdf(true);
    try {
      const safeFileName = studentFile?.name.replace(/\.[^/.]+$/, "") || "result";
      
      const blob = await pdf(
        <GradingReportPDF 
          data={result} 
          fileName={studentFile?.name} 
          showReference={includeRef} // 传递用户的选择
        />
      ).toBlob();
      
      saveAs(blob, `Grading_Report_${safeFileName}.pdf`);
    } catch (e) {
      console.error("PDF generation failed", e);
      alert("Failed to generate PDF");
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
            <Upload className="h-5 w-5 text-indigo-600" />
            Upload Assignment Files
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6 pt-6">
          <div className="grid grid-cols-1 gap-6">
            
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

            {/* Student File */}
            <div className="space-y-2">
              <Label>Student Answer <span className="text-rose-500">*</span></Label>
              <div className="relative">
                <Input 
                  type="file" 
                  onChange={(e) => onStudentFileChange(e.target.files?.[0] || null)} 
                  className="cursor-pointer file:cursor-pointer pr-10" 
                />
                {studentFile && <CheckCircle2 className="absolute right-3 top-2.5 h-4 w-4 text-emerald-500 pointer-events-none" />}
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
          </div>

          {/* Action Bar */}
          <div className="flex items-center gap-3 pt-2">
            <Button 
              disabled={!canSubmit} 
              onClick={onSubmit} 
              className="flex-1 shadow-indigo-200 shadow-lg transition-all hover:shadow-indigo-300"
            >
              {grading ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Grading...</>
              ) : (
                <><FileUp className="mr-2 h-4 w-4" /> Start Grading</>
              )}
            </Button>
          </div>
          
          {gradeError && (
            <div className="p-3 bg-rose-50 text-rose-600 rounded-lg text-sm border border-rose-100 mt-4">
              {gradeError}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 2. Results Card */}
      {result && (
        <Card className="shadow-lg border-0 ring-1 ring-slate-100 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <CardHeader className="flex flex-row items-center justify-between gap-4 border-b border-slate-100 bg-slate-50/50">
            <CardTitle className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-indigo-600" /> Grading Results
            </CardTitle>
            <div className="flex items-center gap-2">
              {reviewMode && <span className="text-xs text-amber-600 font-medium px-2 py-1 bg-amber-50 rounded">Editing Mode</span>}
              <Button 
                variant={reviewMode ? "default" : "outline"} 
                size="sm" 
                onClick={() => setReviewMode(!reviewMode)} 
                className={reviewMode ? "bg-amber-500 hover:bg-amber-600 text-white border-transparent" : ""}
              >
                {reviewMode ? "Exit Review" : "Manual Review"}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-8 pt-6">
            
            {/* Score & Feedback */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="p-6 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-lg shadow-indigo-200 flex flex-col justify-center items-center text-center">
                <div className="text-indigo-100 text-sm font-medium mb-1">Overall Score</div>
                <div className="text-5xl font-bold tracking-tight">{result.overall_score ?? "—"}</div>
                {typeof result.weighted_overall === "number" && (
                  <div className="mt-2 text-xs bg-white/20 inline-block px-2 py-1 rounded">Weighted</div>
                )}
              </div>
              <div className="md:col-span-2 p-6 rounded-2xl border border-slate-100 bg-white shadow-sm">
                <div className="text-slate-500 text-sm font-medium mb-2 uppercase tracking-wide">Overall Feedback</div>
                {reviewMode ? (
                  <Textarea 
                    className="min-h-[100px] border-slate-200 focus:border-indigo-300 resize-none" 
                    value={editedOverallComment} 
                    onChange={(e) => setEditedOverallComment(e.target.value)} 
                  />
                ) : (
                  <div className="whitespace-pre-wrap text-slate-700 leading-relaxed text-sm">
                    {overallText}
                  </div>
                )}
              </div>
            </div>

            {/* Rubric Table */}
            {result.rubric_scores?.length ? (
              <div className="rounded-xl border border-slate-100 overflow-hidden">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-slate-500">
                    <tr>
                      <th className="py-3 px-4 text-left font-medium">Dimension</th>
                      <th className="py-3 px-4 text-left font-medium w-24">Score</th>
                      <th className="py-3 px-4 text-left font-medium w-20">Weight</th>
                      <th className="py-3 px-4 text-left font-medium">Comments</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(reviewMode ? editedRubricScores : result.rubric_scores).map((r, idx) => (
                      <tr key={idx} className="hover:bg-slate-50/50 transition-colors">
                        <td className="py-3 px-4 font-medium text-slate-700">{r.criterion || "—"}</td>
                        <td className="py-3 px-4">
                          {reviewMode ? (
                            <Input 
                              type="number" 
                              min={0} 
                              max={1} 
                              step={0.1} 
                              className="h-8 w-20" 
                              value={r.score} 
                              onChange={(e) => handleEditRubricScore(idx, "score", e.target.value)} 
                            />
                          ) : (
                            <span className={`inline-flex px-2 py-1 rounded-md font-semibold ${
                              r.score === 1 ? 'bg-emerald-100 text-emerald-700' : 
                              r.score >= 0.5 ? 'bg-amber-100 text-amber-700' : 
                              'bg-rose-100 text-rose-700'
                            }`}>
                              {r.score}
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-slate-500">{r.weight ?? "1"}</td>
                        <td className="py-3 px-4 text-slate-600">
                          {reviewMode ? (
                            <Textarea 
                              className="min-h-[60px] text-xs" 
                              value={r.comment} 
                              onChange={(e) => handleEditRubricScore(idx, "comment", e.target.value)} 
                            />
                          ) : (
                            r.comment
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {/* Weights Used Tags */}
            {result.weights_used && Object.keys(result.weights_used).length > 0 && (
               <div className="flex flex-wrap gap-2 text-xs">
                 <span className="px-2 py-1 text-slate-400 font-medium">Weights applied:</span>
                 {Object.entries(result.weights_used).map(([name, w]) => (
                   <span key={name} className="px-2 py-1 bg-slate-100 text-slate-600 rounded-md border border-slate-200">
                     {name}: <b>{w}</b>
                   </span>
                 ))}
               </div>
            )}

            {/* Reference Answer Section */}
            {result && (
              <div className={`rounded-xl border p-5 transition-all ${isEditingRef ? 'border-indigo-200 bg-indigo-50/30' : 'border-slate-100 bg-slate-50/30'}`}>
                <div className="flex items-center justify-between mb-3">
                  <div className="font-semibold text-slate-700 flex items-center gap-2">
                    Reference Answer
                    {result.reference_answer_generated && (
                      <span className="text-[10px] uppercase tracking-wider bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                        Auto-Generated
                      </span>
                    )}
                  </div>
                  <Button 
                    variant={isEditingRef ? "secondary" : "outline"} 
                    size="sm" 
                    onClick={() => setIsEditingRef(!isEditingRef)} 
                    disabled={grading} 
                    className="h-8 text-xs"
                  >
                    {isEditingRef ? "Cancel Edit" : "Edit & Re-grade"}
                  </Button>
                </div>

                {isEditingRef ? (
                  <div className="space-y-4 animate-in fade-in slide-in-from-top-2">
                    <Textarea 
                      value={editedRefAnswer} 
                      onChange={(e) => setEditedRefAnswer(e.target.value)} 
                      className="min-h-[180px] font-mono text-sm bg-white shadow-sm border-indigo-200 focus:border-indigo-400" 
                    />
                    <div className="flex justify-between items-center">
                      <p className="text-xs text-indigo-600 font-medium">
                        ℹ️ Updating this will trigger a new AI grading process.
                      </p>
                      <Button 
                        onClick={handleRegradeClick} 
                        disabled={grading} 
                        className="bg-indigo-600 hover:bg-indigo-700 h-8 text-xs"
                      >
                        {grading ? <><Loader2 className="mr-2 h-3 w-3 animate-spin"/> Processing</> : "Confirm & Re-grade"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="prose prose-sm max-w-none text-slate-600 bg-white p-4 rounded-lg border border-slate-100 max-h-60 overflow-y-auto custom-scrollbar">
                    <pre className="whitespace-pre-wrap font-sans text-sm">{result.reference_answer || "(No reference text)"}</pre>
                  </div>
                )}
              </div>
            )}

            {/* Manual Review Actions Footer */}
            {reviewMode && (
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-100 sticky bottom-0 bg-white/95 backdrop-blur py-4 -mb-6 z-10">
                <Button variant="ghost" onClick={cancelManualReview}>Discard Changes</Button>
                <Button onClick={applyManualReview} className="bg-amber-500 hover:bg-amber-600">Apply Manual Changes</Button>
              </div>
            )}

            {/* Export Actions Footer */}
            {!reviewMode && (
              <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 border-t border-slate-100">
                {/* 左侧：参考答案开关 */}
                <div className="flex items-center gap-2">
                  <input 
                    type="checkbox" 
                    id="includeRefSingle"
                    className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-600 cursor-pointer"
                    checked={includeRef}
                    onChange={(e) => setIncludeRef(e.target.checked)}
                  />
                  <Label htmlFor="includeRefSingle" className="text-sm text-slate-600 cursor-pointer select-none">
                    Include Reference Answer in PDF
                  </Label>
                </div>

                {/* 右侧：按钮 */}
                <div className="flex gap-2">
                  <Button variant="outline" onClick={onExportJson}>
                    JSON
                  </Button>
                  <Button 
                    variant="outline" 
                    onClick={handleExportPDF}
                    disabled={exportingPdf}
                    className="border-indigo-200 text-indigo-700 hover:bg-indigo-50"
                  >
                    {exportingPdf ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <><Download className="mr-2 h-4 w-4" /> Download PDF</>
                    )}
                  </Button>
                </div>
              </div>
            )}

          </CardContent>
        </Card>
      )}
    </>
  );
};