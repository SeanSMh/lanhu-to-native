"""FakeEmbeddingProvider：根据字符串长度 / hash 产出稳定伪向量，供测试使用。"""

from __future__ import annotations

import hashlib


class FakeEmbeddingProvider:
    model = "fake-embedding"
    dim = 32

    async def embed(self, texts: list[str], *, timeout_s: float = 25.0) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            # 用 bytes 前 dim 个字节映射到 [-1, 1]
            vec = [(b - 128) / 128.0 for b in h[: self.dim]]
            out.append(vec)
        return out
