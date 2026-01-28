// src/components/RubricSettings.tsx
import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Scale, BookOpen, FileText } from "lucide-react";
import type { JsonValue } from "../types/grading";

interface RubricSettingsProps {
  rubricText: string;
  onRubricTextChange: (text: string) => void;
  rubricParsed: JsonValue[] | null;
  
  rubricWeightsText: string;
  onRubricWeightsTextChange: (text: string) => void;
  
  rubricFile: File | null;
  onRubricFileChange: (file: File | null) => void;
  
  useStrict: boolean;
  onUseStrictChange: (value: boolean) => void;
  
  onUseDefaultRubric: () => void;
  hasDefaultRubric: boolean;
}

export const RubricSettings: React.FC<RubricSettingsProps> = ({
  rubricText,
  onRubricTextChange,
  rubricParsed,
  rubricWeightsText,
  onRubricWeightsTextChange,
  rubricFile,
  onRubricFileChange,
  useStrict,
  onUseStrictChange,
  onUseDefaultRubric,
  hasDefaultRubric,
}) => {
  return (
    <Card className="shadow-sm border-slate-200 h-full">
      <CardHeader className="pb-3 bg-slate-50/50 border-b border-slate-100">
        <CardTitle className="flex items-center gap-2 text-slate-800 text-base">
          <Scale className="h-4 w-4 text-indigo-600" />
          Configuration (Applied to All)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 pt-5">
        
        {/* Strict Mode Toggle */}
        <div className="flex items-center justify-between p-3 rounded-lg border border-indigo-100 bg-indigo-50/30">
          <div className="space-y-0.5">
            <Label className="text-sm font-semibold text-slate-900">Strict Grading</Label>
            <p className="text-xs text-slate-500">
              Force strict adherence to rubric.
            </p>
          </div>
          <input
            type="checkbox"
            className="accent-indigo-600 h-4 w-4 cursor-pointer"
            checked={useStrict}
            onChange={(e) => onUseStrictChange(e.target.checked)}
          />
        </div>

        {/* Rubric Section */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider">
              <BookOpen className="h-3 w-3" /> Rubric
            </Label>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 text-[10px] text-slate-500 hover:text-indigo-600 px-2"
              onClick={onUseDefaultRubric}
              disabled={!hasDefaultRubric}
            >
              Load Default
            </Button>
          </div>
          
          <Textarea
            value={rubricText}
            onChange={(e) => onRubricTextChange(e.target.value)}
            placeholder={useStrict 
              ? 'Strict Mode: Paste detailed JSON rubric or text description...' 
              : 'Simple Mode: "Completeness, Method, Final Answer"'}
            className="h-32 font-mono text-xs bg-slate-50 focus:bg-white transition-colors resize-none"
          />

          {/* File Upload (Modified) */}
          <div className={`relative group transition-opacity duration-200 ${!useStrict ? "opacity-50" : ""}`}>
            {/* Background Style: Only show hover effect if active */}
            <div className={`absolute inset-0 bg-slate-100 rounded-lg border border-dashed border-slate-300 ${useStrict ? "group-hover:border-indigo-400" : ""} transition-colors pointer-events-none`} />
            
            <Input
              type="file"
              disabled={!useStrict} // [核心修改] 禁用输入
              accept=".pdf,.doc,.docx,.txt,text/plain,image/*"
              onChange={(e) => onRubricFileChange(e.target.files?.[0] || null)}
              className={`relative z-10 opacity-0 h-9 w-full ${useStrict ? "cursor-pointer" : "cursor-not-allowed"}`} // [样式修改] 禁用时显示禁止光标
            />
            
            <div className="absolute inset-0 flex items-center px-3 pointer-events-none">
              {rubricFile ? (
                <div className={`flex items-center gap-2 text-xs font-medium truncate ${useStrict ? "text-indigo-700" : "text-slate-500"}`}>
                  <FileText className="h-3 w-3" /> {rubricFile.name}
                </div>
              ) : (
                <span className="text-xs text-slate-400">
                  {/* [文案修改] 根据状态显示不同提示 */}
                  {useStrict ? "Or upload rubric file (PDF/Doc)..." : "Enable Strict Grading to upload file"}
                </span>
              )}
            </div>
          </div>
          
          <div className="text-[10px] text-slate-400 pl-1 flex justify-between">
            <span>
                {rubricParsed ? "✓ Valid JSON rubric detected" : "ℹ️ Supports Text, JSON, or Files"}
            </span>
          </div>
        </div>

        {/* Weights */}
        <div className="space-y-2 pt-4 border-t border-slate-100">
          <Label className="flex items-center gap-1.5 text-xs font-semibold text-slate-700 uppercase tracking-wider">
            <Scale className="h-3 w-3" /> Weights
          </Label>
          <Textarea
            value={rubricWeightsText}
            onChange={(e) => onRubricWeightsTextChange(e.target.value)}
            placeholder='e.g. "2, 1, 3" OR {"Method": 2, "Result": 1}'
            className="h-16 font-mono text-xs bg-slate-50 focus:bg-white resize-none"
          />
        </div>

      </CardContent>
    </Card>
  );
};