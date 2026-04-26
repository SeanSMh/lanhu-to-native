"""DB 辅助类型 & 工具。"""

from __future__ import annotations

from ulid import ULID


def new_ulid() -> str:
    """生成一个 ULID 字符串（26 字符）。"""
    return str(ULID())
