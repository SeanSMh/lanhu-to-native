"""鉴权相关工具。"""

from __future__ import annotations

import hashlib


def hash_token(token: str) -> str:
    """返回 token 的 sha256 十六进制串（64 字符），用于存储比对。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
