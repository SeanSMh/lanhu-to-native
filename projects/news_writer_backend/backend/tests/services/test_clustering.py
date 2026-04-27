"""clustering utils 单元测试。"""

from __future__ import annotations

from app.utils.clustering import cosine, greedy_cluster, update_centroid


def test_cosine_identical():
    assert cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_cosine_orthogonal():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_empty():
    assert cosine([], [1.0]) == 0.0


def test_update_centroid_first():
    assert update_centroid([0, 0], [1, 1], 1) == [1, 1]


def test_update_centroid_running_mean():
    c = update_centroid([1, 1], [3, 3], 2)
    assert c == [2.0, 2.0]


def test_greedy_cluster_merges_similar():
    items = [
        ("a", [1.0, 0.0]),
        ("b", [0.99, 0.1]),
        ("c", [0.0, 1.0]),
    ]
    clusters = greedy_cluster(items, threshold=0.9)
    assert len(clusters) == 2
    # 前两者应在同一 cluster
    cluster_with_a = next(c for c in clusters if "a" in c["member_ids"])
    assert "b" in cluster_with_a["member_ids"]


def test_greedy_cluster_singletons_preserved():
    items = [
        ("a", [1.0, 0.0]),
        ("b", [0.0, 1.0]),
    ]
    clusters = greedy_cluster(items, threshold=0.9)
    assert len(clusters) == 2
    assert all(len(c["member_ids"]) == 1 for c in clusters)
