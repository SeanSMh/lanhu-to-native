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


def _is_recycler_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[vertical]") or len(children) < 3:
        return False
    fps = [_fingerprint(child) for child in children]
    return len(set(fps)) <= max(1, len(children) // 3)


def _is_tabbar_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    children = node.get("children", [])
    if not widget.startswith("LinearLayout[horizontal]") or len(children) < 2:
        return False
    text_like = sum(
        1 for child in children
        if child.get("tag") in {"text", "button"}
        or _android_widget(child) in {"TextView", "MaterialButton"}
    )
    joined_classes = " ".join(" ".join(child.get("classes", [])) for child in children)
    return text_like == len(children) and ("tab" in joined_classes or len(children) <= 5)


def _is_pager_candidate(node: dict) -> bool:
    widget = _android_widget(node)
    if node.get("tag") == "swiper":
        return True
    joined = " ".join(node.get("classes", []))
    return widget == "ViewPager2" or any(key in joined for key in ("pager", "banner", "carousel"))


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
        if _is_pager_candidate(node):
            return DetectionResult("hscroll", "pager_degraded_to_hscroll")
        if _is_tabbar_candidate(node):
            return DetectionResult("tabbar", "horizontal_tab_group")
        if _is_recycler_candidate(node):
            return DetectionResult("vscroll", "recycler_degraded_to_vscroll")
        if _is_zstack_candidate(node):
            return DetectionResult("zstack", "multiple_absolute_children")
        if widget.startswith("ScrollView") and style.get("flex-direction") == "row":
            return DetectionResult("hscroll", "horizontal_scroll_view")
        if widget.startswith("ScrollView"):
            return DetectionResult("vscroll", "scroll_view")
        if widget.startswith("LinearLayout[horizontal]"):
            return DetectionResult("hstack", "linear_layout_horizontal")
        if widget.startswith("LinearLayout[vertical]"):
            return DetectionResult("vstack", "linear_layout_vertical")
        if widget == "ConstraintLayout":
            return DetectionResult("zstack", "constraintlayout_overlay")
        return DetectionResult("zstack", "generic_container")
    if widget.startswith("TextView") or tag == "text":
        return DetectionResult("label", "text_leaf")
    if widget.startswith("ImageView") or tag == "image":
        return DetectionResult("imageview", "image_leaf")
    if "Button" in widget or tag == "button":
        return DetectionResult("button", "button_leaf")
    if widget.startswith("EditText") or tag in {"input", "textarea"}:
        return DetectionResult("textfield", "input_leaf")
    return DetectionResult("view", "generic_leaf")
