"""图像工具：Pillow 生成缩略图。"""

from __future__ import annotations

import io

from PIL import Image

MAX_THUMB_EDGE = 400


def make_thumbnail(data: bytes, *, max_edge: int = MAX_THUMB_EDGE) -> tuple[bytes, int, int]:
    """返回 (thumb_bytes, width, height)。保留原比例。"""
    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    fmt = "JPEG" if img.mode == "RGB" else "PNG"
    img.save(buf, format=fmt, quality=85)
    return buf.getvalue(), img.width, img.height


def get_size(data: bytes) -> tuple[int, int]:
    img = Image.open(io.BytesIO(data))
    return img.width, img.height
