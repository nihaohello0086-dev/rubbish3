// frontend/src/components/pdf/BatchSummaryPDF.tsx
import React from "react";
import { Document, Page, Text, View } from "@react-pdf/renderer";
import { styles } from "./pdfConfig";
import type { BatchGradeResponse } from "../../types/grading";

interface Props {
  data: BatchGradeResponse;
  showReference?: boolean; // [新增]
}

export const BatchSummaryPDF: React.FC<Props> = ({ 
  data, 
  showReference = false 
}) => {
  // 1. 准备动态列数据
  const rubricKeys = data.rubric_used || [];
  const hasRubric = rubricKeys.length > 0;
  
  // 2. 计算动态列宽
  // 固定列：文件名(25%) + 状态(10%) + 总分(10%) = 45%
  // 剩余 55% 的空间平分给所有 Rubric Items
  const fixedWidth = 45; 
  const remainingWidth = 100 - fixedWidth;
  const rubricColWidth = hasRubric ? (remainingWidth / rubricKeys.length) + "%" : "0%";

  // 3. 决定页面方向：如果列数太多(>5)，使用横向布局
  const pageOrientation = hasRubric && rubricKeys.length > 5 ? "landscape" : "portrait";

  return (
    <Document>
      <Page size="A4" orientation={pageOrientation} style={styles.page}>
        <View style={styles.header}>
          <Text style={styles.title}>Batch Grading Summary</Text>
          <Text style={styles.subTitle}>{new Date().toLocaleDateString()}</Text>
        </View>

        {/* Statistics Dashboard */}
        <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 20 }}>
          <View style={{ width: "30%", padding: 10, backgroundColor: "#f8fafc", borderRadius: 4 }}>
            <Text style={{ fontSize: 10, color: "#64748b" }}>Total Items</Text>
            <Text style={{ fontSize: 18, fontWeight: "bold" }}>{data.count}</Text>
          </View>
          <View style={{ width: "30%", padding: 10, backgroundColor: "#f8fafc", borderRadius: 4 }}>
             <Text style={{ fontSize: 10, color: "#64748b" }}>Average Score</Text>
             <Text style={{ fontSize: 18, fontWeight: "bold" }}>{data.summary?.avg ?? "-"}</Text>
          </View>
          <View style={{ width: "30%", padding: 10, backgroundColor: "#f8fafc", borderRadius: 4 }}>
             <Text style={{ fontSize: 10, color: "#64748b" }}>Pass Rate</Text>
             <Text style={{ fontSize: 18, fontWeight: "bold" }}>{data.summary?.pass_rate.toFixed(1)}%</Text>
          </View>
        </View>

        {/* Summary Table with Sub-scores */}
        <View style={styles.table}>
          {/* Header Row */}
          <View style={[styles.tableRow, styles.tableHeader]}>
            <Text style={{ width: "25%", padding: 5, fontSize: 10 }}>File Name</Text>
            <Text style={{ width: "10%", padding: 5, textAlign: "center", fontSize: 10 }}>Status</Text>
            <Text style={{ width: "10%", padding: 5, textAlign: "center", fontSize: 10 }}>Total</Text>
            
            {/* Dynamic Rubric Headers */}
            {rubricKeys.map((key, i) => (
              <Text key={i} style={{ width: rubricColWidth, padding: 5, textAlign: "center", fontSize: 9 }}>
                {/* 如果标题太长则截断 */}
                {key.length > 10 ? key.substring(0, 8) + ".." : key}
              </Text>
            ))}
          </View>

          {/* Data Rows */}
          {data.items.map((item, idx) => {
             // 为了高效填充表格，先将该学生的 rubric scores 转为 Map
             // key: criterion name, value: score
             const scoreMap: Record<string, number> = {};
             if (item.ok && item.result?.rubric_scores) {
               item.result.rubric_scores.forEach(r => {
                 scoreMap[r.criterion] = r.score;
               });
             }

             return (
              <View key={idx} style={styles.tableRow}>
                {/* File Name */}
                <Text style={{ width: "25%", padding: 5, fontSize: 9 }}>
                  {item.file.length > 30 ? "..." + item.file.slice(-25) : item.file}
                </Text>
                
                {/* Status */}
                <Text style={{ width: "10%", padding: 5, textAlign: "center", fontSize: 9, color: item.ok ? "green" : "red" }}>
                  {item.ok ? "OK" : "Err"}
                </Text>
                
                {/* Overall Score */}
                <Text style={{ width: "10%", padding: 5, textAlign: "center", fontSize: 9, fontWeight: 'bold' }}>
                  {item.result?.overall_score ?? "-"}
                </Text>

                {/* Dynamic Rubric Scores */}
                {rubricKeys.map((key, i) => (
                  <Text key={i} style={{ width: rubricColWidth, padding: 5, textAlign: "center", fontSize: 9, color: "#475569" }}>
                    {item.ok ? (scoreMap[key] !== undefined ? scoreMap[key] : "-") : "-"}
                  </Text>
                ))}
              </View>
             );
          })}
        </View>

        {/* [新增] Reference Answer at the end of summary (Optional) */}
        {showReference && data.reference_answer && (
          <View style={{ marginTop: 20 }} wrap={false}>
             <Text style={styles.sectionTitle}>Global Reference Answer Used</Text>
             <View style={{ padding: 10, backgroundColor: "#f8fafc", borderRadius: 4 }}>
               <Text style={{ fontSize: 9, fontFamily: "Helvetica", color: "#64748b" }}>
                 {data.reference_answer}
               </Text>
             </View>
          </View>
        )}

      </Page>
    </Document>
  );
};