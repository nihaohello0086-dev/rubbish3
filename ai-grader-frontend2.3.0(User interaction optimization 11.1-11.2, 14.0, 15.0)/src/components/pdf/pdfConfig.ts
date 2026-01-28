import { StyleSheet } from "@react-pdf/renderer";


export const styles = StyleSheet.create({
  page: {
    padding: 40,
    fontFamily: "Helvetica", 
    fontSize: 12,
    color: "#334155",
  },
  header: {
    marginBottom: 20,
    borderBottomWidth: 2,
    borderBottomColor: "#4f46e5",
    paddingBottom: 10,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-end",
  },
  title: {
    fontSize: 24,
    fontWeight: "bold", // Helvetica 支持 bold
    color: "#1e293b",
  },
  subTitle: {
    fontSize: 10,
    color: "#64748b",
  },
  scoreBox: {
    padding: 15,
    backgroundColor: "#eef2ff",
    borderRadius: 8,
    marginBottom: 20,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  scoreValue: {
    fontSize: 28,
    fontWeight: "bold",
    color: "#4f46e5",
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: "bold",
    marginTop: 15,
    marginBottom: 8,
    color: "#0f172a",
    backgroundColor: "#f1f5f9",
    padding: 5,
  },
  text: {
    lineHeight: 1.6,
    marginBottom: 8,
    fontSize: 11,
  },
  table: {
    width: "auto",
    borderStyle: "solid",
    borderWidth: 1,
    borderColor: "#e2e8f0",
    marginTop: 10,
  },
  tableRow: {
    margin: "auto",
    flexDirection: "row",
    borderBottomWidth: 1,
    borderBottomColor: "#e2e8f0",
    minHeight: 30,
    alignItems: "center",
  },
  tableHeader: {
    backgroundColor: "#f8fafc",
    fontWeight: "bold",
  },
  col1: { width: "25%", padding: 5 },
  col2: { width: "10%", padding: 5, textAlign: 'center' },
  col3: { width: "65%", padding: 5 },
});