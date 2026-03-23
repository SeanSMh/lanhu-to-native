from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DetectionResult:
    kind: str
    reason: str


def _android_widget(node: dict) -> str:
    return node.get("widgets", {}).get("android", "")


def _style(node: dict) -> dict:
    return node.get("style", {})


def _text(node: dict) -> str:
    return (node.get("text") or "").strip()


def _fingerprint(node: dict) -> tuple:
    style = _style(node)
    width = style.get("width")
    height = style.get("height")
    child_tags = tuple(child.get("tag") for child in node.get("children", []))
    return (
        node.get("tag"),
        _android_widget(node),
        width,
        height,
        child_tags,
        len(node.get("children", [])),
    )


def _is_tab_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[horizontal]") or len(children) < 2:
        return False
    text_like = 0
    class_hits = 0
    for child in children:
        if child.get("tag") in {"text", "button"} or _android_widget(child) in {
            "TextView",
            "MaterialButton",
        }:
            text_like += 1
        joined = " ".join(child.get("classes", []))
        if "tab" in joined or "segment" in joined:
            class_hits += 1
    return text_like == len(children) and (class_hits > 0 or len(children) <= 5)


def _is_pager_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    if node.get("tag") == "swiper":
        return True
    if widget in {"ViewPager2"}:
        return True
    joined = " ".join(node.get("classes", []))
    return "pager" in joined or "banner" in joined or "carousel" in joined


def _is_lazy_column_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[vertical]") or len(children) < 3:
        return False
    fingerprints = [_fingerprint(child) for child in children]
    return len(set(fingerprints)) <= max(1, len(children) // 3)


def _is_constraint_candidate(node: dict) -> bool:
    children = node.get("children", [])
    if len(children) < 3:
        return False
    absolute_children = [child for child in children if child.get("positioned") == "absolute"]
    if len(absolute_children) < 3:
        return False
    style = _style(node)
    return isinstance(style.get("width"), (int, float, str)) or isinstance(
        style.get("height"), (int, float, str)
    )


def detect_container_kind(node: dict) -> DetectionResult:
    widget = _android_widget(node)
    style = _style(node)
    if _is_pager_candidate(node):
        return DetectionResult("pager", "swiper_or_pager_widget")
    if _is_tab_candidate(node):
        return DetectionResult("tab_row", "horizontal_text_group")
    if _is_lazy_column_candidate(node):
        return DetectionResult("lazy_column", "repeated_vertical_children")
    if _is_constraint_candidate(node):
        return DetectionResult("constraint", "multiple_absolute_children")
    if widget.startswith("ScrollView") and style.get("flex-direction") == "row":
        return DetectionResult("scroll_row", "horizontal_scroll_view")
    if widget.startswith("LinearLayout[vertical]"):
        return DetectionResult("column", "linear_layout_vertical")
    if widget.startswith("LinearLayout[horizontal]"):
        return DetectionResult("row", "linear_layout_horizontal")
    if widget.startswith("ScrollView"):
        return DetectionResult("scroll", "scroll_view")
    if widget == "ConstraintLayout":
        return DetectionResult("box", "constraintlayout_fallback_to_box")
    if node.get("tag") == "view":
        return DetectionResult("box", "generic_view")
    return DetectionResult("box", "default_container")


def detect_leaf_kind(node: dict) -> str:
    widget = _android_widget(node)
    tag = node.get("tag", "")
    if widget.startswith("TextView") or tag == "text":
        return "text"
    if widget.startswith("ImageView") or tag == "image":
        return "image"
    if "Button" in widget or tag == "button":
        return "button"
    if widget.startswith("EditText") or tag in {"input", "textarea"}:
        return "input"
    return "box"


def detect_kind(node: dict) -> DetectionResult:
    if node.get("children"):
        return detect_container_kind(node)
    return DetectionResult(detect_leaf_kind(node), "leaf")
