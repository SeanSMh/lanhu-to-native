#!/usr/bin/env python3
"""
Lanhu Compose renderer MVP.

Reads a spec.json produced by lanhu_parser.py and emits:
  - XxxScreen.kt
  - colors.xml
  - strings.xml
  - icon_placeholders.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FALLBACK_SKILL_SCRIPT_DIR = Path.home() / ".codex/skills/lanhu-to-native/scripts"
sys.path.insert(0, str(SCRIPT_DIR))
if FALLBACK_SKILL_SCRIPT_DIR != SCRIPT_DIR:
    sys.path.append(str(FALLBACK_SKILL_SCRIPT_DIR))

from lanhu_parser import generate_spec
from compose_detect import detect_kind
from compose_integrate import (
    detect_compose_project,
    find_android_project_root,
    replace_marked_block,
    write_generated_files,
)


LOW_PRECISION_MODES = {"screenshot", "fallback"}


def snake_case(value: str) -> str:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", normalized).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.lower() or "screen"


def pascal_case(value: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", value)
    cleaned = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return cleaned or "LanhuScreen"


def format_number(value: int | float | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if value == int(value):
        return str(int(value))
    return str(round(value, 1)).rstrip("0").rstrip(".")


def dp(value: int | float | str | None) -> str | None:
    raw = format_number(value)
    return f"{raw}.dp" if raw is not None else None


def sp(value: int | float | str | None) -> str | None:
    raw = format_number(value)
    return f"{raw}.sp" if raw is not None else None


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "\\'")
    )


def argb_from_hex(hex_value: str) -> str:
    raw = hex_value.lstrip("#").upper()
    if len(raw) == 6:
        return f"FF{raw}"
    if len(raw) == 8:
        return f"{raw[6:8]}{raw[:6]}"
    return "FF000000"


def kotlin_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def color_literal(hex_value: str) -> str:
    return f"Color(0x{argb_from_hex(hex_value)})"


def parse_gradient(value: str) -> str | None:
    if not isinstance(value, str) or "linear-gradient" not in value:
        return None
    colors = re.findall(r"#[0-9A-Fa-f]{6,8}", value)
    if len(colors) < 2:
        return None
    color_exprs = ", ".join(color_literal(color) for color in colors[:3])
    return f"Brush.linearGradient(listOf({color_exprs}))"


def parse_shadow(style: dict) -> str | None:
    raw = style.get("box-shadow")
    if not isinstance(raw, str):
        return None
    numbers = re.findall(r"-?\d+(?:\.\d+)?", raw)
    if len(numbers) < 3:
        return None
    blur = numbers[2]
    return f"shadow({dp(float(blur))}, RoundedCornerShape({dp(style.get('border-radius') or 0)}))"


def font_weight_expr(value: object) -> str | None:
    mapping = {
        "normal": "FontWeight.Normal",
        "medium": "FontWeight.Medium",
        "semibold": "FontWeight.SemiBold",
        "bold": "FontWeight.Bold",
    }
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in mapping:
            return mapping[lowered]
        if lowered.isdigit():
            value = int(lowered)
    if isinstance(value, (int, float)):
        number = int(value)
        if number >= 700:
            return "FontWeight.Bold"
        if number >= 600:
            return "FontWeight.SemiBold"
        if number >= 500:
            return "FontWeight.Medium"
        return "FontWeight.Normal"
    return None


def text_align_expr(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    mapping = {
        "left": "TextAlign.Left",
        "center": "TextAlign.Center",
        "right": "TextAlign.Right",
        "justify": "TextAlign.Justify",
    }
    return mapping.get(value.lower())


@dataclass
class RenderContext:
    screen_name: str
    package_name: str
    mode: str
    low_precision: bool
    colors: dict[str, dict]
    string_ids: dict[str, str] = field(default_factory=dict)
    strings: list[tuple[str, str]] = field(default_factory=list)
    icons: list[tuple[str, str]] = field(default_factory=list)
    image_placeholders: dict[str, str] = field(default_factory=dict)
    image_counter: int = 0
    needs_tab_state: bool = False
    needs_pager_state: bool = False
    needs_constraint_layout: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def screen_snake(self) -> str:
        return snake_case(self.screen_name)

    def note(self, text: str) -> str:
        return f" // {text}" if self.low_precision else ""

    def string_ref(self, text: str) -> str:
        if text not in self.string_ids:
            key = f"{self.screen_snake}_text_{len(self.strings) + 1}"
            self.string_ids[text] = key
            self.strings.append((key, text))
        return self.string_ids[text]

    def image_placeholder(self, node_path: str, node: dict) -> str:
        if node_path not in self.image_placeholders:
            self.image_counter += 1
            semantic = "image"
            classes = "_".join(node.get("classes", []))
            if "back" in classes:
                semantic = "back"
            elif "avatar" in classes:
                semantic = "avatar"
            elif "icon" in classes:
                semantic = "icon"
            elif "logo" in classes:
                semantic = "logo"
            elif "close" in classes:
                semantic = "close"
            placeholder = f"ic_{self.screen_snake}_{semantic}_{self.image_counter}"
            self.image_placeholders[node_path] = placeholder
            desc = " / ".join(
                part for part in [node.get("tag", "image"), classes or None] if part
            )
            self.icons.append((placeholder, desc))
        return self.image_placeholders[node_path]


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec.get("tree"), list) or not spec["tree"]:
        raise ValueError("spec.json 缺少有效 tree")
    if not isinstance(spec.get("colors"), dict):
        raise ValueError("spec.json 缺少有效 colors")
    return spec


def indent(level: int) -> str:
    return " " * (level * 4)


def compose_color_expr(ctx: RenderContext, style: dict, key: str) -> str | None:
    value = style.get(key)
    if not isinstance(value, str):
        return None
    if value in ctx.colors:
        color_name = ctx.colors[value]["name"]
        return f"colorResource(id = R.color.{color_name})"
    if re.fullmatch(r"#[0-9A-Fa-f]{6,8}", value):
        return color_literal(value)
    return None


def render_modifier(ctx: RenderContext, node: dict) -> str:
    style = node.get("style", {})
    modifiers: list[str] = []

    width = style.get("width")
    height = style.get("height")
    if width == "match_parent":
        modifiers.append("fillMaxWidth()")
    elif isinstance(width, (int, float)):
        modifiers.append(f"width({dp(width)})")
    if height == "match_parent":
        modifiers.append("fillMaxHeight()")
    elif isinstance(height, (int, float)):
        modifiers.append(f"height({dp(height)})")

    padding = style.get("padding")
    if isinstance(padding, dict):
        entries = []
        for compose_key, style_key in (
            ("start", "left"),
            ("top", "top"),
            ("end", "right"),
            ("bottom", "bottom"),
        ):
            if isinstance(padding.get(style_key), (int, float)):
                entries.append(f"{compose_key} = {dp(padding[style_key])}")
        if entries:
            modifiers.append(f"padding({', '.join(entries)})")

    shadow = parse_shadow(style)
    if shadow:
        modifiers.append(shadow)

    bg_gradient = parse_gradient(style.get("background"))
    bg = compose_color_expr(ctx, style, "background-color") or compose_color_expr(ctx, style, "background")
    if bg_gradient:
        modifiers.append(f"background(brush = {bg_gradient})")
    elif bg:
        modifiers.append(f"background({bg})")

    radius = style.get("border-radius")
    if isinstance(radius, (int, float)):
        modifiers.append(f"clip(RoundedCornerShape({dp(radius)}))")

    border_color = compose_color_expr(ctx, style, "border-color")
    border_width = style.get("border-width")
    if border_color and isinstance(border_width, (int, float)):
        modifiers.append(
            f"border(BorderStroke({dp(border_width)}, {border_color}), RoundedCornerShape({dp(radius or 0)}))"
        )

    if node.get("positioned") == "absolute":
        left = style.get("left")
        top = style.get("top")
        if isinstance(left, (int, float)) or isinstance(top, (int, float)):
            modifiers.append(
                f"offset(x = {dp(left or 0)}, y = {dp(top or 0)})"
            )

    opacity = style.get("opacity")
    if isinstance(opacity, (int, float)):
        modifiers.append(f"alpha({format_number(opacity)}f)")

    if not modifiers:
        return "Modifier"

    head, *tail = modifiers
    lines = ["Modifier", f"    .{head}{ctx.note('估算值') if ctx.low_precision and head.startswith(('width(', 'height(', 'offset(', 'padding(')) else ''}"]
    for item in tail:
        note = ctx.note("估算值") if ctx.low_precision and item.startswith(("width(", "height(", "offset(", "padding(")) else ""
        lines.append(f"    .{item}{note}")
    return "\n".join(lines)


def render_text(ctx: RenderContext, node: dict, level: int) -> list[str]:
    style = node.get("style", {})
    key = ctx.string_ref(node.get("text", ""))
    text_color = compose_color_expr(ctx, style, "color")
    font_size = sp(style.get("font-size")) if isinstance(style.get("font-size"), (int, float)) else None
    line_height = sp(style.get("line-height")) if isinstance(style.get("line-height"), (int, float)) else None
    font_weight = font_weight_expr(style.get("font-weight"))
    text_align = text_align_expr(style.get("text-align"))
    params = [f"text = stringResource(id = R.string.{key})"]
    params.append("modifier = " + render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}"))
    if text_color or font_size or line_height or font_weight or text_align:
        style_items = []
        if text_color:
            style_items.append(f"color = {text_color}")
        if font_size:
            style_items.append(f"fontSize = {font_size}")
        if line_height:
            style_items.append(f"lineHeight = {line_height}")
        if font_weight:
            style_items.append(f"fontWeight = {font_weight}")
        if text_align:
            style_items.append(f"textAlign = {text_align}")
        params.append(f"style = TextStyle({', '.join(style_items)})")
    lines = [f"{indent(level)}Text("]
    for idx, param in enumerate(params):
        suffix = "," if idx < len(params) - 1 else ""
        lines.append(f"{indent(level + 1)}{param}{suffix}")
    lines.append(f"{indent(level)})")
    return lines


def render_button(ctx: RenderContext, node: dict, level: int) -> list[str]:
    key = ctx.string_ref(node.get("text", "按钮"))
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    return [
        f"{indent(level)}Button(",
        f"{indent(level + 1)}onClick = {{ }},",
        f"{indent(level + 1)}modifier = {modifier}",
        f"{indent(level)}) {{",
        f"{indent(level + 1)}Text(text = stringResource(id = R.string.{key}))",
        f"{indent(level)}}}",
    ]


def render_input(ctx: RenderContext, node: dict, level: int) -> list[str]:
    text = node.get("text", "")
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    lines = [f"{indent(level)}OutlinedTextField("]
    lines.append(f"{indent(level + 1)}value = {kotlin_string(text)},")
    lines.append(f"{indent(level + 1)}onValueChange = {{ }},")
    lines.append(f"{indent(level + 1)}modifier = {modifier}")
    lines.append(f"{indent(level)})")
    return lines


def render_image(ctx: RenderContext, node: dict, level: int, node_path: str) -> list[str]:
    placeholder = ctx.image_placeholder(node_path, node)
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    return [
        f"{indent(level)}Image(",
        f"{indent(level + 1)}painter = painterResource(id = R.drawable.{placeholder}),",
        f"{indent(level + 1)}contentDescription = null,",
        f"{indent(level + 1)}modifier = {modifier} // TODO: replace icon asset",
        f"{indent(level)})",
    ]


def render_children(ctx: RenderContext, children: list[dict], level: int, path: str) -> list[str]:
    lines: list[str] = []
    for index, child in enumerate(children):
        child_path = f"{path}_{index}"
        lines.extend(render_node(ctx, child, level, child_path))
    return lines


def render_container(ctx: RenderContext, node: dict, level: int, node_path: str, container: str) -> list[str]:
    name = {
        "column": "Column",
        "row": "Row",
        "box": "Box",
        "scroll": "Column",
        "scroll_row": "Row",
    }[container]
    modifier = render_modifier(ctx, node)
    if container == "scroll":
        modifier = f"{modifier}\n    .verticalScroll(rememberScrollState())"
    if container == "scroll_row":
        modifier = f"{modifier}\n    .horizontalScroll(rememberScrollState())"
    modifier = modifier.replace("\n", f"\n{indent(level + 2)}")
    lines = [f"{indent(level)}{name}("]
    lines.append(f"{indent(level + 1)}modifier = {modifier}")
    lines.append(f"{indent(level)}) {{")
    lines.extend(render_children(ctx, node.get("children", []), level + 1, node_path))
    lines.append(f"{indent(level)}}}")
    return lines


def render_lazy_column(ctx: RenderContext, node: dict, level: int, node_path: str) -> list[str]:
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    lines = [f"{indent(level)}LazyColumn("]
    lines.append(f"{indent(level + 1)}modifier = {modifier}")
    lines.append(f"{indent(level)}) {{")
    for index, child in enumerate(node.get("children", [])):
        lines.append(f"{indent(level + 1)}item {{")
        lines.extend(render_node(ctx, child, level + 2, f"{node_path}_{index}"))
        lines.append(f"{indent(level + 1)}}}")
    lines.append(f"{indent(level)}}}")
    return lines


def render_tab_row(ctx: RenderContext, node: dict, level: int) -> list[str]:
    ctx.needs_tab_state = True
    children = node.get("children", [])
    labels = []
    for index, child in enumerate(children):
        label = (child.get("text") or "").strip() or f"Tab {index + 1}"
        labels.append((ctx.string_ref(label), index))
    lines = [f"{indent(level)}TabRow(selectedTabIndex = selectedTabIndex) {{"] 
    for key, index in labels:
        lines.append(f"{indent(level + 1)}Tab(")
        lines.append(f"{indent(level + 2)}selected = selectedTabIndex == {index},")
        lines.append(f"{indent(level + 2)}onClick = {{ selectedTabIndex = {index} }},")
        lines.append(f"{indent(level + 2)}text = {{ Text(stringResource(id = R.string.{key})) }}")
        lines.append(f"{indent(level + 1)})")
    lines.append(f"{indent(level)}}}")
    return lines


def render_pager(ctx: RenderContext, node: dict, level: int, node_path: str) -> list[str]:
    ctx.needs_pager_state = True
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    lines = [f"{indent(level)}HorizontalPager("]
    lines.append(f"{indent(level + 1)}state = pagerState,")
    lines.append(f"{indent(level + 1)}modifier = {modifier}")
    lines.append(f"{indent(level)}) {{ page ->")
    lines.append(f"{indent(level + 1)}when (page) {{")
    for index, child in enumerate(node.get("children", [])):
        lines.append(f"{indent(level + 2)}{index} -> {{")
        lines.extend(render_node(ctx, child, level + 3, f"{node_path}_{index}"))
        lines.append(f"{indent(level + 2)}}}")
    lines.append(f"{indent(level + 2)}else -> Unit")
    lines.append(f"{indent(level + 1)}}}")
    lines.append(f"{indent(level)}}}")
    return lines


def render_constraint_container(ctx: RenderContext, node: dict, level: int, node_path: str) -> list[str]:
    ctx.needs_constraint_layout = True
    children = node.get("children", [])
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    ref_names = [f"ref{index}" for index in range(len(children))]
    lines = [f"{indent(level)}ConstraintLayout("]
    lines.append(f"{indent(level + 1)}modifier = {modifier}")
    lines.append(f"{indent(level)}) {{")
    lines.append(f"{indent(level + 1)}val ({', '.join(ref_names)}) = createRefs()")
    for index, child in enumerate(children):
        constrained = dict(child)
        constrained_style = dict(child.get("style", {}))
        left = constrained_style.pop("left", 0) or 0
        top = constrained_style.pop("top", 0) or 0
        constrained_style.pop("right", None)
        constrained_style.pop("bottom", None)
        constrained["style"] = constrained_style
        constrained.pop("positioned", None)
        lines.append(f"{indent(level + 1)}Box(")
        lines.append(
            f"{indent(level + 2)}modifier = Modifier.constrainAs({ref_names[index]}) {{"
        )
        lines.append(f"{indent(level + 3)}start.linkTo(parent.start, margin = {dp(left)})")
        lines.append(f"{indent(level + 3)}top.linkTo(parent.top, margin = {dp(top)})")
        lines.append(f"{indent(level + 2)}}}")
        lines.append(f"{indent(level + 1)}) {{")
        lines.extend(render_node(ctx, constrained, level + 2, f"{node_path}_{index}"))
        lines.append(f"{indent(level + 1)}}}")
    lines.append(f"{indent(level)}}}")
    return lines


def render_box_leaf(ctx: RenderContext, node: dict, level: int) -> list[str]:
    modifier = render_modifier(ctx, node).replace("\n", f"\n{indent(level + 2)}")
    return [
        f"{indent(level)}Box(",
        f"{indent(level + 1)}modifier = {modifier}",
        f"{indent(level)})",
    ]


def render_node(ctx: RenderContext, node: dict, level: int, node_path: str) -> list[str]:
    detection = detect_kind(node)
    kind = detection.kind
    if kind == "text":
        return render_text(ctx, node, level)
    if kind == "button":
        return render_button(ctx, node, level)
    if kind == "input":
        return render_input(ctx, node, level)
    if kind == "image":
        return render_image(ctx, node, level, node_path)
    if kind == "lazy_column":
        return render_lazy_column(ctx, node, level, node_path)
    if kind == "tab_row":
        return render_tab_row(ctx, node, level)
    if kind == "pager":
        return render_pager(ctx, node, level, node_path)
    if kind == "constraint":
        return render_constraint_container(ctx, node, level, node_path)
    if node.get("children"):
        return render_container(ctx, node, level, node_path, kind)
    return render_box_leaf(ctx, node, level)


def render_kotlin(ctx: RenderContext, spec: dict) -> str:
    body_lines: list[str] = []
    pager_page_count = 1
    for index, node in enumerate(spec["tree"]):
        detection = detect_kind(node)
        if detection.kind == "pager":
            pager_page_count = max(pager_page_count, len(node.get("children", [])))
        body_lines.extend(render_node(ctx, node, 2, str(index)))

    imports = [
        "import androidx.compose.foundation.BorderStroke",
        "import androidx.compose.foundation.Image",
        "import androidx.compose.foundation.background",
        "import androidx.compose.foundation.border",
        "import androidx.compose.foundation.horizontalScroll",
        "import androidx.compose.foundation.layout.Box",
        "import androidx.compose.foundation.layout.Column",
        "import androidx.compose.foundation.layout.Row",
        "import androidx.compose.foundation.layout.fillMaxHeight",
        "import androidx.compose.foundation.layout.fillMaxSize",
        "import androidx.compose.foundation.layout.fillMaxWidth",
        "import androidx.compose.foundation.layout.height",
        "import androidx.compose.foundation.layout.offset",
        "import androidx.compose.foundation.layout.padding",
        "import androidx.compose.foundation.layout.size",
        "import androidx.compose.foundation.layout.width",
        "import androidx.compose.foundation.lazy.LazyColumn",
        "import androidx.compose.foundation.rememberScrollState",
        "import androidx.compose.foundation.shape.RoundedCornerShape",
        "import androidx.compose.foundation.shadow",
        "import androidx.compose.foundation.verticalScroll",
        "import androidx.compose.foundation.pager.HorizontalPager",
        "import androidx.compose.foundation.pager.rememberPagerState",
        "import androidx.compose.material3.Button",
        "import androidx.compose.material3.OutlinedTextField",
        "import androidx.compose.material3.Tab",
        "import androidx.compose.material3.TabRow",
        "import androidx.compose.material3.Text",
        "import androidx.compose.runtime.Composable",
        "import androidx.compose.runtime.getValue",
        "import androidx.compose.runtime.mutableIntStateOf",
        "import androidx.compose.runtime.remember",
        "import androidx.compose.runtime.setValue",
        "import androidx.compose.ui.Modifier",
        "import androidx.compose.ui.draw.clip",
        "import androidx.compose.ui.draw.alpha",
        "import androidx.compose.ui.graphics.Brush",
        "import androidx.compose.ui.graphics.Color",
        "import androidx.compose.ui.res.colorResource",
        "import androidx.compose.ui.res.painterResource",
        "import androidx.compose.ui.res.stringResource",
        "import androidx.compose.ui.text.TextStyle",
        "import androidx.compose.ui.text.font.FontWeight",
        "import androidx.compose.ui.text.style.TextAlign",
        "import androidx.compose.ui.tooling.preview.Preview",
        "import androidx.compose.ui.unit.dp",
        "import androidx.compose.ui.unit.sp",
        "import androidx.constraintlayout.compose.ConstraintLayout",
    ]
    lines = [f"package {ctx.package_name}", "", *imports, "", ""]
    if ctx.low_precision:
        lines.append("// Low precision mode: values are approximated from screenshot or partial source.")
        lines.append("")
    if ctx.warnings:
        for warning in ctx.warnings:
            lines.append(f"// renderer-note: {warning}")
        lines.append("")
    lines.append("@Composable")
    lines.append(f"fun {ctx.screen_name}() {{")
    lines.append(f"{indent(1)}{ctx.screen_name}Content()")
    lines.append("}")
    lines.append("")
    lines.append("@Composable")
    lines.append(f"private fun {ctx.screen_name}Content() {{")
    if ctx.needs_tab_state:
        lines.append(f"{indent(1)}var selectedTabIndex by remember {{ mutableIntStateOf(0) }}")
    if ctx.needs_pager_state:
        lines.append(f"{indent(1)}val pagerState = rememberPagerState(pageCount = {{ {pager_page_count} }})")
    lines.append(f"{indent(1)}Column(")
    lines.append(f"{indent(2)}modifier = Modifier.fillMaxSize()")
    lines.append(f"{indent(1)}) {{")
    lines.extend(body_lines)
    lines.append(f"{indent(1)}}}")
    lines.append("}")
    lines.append("")
    lines.append("@Preview(showBackground = true)")
    lines.append("@Composable")
    lines.append(f"private fun {ctx.screen_name}Preview() {{")
    lines.append(f"{indent(1)}{ctx.screen_name}()")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_colors_xml(colors: dict[str, dict]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for _, value in sorted(colors.items(), key=lambda item: item[1]["name"]):
        lines.append(f'    <color name="{value["name"]}">{value["hex"]}</color>')
    lines.append("</resources>")
    return "\n".join(lines) + "\n"


def render_strings_xml(strings: list[tuple[str, str]]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for key, value in strings:
        lines.append(f'    <string name="{key}">{xml_escape(value)}</string>')
    lines.append("</resources>")
    return "\n".join(lines) + "\n"


def render_icon_markdown(icons: list[tuple[str, str]]) -> str:
    if not icons:
        return "# Icon Placeholders\n\n- 无图片/图标占位。\n"
    lines = ["# Icon Placeholders", ""]
    for name, desc in icons:
        lines.append(f"- `{name}` -> {desc}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Compose UI from lanhu spec.json")
    parser.add_argument("--spec", help="Path to spec.json")
    parser.add_argument("--wxml", help="Path to wxml.txt")
    parser.add_argument("--wxss", help="Path to wxss.txt")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--screen-name", help="Compose screen name, e.g. LoginScreen")
    parser.add_argument("--package-name", default="generated.compose", help="Kotlin package name")
    parser.add_argument("--project-root", help="Android project root for optional integration")
    parser.add_argument("--module-name", help="Target Android module, default app")
    parser.add_argument("--target-file", help="Existing Kotlin file to replace marked block")
    parser.add_argument(
        "--write-mode",
        default="none",
        choices=["none", "generated", "replace-block"],
        help="Optionally write generated files into a real Android project",
    )
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "partial", "screenshot", "fallback"],
        help="Source precision mode",
    )
    return parser.parse_args()


def resolve_spec(args: argparse.Namespace) -> tuple[dict, str, str]:
    if args.spec:
        spec_path = Path(args.spec)
        return load_spec(spec_path), str(spec_path), spec_path.stem

    if args.wxml and args.wxss:
        wxml_path = Path(args.wxml)
        wxss_path = Path(args.wxss)
        if not wxml_path.exists():
            raise ValueError(f"WXML 不存在: {wxml_path}")
        if not wxss_path.exists():
            raise ValueError(f"WXSS 不存在: {wxss_path}")
        with tempfile.TemporaryDirectory(prefix="compose_renderer_spec_") as temp_dir:
            temp_spec_path = Path(temp_dir) / "spec.json"
            spec = generate_spec(wxml_path, wxss_path, temp_spec_path)
            return spec, f"generated-from:{wxml_path}", wxml_path.stem

    raise ValueError("需要提供 --spec，或同时提供 --wxml 和 --wxss")


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec, spec_ref, name_seed = resolve_spec(args)

    screen_name = pascal_case(args.screen_name or name_seed)
    if not screen_name.endswith("Screen"):
        screen_name += "Screen"

    ctx = RenderContext(
        screen_name=screen_name,
        package_name=args.package_name,
        mode=args.mode,
        low_precision=args.mode in LOW_PRECISION_MODES,
        colors=spec["colors"],
    )

    kotlin = render_kotlin(ctx, spec)
    colors_xml = render_colors_xml(spec["colors"])
    strings_xml = render_strings_xml(ctx.strings)
    icon_md = render_icon_markdown(ctx.icons)

    (out_dir / f"{screen_name}.kt").write_text(kotlin, encoding="utf-8")
    (out_dir / "colors.xml").write_text(colors_xml, encoding="utf-8")
    (out_dir / "strings.xml").write_text(strings_xml, encoding="utf-8")
    (out_dir / "icon_placeholders.md").write_text(icon_md, encoding="utf-8")

    integration = None
    if args.write_mode != "none":
        if args.project_root:
            project_root = Path(args.project_root)
        else:
            project_root = find_android_project_root(Path.cwd())
        if project_root is None:
            raise ValueError("未找到 Android 工程根目录，请通过 --project-root 显式指定")
        if not detect_compose_project(project_root):
            print("WARNING: 目标工程未检测到明确 Compose 信号，已继续执行写回。")
        if args.write_mode == "generated":
            integration = write_generated_files(
                project_root=project_root,
                module_name=args.module_name,
                package_name=args.package_name,
                screen_name=screen_name,
                kotlin=kotlin,
                colors_xml=colors_xml,
                strings_xml=strings_xml,
            )
        else:
            if not args.target_file:
                raise ValueError("--write-mode replace-block 需要同时提供 --target-file")
            integration = replace_marked_block(Path(args.target_file), kotlin)

    print(f"SPEC_SOURCE:{spec_ref}")
    print(f"SCREEN:{out_dir / f'{screen_name}.kt'}")
    print(f"COLORS:{out_dir / 'colors.xml'}")
    print(f"STRINGS:{out_dir / 'strings.xml'}")
    print(f"ICONS:{out_dir / 'icon_placeholders.md'}")
    print(f"SUMMARY:nodes={len(spec['tree'])}, strings={len(ctx.strings)}, icons={len(ctx.icons)}")
    if integration:
        print(f"INTEGRATION_MODE:{integration.mode}")
        if integration.kotlin_path:
            print(f"INTEGRATED_KOTLIN:{integration.kotlin_path}")
        if integration.colors_path:
            print(f"INTEGRATED_COLORS:{integration.colors_path}")
        if integration.strings_path:
            print(f"INTEGRATED_STRINGS:{integration.strings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
