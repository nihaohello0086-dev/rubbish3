# app/services/stats_service.py
from __future__ import annotations

from typing import List, Dict


def compute_batch_summary(items: List[Dict], pass_threshold: float = 60.0) -> Dict[str, float]:
    """
    Compute avg/min/max/stdev/pass_rate on final overall scores (after weighting if present).

    items: list of dicts from batch grading, each item like:
        {
          "id": "0001",
          "file": "...",
          "ok": True/False,
          "result": {
              "overall_score": float,
              "weighted_overall": float | None,
              ...
          }
        }
    """
    scores: List[float] = []
    for it in items:
        if it.get("ok"):
            s = it["result"].get("weighted_overall")
            if s is None:
                s = it["result"].get("overall_score")
            if isinstance(s, (int, float)):
                scores.append(float(s))

    if not scores:
        return {
            "avg": 0.0,
            "min": 0.0,
            "max": 0.0,
            "stdev": 0.0,
            "pass_rate": 0.0,
        }

    n = len(scores)
    avg = sum(scores) / n
    _min, _max = min(scores), max(scores)
    var = sum((x - avg) ** 2 for x in scores) / n
    stdev = var ** 0.5
    pass_rate = sum(1 for x in scores if x >= pass_threshold) / n

    return {
        "avg": round(avg, 2),
        "min": round(_min, 2),
        "max": round(_max, 2),
        "stdev": round(stdev, 2),
        "pass_rate": round(pass_rate, 3),
    }
