// src/components/SystemStatusCard.tsx
import React from "react";
import { Card } from "./ui/card";
import { Input } from "./ui/input";
import { Button } from "./ui/button";
import {
  Activity,
  CheckCircle2,
  AlertCircle,
  Loader2,
  RefreshCw,
  Server,
  Cpu,
  FileImage,
  HardDrive,
  XCircle,
  FileText,
  FileQuestion
} from "lucide-react";
import type { SystemStatus } from "../types/grading";

interface SystemStatusCardProps {
  apiBase: string;
  onApiBaseChange: (value: string) => void;
  status: SystemStatus | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

const StatusBadge = ({ active, label }: { active?: boolean; label: string }) => (
  <span
    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border ${
      active
        ? "bg-emerald-50 border-emerald-200 text-emerald-700"
        : "bg-slate-50 border-slate-200 text-slate-400"
    }`}
  >
    {active ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
    {label}
  </span>
);

// Helper: Convert MIME types to readable extensions
const getReadableExtensions = (mimeTypes: string[] = []): string => {
  const map: Record<string, string> = {
    'application/pdf': 'PDF',
    'text/plain': 'TXT',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
    'application/msword': 'DOC',
    'image/png': 'PNG',
    'image/jpeg': 'JPG',
    'image/webp': 'WEBP',
  };
  
  // Clean up and unique
  const exts = new Set(
    mimeTypes.map(t => map[t] || t.split('/')[1]?.toUpperCase() || 'FILE')
  );
  
  // Sort: PDF first, then images, then docs
  const sorted = Array.from(exts).sort((a, b) => {
    const priority = { PDF: 1, DOCX: 2, DOC: 3, TXT: 4 };
    return (priority[a as keyof typeof priority] || 99) - (priority[b as keyof typeof priority] || 99);
  });

  return sorted.join(', ');
};

export const SystemStatusCard: React.FC<SystemStatusCardProps> = ({
  apiBase,
  onApiBaseChange,
  status,
  loading,
  error,
  onRefresh,
}) => {
  const isHealthy = status?.status === "ok";
  const supportedTypesStr = getReadableExtensions(status?.limits?.allowed_types);

  return (
    <Card className="shadow-sm border-slate-200 overflow-hidden bg-white">
      {/* Header Section: Connection & Status */}
      <div className="p-4 border-b border-slate-100 flex flex-col md:flex-row md:items-center justify-between gap-4 bg-slate-50/50">
        <div className="flex items-center gap-3">
          <div
            className={`p-2 rounded-lg border ${
              isHealthy
                ? "bg-emerald-100/50 border-emerald-100 text-emerald-600"
                : error
                ? "bg-rose-100/50 border-rose-100 text-rose-600"
                : "bg-slate-100 border-slate-200 text-slate-500"
            }`}
          >
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-800 text-sm">System Connection</h3>
            <div className="text-xs mt-0.5 flex items-center gap-2">
              {loading ? (
                <span className="text-indigo-600 flex items-center gap-1.5">
                  <Loader2 className="h-3 w-3 animate-spin" /> Connecting...
                </span>
              ) : error ? (
                <span className="text-rose-600 flex items-center gap-1.5">
                  <AlertCircle className="h-3 w-3" /> Connection Failed
                </span>
              ) : isHealthy ? (
                <span className="text-emerald-600 flex items-center gap-1.5">
                  <CheckCircle2 className="h-3 w-3" /> Online & Ready
                </span>
              ) : (
                <span className="text-slate-400">Waiting for check...</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 md:w-72">
            <Server className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input
              placeholder="API Base URL (e.g. http://localhost:8000)"
              value={apiBase}
              onChange={(e) => onApiBaseChange(e.target.value)}
              className="pl-9 h-9 text-xs bg-white shadow-sm"
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={loading}
            className="h-9 px-3 hover:bg-white hover:text-indigo-600 transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Details Grid */}
      {status && !error && (
        <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-slate-100">
          
          {/* 1. Backend Version */}
          <div className="p-4 flex flex-col gap-2 hover:bg-slate-50/30 transition-colors">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400 uppercase tracking-wider">
              <Cpu className="h-3.5 w-3.5" /> Backend Version
            </div>
            <div className="font-mono text-sm font-semibold text-slate-700">
              v{status.version || "Unknown"}
            </div>
          </div>

          {/* 2. OCR Capabilities */}
          <div className="p-4 flex flex-col gap-2 hover:bg-slate-50/30 transition-colors">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400 uppercase tracking-wider">
              <FileImage className="h-3.5 w-3.5" /> OCR Engine
            </div>
            <div className="flex gap-2">
              <StatusBadge active={status.ocr?.mathpix} label="Mathpix" />
              <StatusBadge active={status.ocr?.vision} label="Vision (GPT-5)" />
            </div>
          </div>

          {/* 3. Upload Limits (Modified) */}
          <div className="p-4 flex flex-col gap-3 hover:bg-slate-50/30 transition-colors">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-medium text-slate-400 uppercase tracking-wider">
                <HardDrive className="h-3.5 w-3.5" /> Supported Files
              </div>
              <span className="text-[10px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-500 font-medium">
                Max {status.limits?.max_file_mb ?? 10}MB
              </span>
            </div>
            
            {/* Split display for Question / Answer as requested */}
            <div className="space-y-1.5">
              <div className="flex items-start gap-2">
                <FileQuestion className="h-3.5 w-3.5 text-indigo-400 mt-0.5 shrink-0" />
                <div className="text-xs text-slate-600 leading-tight">
                  <span className="font-semibold text-slate-700 block mb-0.5">Question Files</span>
                  {supportedTypesStr}
                </div>
              </div>
              <div className="w-full h-px bg-slate-50"></div>
              <div className="flex items-start gap-2">
                <FileText className="h-3.5 w-3.5 text-emerald-400 mt-0.5 shrink-0" />
                <div className="text-xs text-slate-600 leading-tight">
                  <span className="font-semibold text-slate-700 block mb-0.5">Answer / Reference</span>
                  {supportedTypesStr}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="p-4 bg-rose-50 border-t border-rose-100">
          <p className="text-xs text-rose-600 font-mono break-all flex gap-2">
            <span className="font-bold shrink-0">ERROR:</span> {error}
          </p>
        </div>
      )}
    </Card>
  );
};