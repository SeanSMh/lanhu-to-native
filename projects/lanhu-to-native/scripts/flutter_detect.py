from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DetectionResult:
    kind: str
    reason: str


def _flutter_widget(node: dict) -> str:
    return node.get("widgets", {}).get("flutter", "")


def _android_widget(node: dict) -> str:
    return node.get("widgets", {}).get("android", "")


def _style(node: dict) -> dict:
    return node.get("style", {})


def _fingerprint(node: dict) -> tuple:
    style = _style(node)
    return (
        node.get("tag"),
        _flutter_widget(node),
        _android_widget(node),
        style.get("width"),
        style.get("height"),
        tuple(child.get("tag") for child in node.get("children", [])),
        len(node.get("children", [])),
    )


def _is_list_candidate(node: dict) -> bool:
    widget = _flutter_widget(node) or _android_widget(node)
    children = node.get("children", [])
    if not (widget.startswith("Column") or "LinearLayout[vertical]" in widget) or len(children) < 3:
        return False
    fingerprints = [_fingerprint(child) for child in children]
    return len(set(fingerprints)) <= max(1, len(children) // 3)


def _is_page_view_candidate(node: dict) -> bool:
    widget = _flutter_widget(node) or _android_widget(node)
    joined = " ".join(node.get("classes", []))
    return (
        node.get("tag") == "swiper"
        or widget == "PageView"
        or widget == "ViewPager2"
        or any(key in joined for key in ("pager", "banner", "carousel"))
    )


def _is_tab_bar_candidate(node: dict) -> bool:
    widget = _flutter_widget(node) or _android_widget(node)
    children = node.get("children", [])
    if len(children) < 2:
        return False
    if not (widget.startswith("Row") or "LinearLayout[horizontal]" in widget):
        return False
    if not all(child.get("tag") in {"text", "button"} for child in children):
        return False
    classes = " ".join(" ".join(child.get("classes", [])) for child in children)
    return "tab" in classes or all(child.get("tag") == "text" for child in children)


def _is_stack_candidate(node: dict) -> bool:
    children = node.get("children", [])
    if len(children) < 2:
        return False
    widget = _flutter_widget(node) or _android_widget(node)
    return (
        widget in {"Stack", "ConstraintLayout"}
        or sum(1 for child in children if child.get("positioned") == "absolute") >= 2
    )


def detect_kind(node: dict) -> DetectionResult:
    widget = _flutter_widget(node) or _android_widget(node)
    style = _style(node)
    tag = node.get("tag", "")
    if node.get("children"):
        if _is_tab_bar_candidate(node):
            return DetectionResult("tab_bar", "horizontal_tab_items")
        if _is_page_view_candidate(node):
            return DetectionResult("page_view", "swiper_or_pager_widget")
        if _is_list_candidate(node):
            return DetectionResult("list_view", "repeated_vertical_children")
        if _is_stack_candidate(node):
            return DetectionResult("stack", "multiple_absolute_children")
        if tag == "scroll-view" and style.get("flex-direction") == "row":
            return DetectionResult("horizontal_scroll", "horizontal_scroll_view")
        if tag == "scroll-view" or widget in {"SingleChildScrollView", "ScrollView"}:
            return DetectionResult("vertical_scroll", "scroll_view")
        if widget.startswith("Row") or "LinearLayout[horizontal]" in widget:
            return DetectionResult("row", "row_container")
        if widget.startswith("Column") or "LinearLayout[vertical]" in widget:
            return DetectionResult("column", "column_container")
        if widget in {"Stack", "ConstraintLayout"}:
            return DetectionResult("stack", "stack_container")
        return DetectionResult("stack", "generic_container")
    if widget.startswith("TextField") or tag in {"input", "textarea"}:
        return DetectionResult("input", "input_leaf")
    if widget == "Text" or widget.startswith("RichText") or tag == "text":
        return DetectionResult("text", "text_leaf")
    if widget.startswith("Image") or tag == "image":
        return DetectionResult("image", "image_leaf")
    if "Button" in widget or tag == "button":
        return DetectionResult("button", "button_leaf")
    return DetectionResult("spacer", "generic_leaf")
