# app/services/report_service.py
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from app.utils.logger import logger
from app.services.weighting_service import norm_name


def ensure_results_dir() -> Path:
    """
    Ensure the results directory exists and return its Path.
    Directory path is controlled by env var RESULTS_DIR (default: "results").
    """
    d = Path(os.getenv("RESULTS_DIR", "results"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_batch_reports(batch_id: str, payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Write a TXT and CSV snapshot of this batch grading.

    payload: the response object you're about to return from /grade-batch,
             containing keys like count, success_count, items, summary, etc.

    Returns:
        {"txt": "<txt_path>", "csv": "<csv_path>"}
    """
    outdir = ensure_results_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base = f"batch_{batch_id}_{ts}"
    txt_path = outdir / f"{base}.txt"
    csv_path = outdir / f"{base}.csv"

    items: List[Dict[str, Any]] = payload.get("items", []) or []
    rubric_used = payload.get("rubric_used") or []
    summary = payload.get("summary") or {}
    weights_used = payload.get("weights_used")

    # ---- Build canonical rubric item list from first successful result ----
    rubric_items: List[str] = []
    for it in items:
        if it.get("ok") and it.get("result"):
            rs_list = it["result"].get("rubric_scores") or []
            for rs in rs_list:
                # rs may be dict or Pydantic model
                if isinstance(rs, dict):
                    name = (rs.get("item") or "").strip()
                else:
                    name = (getattr(rs, "item", "") or "").strip()
                if name and name not in rubric_items:
                    rubric_items.append(name)
            if rubric_items:
                break

    # fallback: use rubric_used if no result-based items
    if not rubric_items and rubric_used:
        rubric_items = list(rubric_used)

    # ---------------- TXT report (human readable, very detailed) ----------------
    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"Batch ID: {batch_id}\n")
            f.write(
                f"Count: {payload.get('count')}  "
                f"Success: {payload.get('success_count')}  "
                f"Fail: {payload.get('fail_count')}\n"
            )
            f.write("Rubric: " + ", ".join(rubric_used) + "\n")
            if weights_used:
                f.write(
                    "Weights: "
                    + ", ".join(f"{k}:{v}" for k, v in weights_used.items())
                    + "\n"
                )
            if summary:
                f.write(
                    "Summary: "
                    + ", ".join(f"{k}={v}" for k, v in summary.items())
                    + "\n"
                )
            f.write("\n-- Items (detailed) --\n")

            for it in items:
                sid = it.get("id")
                fname = it.get("file")
                f.write(f"\n[{sid}] {fname}\n")
                if not it.get("ok"):
                    f.write(f"  ERROR: {it.get('error')}\n")
                    continue

                res = it.get("result") or {}
                overall = res.get("overall_score")
                weighted = res.get("weighted_overall")
                f.write(f"  overall={overall}, weighted={weighted}\n")

                # Rubric details
                rs_list = res.get("rubric_scores") or []
                if rs_list:
                    f.write("  Rubric details:\n")
                    for rs in rs_list:
                        if isinstance(rs, dict):
                            item = (rs.get("item") or "").strip()
                            score = rs.get("score")
                            comment = rs.get("comment") or ""
                        else:
                            item = (getattr(rs, "item", "") or "").strip()
                            score = getattr(rs, "score", None)
                            comment = getattr(rs, "comment", "") or ""

                        f.write(f"    - {item}: {score}\n")
                        if comment:
                            # indent multi-line comment
                            indented = "      " + str(comment).replace("\n", "\n      ")
                            f.write(indented + "\n")

                # Overall feedback
                fb = res.get("feedback") or ""
                if fb:
                    f.write("  Feedback:\n")
                    indented_fb = "    " + str(fb).replace("\n", "\n    ")
                    f.write(indented_fb + "\n")

    except Exception as e:
        logger.warning(f"Failed to write TXT report: {e}")

    # ---------------- CSV report (machine friendly, wide & detailed) ----------------
    try:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)

            # Build header
            header = ["id", "file", "ok", "overall_score", "weighted_overall"]
            # For each rubric item, add score_xxx, comment_xxx
            for name in rubric_items:
                n = norm_name(name) or "item"
                header.append(f"score_{n}")
                header.append(f"comment_{n}")
            # Add feedback column at the end
            header.append("feedback")

            writer.writerow(header)

            # Write rows
            for it in items:
                sid = it.get("id")
                fname = it.get("file")
                ok = bool(it.get("ok"))

                if not ok or not it.get("result"):
                    row = [sid, fname, False, "", ""]
                    # Empty rubric and feedback columns
                    row.extend([""] * (len(header) - len(row)))
                    writer.writerow(row)
                    continue

                res = it["result"]
                overall = res.get("overall_score")
                weighted = res.get("weighted_overall")

                row = [sid, fname, True, overall, weighted]

                # Build a lookup: rubric item name -> (score, comment)
                rs_map: Dict[str, tuple[Any, Any]] = {}
                for rs in res.get("rubric_scores") or []:
                    if isinstance(rs, dict):
                        item = (rs.get("item") or "").strip()
                        score = rs.get("score")
                        comment = rs.get("comment") or ""
                    else:
                        item = (getattr(rs, "item", "") or "").strip()
                        score = getattr(rs, "score", None)
                        comment = getattr(rs, "comment", "") or ""
                    if item:
                        rs_map[item] = (score, comment)

                # Fill rubric columns in the same order as header/rubric_items
                for name in rubric_items:
                    score, comment = rs_map.get(name, ("", ""))
                    row.append(score)
                    row.append(comment)

                # Append feedback
                fb = res.get("feedback") or ""
                row.append(fb)

                writer.writerow(row)

    except Exception as e:
        logger.warning(f"Failed to write CSV report: {e}")

    return {"txt": str(txt_path), "csv": str(csv_path)}
