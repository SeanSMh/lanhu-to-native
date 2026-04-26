"""贪心聚类：给定 embeddings 和阈值，按顺序合并相似项。"""

from __future__ import annotations

import math
from typing import Iterable


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def update_centroid(centroid: list[float], new_vec: list[float], new_count: int) -> list[float]:
    if new_count <= 1:
        return list(new_vec)
    old_n = new_count - 1
    return [(c * old_n + v) / new_count for c, v in zip(centroid, new_vec)]


def greedy_cluster(
    items: Iterable[tuple[str, list[float]]], *, threshold: float = 0.82
) -> list[dict]:
    """对 (id, vec) 列表做贪心聚类。

    返回 list[{"centroid": [...], "member_ids": [...]}]。
    """
    clusters: list[dict] = []
    for item_id, vec in items:
        best_idx = -1
        best_sim = -1.0
        for i, c in enumerate(clusters):
            sim = cosine(vec, c["centroid"])
            if sim > best_sim:
                best_idx, best_sim = i, sim
        if best_idx >= 0 and best_sim >= threshold:
            c = clusters[best_idx]
            c["member_ids"].append(item_id)
            c["centroid"] = update_centroid(c["centroid"], vec, len(c["member_ids"]))
        else:
            clusters.append({"centroid": list(vec), "member_ids": [item_id]})
    return clusters
