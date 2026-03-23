from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DetectionResult:
    kind: str
    reason: str


def _android_widget(node: dict) -> str:
    return node.get("widgets", {}).get("android", "")


def _style(node: dict) -> dict:
    return node.get("style", {})


def _fingerprint(node: dict) -> tuple:
    style = _style(node)
    return (
        node.get("tag"),
        _android_widget(node),
        style.get("width"),
        style.get("height"),
        tuple(child.get("tag") for child in node.get("children", [])),
        len(node.get("children", [])),
    )


def _is_recycler_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[vertical]") or len(children) < 3:
        return False
    fps = [_fingerprint(child) for child in children]
    return len(set(fps)) <= max(1, len(children) // 3)


def _is_tab_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[horizontal]") or len(children) < 2:
        return False
    joined_classes = " ".join(" ".join(child.get("classes", [])) for child in children)
    text_like = sum(
        1
        for child in children
        if child.get("tag") in {"text", "button"}
        or _android_widget(child) in {"TextView", "MaterialButton"}
    )
    return text_like == len(children) and ("tab" in joined_classes or len(children) <= 5)


def _is_pager_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    if node.get("tag") == "swiper":
        return True
    joined = " ".join(node.get("classes", []))
    return widget == "ViewPager2" or any(key in joined for key in ("pager", "banner", "carousel"))


def _is_constraint_candidate(node: dict) -> bool:
    children = node.get("children", [])
    if len(children) < 2:
        return False
    abs_children = [child for child in children if child.get("positioned") == "absolute"]
    return len(abs_children) >= 2


def is_status_bar_mock(node: dict) -> bool:
    """Detect mobile OS status bar mock nodes (time + signal/wifi/battery icons).

    These are design-tool artefacts that should not appear in Android layouts.
    Detection heuristic: a horizontal container whose descendants contain a
    text node matching the HH:MM clock pattern.
    """
    if not _android_widget(node).startswith("LinearLayout[horizontal]"):
        return False

    def _has_time_text(n: dict) -> bool:
        if n.get("tag") == "text":
            if re.fullmatch(r"\d{1,2}:\d{2}", (n.get("text") or "").strip()):
                return True
        return any(_has_time_text(child) for child in n.get("children", []))

    return _has_time_text(node)


def detect_kind(node: dict) -> DetectionResult:
    widget = _android_widget(node)
    style = _style(node)
    tag = node.get("tag", "")
    if node.get("children"):
        if _is_pager_candidate(node):
            return DetectionResult("view_pager", "swiper_or_pager_widget")
        if _is_tab_candidate(node):
            return DetectionResult("tab_layout", "horizontal_tab_group")
        if _is_recycler_candidate(node):
            return DetectionResult("recycler_view", "repeated_vertical_children")
        if _is_constraint_candidate(node):
            return DetectionResult("constraint", "multiple_absolute_children")
        if widget.startswith("ScrollView") and style.get("flex-direction") == "row":
            return DetectionResult("horizontal_scroll", "horizontal_scroll_view")
        if widget.startswith("ScrollView"):
            return DetectionResult("vertical_scroll", "scroll_view")
        if widget.startswith("LinearLayout[horizontal]"):
            return DetectionResult("linear_horizontal", "linear_layout_horizontal")
        if widget.startswith("LinearLayout[vertical]"):
            return DetectionResult("linear_vertical", "linear_layout_vertical")
        if widget == "ConstraintLayout":
            return DetectionResult("constraint", "constraintlayout")
        return DetectionResult("frame", "generic_container")
    if widget.startswith("TextView") or tag == "text":
        return DetectionResult("text", "text_leaf")
    if widget.startswith("ImageView") or tag == "image":
        return DetectionResult("image", "image_leaf")
    if "Button" in widget or tag == "button":
        return DetectionResult("button", "button_leaf")
    if widget.startswith("EditText") or tag in {"input", "textarea"}:
        return DetectionResult("input", "input_leaf")
    return DetectionResult("view", "generic_leaf")
