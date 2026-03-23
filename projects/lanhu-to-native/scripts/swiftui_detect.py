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


def _is_lazy_vstack_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[vertical]") or len(children) < 3:
        return False
    fps = [_fingerprint(child) for child in children]
    return len(set(fps)) <= max(1, len(children) // 3)


def _is_tabview_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    if node.get("tag") == "swiper":
        return True
    if widget == "ViewPager2":
        return True
    joined = " ".join(node.get("classes", []))
    return any(key in joined for key in ("pager", "banner", "carousel"))


def _is_zstack_candidate(node: dict) -> bool:
    children = node.get("children", [])
    if len(children) < 2:
        return False
    return sum(1 for child in children if child.get("positioned") == "absolute") >= 2


def detect_kind(node: dict) -> DetectionResult:
    widget = _android_widget(node)
    style = _style(node)
    tag = node.get("tag", "")
    if node.get("children"):
        if _is_tabview_candidate(node):
            return DetectionResult("tab_view", "swiper_or_pager_widget")
        if _is_lazy_vstack_candidate(node):
            return DetectionResult("lazy_vstack", "repeated_vertical_children")
        if _is_zstack_candidate(node):
            return DetectionResult("zstack", "multiple_absolute_children")
        if widget.startswith("ScrollView") and style.get("flex-direction") == "row":
            return DetectionResult("horizontal_scroll", "horizontal_scroll_view")
        if widget.startswith("ScrollView"):
            return DetectionResult("vertical_scroll", "scroll_view")
        if widget.startswith("LinearLayout[horizontal]"):
            return DetectionResult("hstack", "linear_layout_horizontal")
        if widget.startswith("LinearLayout[vertical]"):
            return DetectionResult("vstack", "linear_layout_vertical")
        if widget == "ConstraintLayout":
            return DetectionResult("zstack", "constraintlayout_overlay")
        return DetectionResult("zstack", "generic_container")
    if widget.startswith("TextView") or tag == "text":
        return DetectionResult("text", "text_leaf")
    if widget.startswith("ImageView") or tag == "image":
        return DetectionResult("image", "image_leaf")
    if "Button" in widget or tag == "button":
        return DetectionResult("button", "button_leaf")
    if widget.startswith("EditText") or tag in {"input", "textarea"}:
        return DetectionResult("input", "input_leaf")
    return DetectionResult("spacer", "generic_leaf")
