# app/services/weighting_service.py
from __future__ import annotations

import json
import re
from typing import List, Tuple, Dict


def norm_name(s: str) -> str:
    """
    Normalize rubric item / name:
    - strip spaces
    - lowercase
    - remove all non-alphanumeric characters (including spaces, brackets, underscores, etc.)
    """
    return re.sub(r"[\W_]+", "", (s or "").strip().lower())


def parse_weights(
    rubric_items: List[str],
    raw_weights: str | None,
) -> Tuple[List[float], str]:
    """
    Parse user-provided weights into a list aligned with rubric_items.

    Supports three forms of input:
      1) Positional list:
         - Comma-separated numbers:  "2,1,3"
         - JSON array:               "[2,1,3]"
         (length must equal len(rubric_items))

      2) Named mapping:
         - "Completeness:2,Final Answer:3"
         (missing items default to 0; if all 0, fallback to equal weights)

      3) Empty / invalid:
         - Fallback to equal weights (all 1.0)

    Returns:
        (weights, mode)
        mode ∈ {"positional", "named", "default"}
    """
    n = len(rubric_items)
    if not raw_weights or not raw_weights.strip():
        return [1.0] * n, "default"

    s = raw_weights.strip()

    # 1) JSON array
    try:
        arr = json.loads(s)
        if isinstance(arr, list) and all(isinstance(x, (int, float)) for x in arr):
            if len(arr) == n and sum(arr) > 0:
                return [float(x) for x in arr], "positional"
    except Exception:
        pass

    # 2) Comma-separated numbers
    try:
        nums = [float(x.strip()) for x in s.split(",")]
        if len(nums) == n and sum(nums) > 0 and all(x >= 0 for x in nums):
            return nums, "positional"
    except Exception:
        pass

    # 3) Named pairs: "Name:2,Other:1"
    name_map: Dict[str, float] = {}
    any_pair = False
    for part in s.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip()
            try:
                w = float(v.strip())
                if k and w >= 0:
                    name_map[norm_name(k)] = w
                    any_pair = True
            except Exception:
                continue

    if any_pair:
        weights = [float(name_map.get(norm_name(item), 0.0)) for item in rubric_items]
        if sum(weights) > 0:
            return weights, "named"

    # Fallback: equal weights
    return [1.0] * n, "default"


def apply_weighted_overall(
    rubric_scores_0_to_1: List[float],
    weights: List[float],
) -> float:
    """
    Compute weighted overall score in 0..100.

    rubric_scores_0_to_1:
        each dimension score in [0,1]

    weights:
        non-negative; if all zero, fallback to equal weights

    Returns:
        0..100 float, rounded to 1 decimal place.
    """
    total_w = float(sum(weights))
    if total_w <= 0:
        # fallback to equal weights
        weights = [1.0] * len(rubric_scores_0_to_1)
        total_w = float(len(rubric_scores_0_to_1))

    weighted = sum(s * w for s, w in zip(rubric_scores_0_to_1, weights)) / total_w
    return round(weighted * 100.0, 1)
