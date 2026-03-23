#!/usr/bin/env python3
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

from flutter_detect import detect_kind
from flutter_integrate import (
    detect_flutter_project,
    find_flutter_project_root,
    replace_marked_block,
    write_generated_files,
)
from lanhu_parser import generate_spec


LOW_PRECISION_MODES = {"screenshot", "fallback"}


def snake_case(value: str) -> str:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", normalized).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.lower() or "page"


def pascal_case(value: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", value)
    merged = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return merged or "LanhuPage"


def camel_case(value: str) -> str:
    snake = snake_case(value)
    parts = snake.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


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


def dart_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    return f"'{escaped}'"


def indent_lines(lines: list[str], level: int) -> list[str]:
    pad = " " * (level * 2)
    return [f"{pad}{line}" if line else "" for line in lines]


def parse_gradient(value: object) -> list[str] | None:
    if not isinstance(value, str) or "linear-gradient" not in value:
        return None
    colors = re.findall(r"#[0-9A-Fa-f]{6,8}", value)
    return colors[:3] if len(colors) >= 2 else None


def font_weight_expr(value: object) -> str | None:
    if isinstance(value, str):
        lower = value.lower()
        mapping = {
            "bold": "FontWeight.bold",
            "700": "FontWeight.w700",
            "600": "FontWeight.w600",
            "semibold": "FontWeight.w600",
            "500": "FontWeight.w500",
            "medium": "FontWeight.w500",
            "light": "FontWeight.w300",
            "300": "FontWeight.w300",
        }
        return mapping.get(lower)
    if isinstance(value, (int, float)):
        number = int(value)
        if number >= 700:
            return "FontWeight.w700"
        if number >= 600:
            return "FontWeight.w600"
        if number >= 500:
            return "FontWeight.w500"
    return None


def text_align_expr(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    mapping = {
        "left": "TextAlign.left",
        "center": "TextAlign.center",
        "right": "TextAlign.right",
    }
    return mapping.get(value.lower())


@dataclass
class FlutterContext:
    page_name: str
    mode: str
    low_precision: bool
    colors: dict[str, dict]
    strings: dict[str, str] = field(default_factory=dict)
    icons: list[tuple[str, str]] = field(default_factory=list)
    image_counter: int = 0
    max_tab_count: int = 0

    @property
    def page_snake(self) -> str:
        return snake_case(self.page_name)

    def string_key(self, text: str) -> str:
        for key, value in self.strings.items():
            if value == text:
                return key
        key = f"{self.page_snake}_text_{len(self.strings) + 1}"
        self.strings[key] = text
        return key

    def image_path(self, node_path: str, node: dict) -> str:
        self.image_counter += 1
        classes = "_".join(node.get("classes", []))
        semantic = "image"
        for candidate in ("back", "avatar", "icon", "logo", "close"):
            if candidate in classes:
                semantic = candidate
                break
        name = f"ic_{self.page_snake}_{semantic}_{self.image_counter}"
        desc = " / ".join(part for part in [node.get("tag", "image"), classes or None] if part)
        path = f"assets/icons/{name}.png"
        self.icons.append((path, desc))
        return path


def load_spec(path: Path) -> dict:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec.get("tree"), list) or not spec["tree"]:
        raise ValueError("spec.json 缺少有效 tree")
    if not isinstance(spec.get("colors"), dict):
        raise ValueError("spec.json 缺少有效 colors")
    return spec


def resolve_spec(args: argparse.Namespace) -> tuple[dict, str, str]:
    if args.spec:
        spec_path = Path(args.spec)
        return load_spec(spec_path), str(spec_path), spec_path.stem
    if args.wxml and args.wxss:
        wxml_path = Path(args.wxml)
        wxss_path = Path(args.wxss)
        if not wxml_path.exists() or not wxss_path.exists():
            raise ValueError("WXML/WXSS 文件不存在")
        with tempfile.TemporaryDirectory(prefix="flutter_renderer_spec_") as temp_dir:
            temp_spec_path = Path(temp_dir) / "spec.json"
            spec = generate_spec(wxml_path, wxss_path, temp_spec_path)
            return spec, f"generated-from:{wxml_path}", wxml_path.stem
    raise ValueError("需要提供 --spec，或同时提供 --wxml 和 --wxss")


def color_ref(ctx: FlutterContext, style: dict, key: str) -> str | None:
    value = style.get(key)
    if not isinstance(value, str):
        return None
    if value in ctx.colors:
        return f"AppColors.{camel_case(ctx.colors[value]['name'])}"
    if re.fullmatch(r"#[0-9A-Fa-f]{6,8}", value):
        hex_value = value.upper().replace("#", "")
        if len(hex_value) == 6:
            hex_value = f"FF{hex_value}"
        return f"const Color(0x{hex_value})"
    return None


def build_text_style(ctx: FlutterContext, style: dict) -> list[str]:
    entries: list[str] = []
    font_size = style.get("font-size")
    if isinstance(font_size, (int, float)):
        entries.append(f"fontSize: {format_number(font_size)}")
    weight = font_weight_expr(style.get("font-weight"))
    if weight:
        entries.append(f"fontWeight: {weight}")
    color = color_ref(ctx, style, "color")
    if color:
        entries.append(f"color: {color}")
    line_height = style.get("line-height")
    if isinstance(line_height, (int, float)) and isinstance(font_size, (int, float)) and font_size:
        entries.append(f"height: {round(line_height / font_size, 2)}")
    return entries


def build_edge_insets(padding: dict) -> str | None:
    values = {}
    for key in ("top", "right", "bottom", "left"):
        if isinstance(padding.get(key), (int, float)):
            values[key] = format_number(padding[key])
    if not values:
        return None
    return (
        "EdgeInsets.only("
        f"top: {values.get('top', '0')}, "
        f"right: {values.get('right', '0')}, "
        f"bottom: {values.get('bottom', '0')}, "
        f"left: {values.get('left', '0')})"
    )


def wrap_widget(ctx: FlutterContext, node: dict, child_lines: list[str]) -> list[str]:
    style = node.get("style", {})
    current = child_lines

    width = style.get("width")
    height = style.get("height")
    if width == "match_parent":
        width_expr = "double.infinity"
    elif isinstance(width, (int, float)):
        width_expr = format_number(width)
    else:
        width_expr = None
    if height == "match_parent":
        height_expr = "double.infinity"
    elif isinstance(height, (int, float)):
        height_expr = format_number(height)
    else:
        height_expr = None

    padding_expr = build_edge_insets(style.get("padding", {})) if isinstance(style.get("padding"), dict) else None
    bg_color = color_ref(ctx, style, "background-color") or color_ref(ctx, style, "background")
    gradient = parse_gradient(style.get("background"))
    border_color = color_ref(ctx, style, "border-color")
    border_width = style.get("border-width")
    radius = style.get("border-radius")
    opacity = style.get("opacity")
    shadow_raw = style.get("box-shadow")

    decoration_lines: list[str] = []
    if bg_color:
        decoration_lines.append(f"color: {bg_color},")
    if gradient:
        gradient_colors = ", ".join(
            color_ref(ctx, {"background": color}, "background") or f"const Color(0xFF000000)"
            for color in gradient
        )
        decoration_lines.append(f"gradient: LinearGradient(colors: [{gradient_colors}]),")
    if isinstance(radius, (int, float)):
        decoration_lines.append(
            f"borderRadius: BorderRadius.circular({format_number(radius)}),"
        )
    if border_color and isinstance(border_width, (int, float)):
        decoration_lines.append(
            f"border: Border.all(color: {border_color}, width: {format_number(border_width)}),"
        )
    if isinstance(shadow_raw, str):
        numbers = re.findall(r"-?\d+(?:\.\d+)?", shadow_raw)
        colors = re.findall(r"#[0-9A-Fa-f]{6,8}", shadow_raw)
        if len(numbers) >= 3:
            shadow_color = (
                color_ref(ctx, {"background": colors[0]}, "background")
                if colors
                else "const Color(0x33000000)"
            )
            decoration_lines.append(
                "boxShadow: ["
                f"BoxShadow(color: {shadow_color}, offset: Offset({numbers[0]}, {numbers[1]}), blurRadius: {numbers[2]})"
                "],"
            )

    needs_container = any([width_expr, height_expr, padding_expr, decoration_lines])
    if needs_container:
        wrapped = ["Container("]
        if width_expr:
            wrapped.append(f"  width: {width_expr},")
        if height_expr:
            wrapped.append(f"  height: {height_expr},")
        if padding_expr:
            wrapped.append(f"  padding: {padding_expr},")
        if decoration_lines:
            wrapped.append("  decoration: BoxDecoration(")
            wrapped.extend(indent_lines(decoration_lines, 2))
            wrapped.append("  ),")
        wrapped.append("  child:")
        wrapped.extend(indent_lines(current, 2))
        wrapped.append(")")
        current = wrapped

    if isinstance(opacity, (int, float)):
        current = [
            "Opacity(",
            f"  opacity: {format_number(opacity)},",
            "  child:",
            *indent_lines(current, 2),
            ")",
        ]

    if node.get("positioned") == "absolute":
        left = style.get("left")
        top = style.get("top")
        right = style.get("right")
        bottom = style.get("bottom")
        current = [
            "Positioned(",
            *([f"  left: {format_number(left)},"]
              if isinstance(left, (int, float)) else []),
            *([f"  top: {format_number(top)},"]
              if isinstance(top, (int, float)) else []),
            *([f"  right: {format_number(right)},"]
              if isinstance(right, (int, float)) else []),
            *([f"  bottom: {format_number(bottom)},"]
              if isinstance(bottom, (int, float)) else []),
            "  child:",
            *indent_lines(current, 2),
            ")",
        ]

    return current


def render_text(ctx: FlutterContext, node: dict) -> list[str]:
    style = node.get("style", {})
    key = ctx.string_key((node.get("text") or "").strip())
    style_entries = build_text_style(ctx, style)
    lines = ["Text("]
    lines.append(f"  AppStrings.{camel_case(key)},")
    text_align = text_align_expr(style.get("text-align"))
    if text_align:
        lines.append(f"  textAlign: {text_align},")
    if style_entries:
        lines.append("  style: const TextStyle(")
        lines.extend(indent_lines([f"{entry}," for entry in style_entries], 2))
        lines.append("  ),")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_button(ctx: FlutterContext, node: dict) -> list[str]:
    key = ctx.string_key((node.get("text") or "按钮").strip())
    lines = [
        "ElevatedButton(",
        "  onPressed: () {},",
        f"  child: Text(AppStrings.{camel_case(key)}),",
        ")",
    ]
    return wrap_widget(ctx, node, lines)


def render_input(ctx: FlutterContext, node: dict) -> list[str]:
    key = ctx.string_key((node.get("text") or "").strip() or "placeholder")
    tag = node.get("tag")
    lines = ["TextField("]
    if tag == "textarea":
        lines.append("  maxLines: null,")
    lines.append("  decoration: const InputDecoration(")
    lines.append(f"    hintText: AppStrings.{camel_case(key)},")
    lines.append("  ),")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_image(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    path = ctx.image_path(node_path, node)
    lines = [
        "Image.asset(",
        f"  {dart_string(path)},",
        "  fit: BoxFit.cover,",
        ")",
    ]
    return wrap_widget(ctx, node, lines)


def render_children(ctx: FlutterContext, children: list[dict], path: str) -> list[list[str]]:
    return [render_node(ctx, child, f"{path}_{index}") for index, child in enumerate(children)]


def render_column(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    children = render_children(ctx, node.get("children", []), node_path)
    lines = ["Column(", "  crossAxisAlignment: CrossAxisAlignment.start,", "  children: ["]
    for child in children:
        lines.extend(indent_lines(child, 2))
        lines[-1] = lines[-1] + ","
    lines.append("  ],")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_row(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    children = render_children(ctx, node.get("children", []), node_path)
    lines = ["Row(", "  crossAxisAlignment: CrossAxisAlignment.center,", "  children: ["]
    for child in children:
        lines.extend(indent_lines(child, 2))
        lines[-1] = lines[-1] + ","
    lines.append("  ],")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_stack(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    children = render_children(ctx, node.get("children", []), node_path)
    lines = ["Stack(", "  children: ["]
    for child in children:
        lines.extend(indent_lines(child, 2))
        lines[-1] = lines[-1] + ","
    lines.append("  ],")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_scroll(ctx: FlutterContext, node: dict, node_path: str, horizontal: bool) -> list[str]:
    inner = render_row(ctx, {**node, "style": {}, "children": node.get("children", [])}, node_path) if horizontal else render_column(ctx, {**node, "style": {}, "children": node.get("children", [])}, node_path)
    lines = ["SingleChildScrollView("]
    if horizontal:
        lines.append("  scrollDirection: Axis.horizontal,")
    lines.append("  child:")
    lines.extend(indent_lines(inner, 2))
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_list_view(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    children = render_children(ctx, node.get("children", []), node_path)
    ctx.max_tab_count = max(ctx.max_tab_count, 0)
    lines = [
        "ListView.builder(",
        "  shrinkWrap: true,",
        "  physics: const NeverScrollableScrollPhysics(),",
        f"  itemCount: {len(children)},",
        "  itemBuilder: (context, index) {",
        "    final samples = <Widget>[",
    ]
    for child in children:
        lines.extend(indent_lines(child, 3))
        lines[-1] = lines[-1] + ","
    lines.extend(
        [
            "    ];",
            "    return samples[index];",
            "  },",
            ")",
        ]
    )
    return wrap_widget(ctx, node, lines)


def render_tab_bar(ctx: FlutterContext, node: dict) -> list[str]:
    children = node.get("children", [])
    ctx.max_tab_count = max(ctx.max_tab_count, len(children))
    lines = ["TabBar(", "  isScrollable: true,", "  tabs: ["]
    for child in children:
        key = ctx.string_key((child.get("text") or "标签").strip())
        lines.append(f"    Tab(text: AppStrings.{camel_case(key)}),")
    lines.append("  ],")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_page_view(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    children = render_children(ctx, node.get("children", []), node_path)
    lines = ["PageView(", "  children: ["]
    for child in children:
        lines.extend(indent_lines(child, 2))
        lines[-1] = lines[-1] + ","
    lines.append("  ],")
    lines.append(")")
    return wrap_widget(ctx, node, lines)


def render_spacer() -> list[str]:
    return ["const SizedBox.shrink()"]


def render_node(ctx: FlutterContext, node: dict, node_path: str) -> list[str]:
    kind = detect_kind(node).kind
    if kind == "text":
        return render_text(ctx, node)
    if kind == "button":
        return render_button(ctx, node)
    if kind == "input":
        return render_input(ctx, node)
    if kind == "image":
        return render_image(ctx, node, node_path)
    if kind == "column":
        return render_column(ctx, node, node_path)
    if kind == "row":
        return render_row(ctx, node, node_path)
    if kind == "stack":
        return render_stack(ctx, node, node_path)
    if kind == "vertical_scroll":
        return render_scroll(ctx, node, node_path, horizontal=False)
    if kind == "horizontal_scroll":
        return render_scroll(ctx, node, node_path, horizontal=True)
    if kind == "list_view":
        return render_list_view(ctx, node, node_path)
    if kind == "tab_bar":
        return render_tab_bar(ctx, node)
    if kind == "page_view":
        return render_page_view(ctx, node, node_path)
    if node.get("children"):
        return render_stack(ctx, node, node_path)
    return render_spacer()


def render_dart(ctx: FlutterContext, spec: dict) -> str:
    body_widgets: list[list[str]] = []
    for index, node in enumerate(spec["tree"]):
        body_widgets.append(render_node(ctx, node, str(index)))

    body_lines = ["Column(", "  crossAxisAlignment: CrossAxisAlignment.start,", "  children: ["]
    for widget in body_widgets:
        body_lines.extend(indent_lines(widget, 2))
        body_lines[-1] = body_lines[-1] + ","
    body_lines.append("  ],")
    body_lines.append(")")

    scaffold_lines = [
        "Scaffold(",
        "  body: SafeArea(",
        "    child:",
        *indent_lines(body_lines, 3),
        "  ),",
        ")",
    ]
    root_lines = scaffold_lines
    if ctx.max_tab_count > 0:
        root_lines = [
            "DefaultTabController(",
            f"  length: {ctx.max_tab_count},",
            "  child:",
            *indent_lines(scaffold_lines, 2),
            ")",
        ]

    page_class = ctx.page_name
    lines = [
        "import 'package:flutter/material.dart';",
        "",
        "import 'app_colors.dart';",
        "import 'app_strings.dart';",
        "",
        f"class {page_class} extends StatelessWidget {{",
        f"  const {page_class}({{super.key}});",
        "",
        "  @override",
        "  Widget build(BuildContext context) {",
        "    return",
        *indent_lines(root_lines, 3),
        "    ;",
        "  }",
        "}",
        "",
    ]
    return "\n".join(lines)


def render_colors_file(colors: dict[str, dict]) -> str:
    lines = [
        "import 'package:flutter/material.dart';",
        "",
        "class AppColors {",
        "  const AppColors._();",
    ]
    for _, value in sorted(colors.items(), key=lambda item: item[1]["name"]):
        name = camel_case(value["name"])
        hex_value = value["hex"].replace("#", "")
        if len(hex_value) == 6:
            hex_value = f"FF{hex_value}"
        lines.append(f"  static const Color {name} = Color(0x{hex_value});")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def render_strings_file(strings: dict[str, str]) -> str:
    lines = ["class AppStrings {", "  const AppStrings._();"]
    for key, value in strings.items():
        lines.append(f"  static const String {camel_case(key)} = {dart_string(value)};")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def render_icon_markdown(icons: list[tuple[str, str]]) -> str:
    if not icons:
        return "# Icon Placeholders\n\n- No icon placeholders.\n"
    lines = ["# Icon Placeholders", ""]
    for path, desc in icons:
        lines.append(f"- `{path}` -> {desc}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Flutter page from lanhu spec.json")
    parser.add_argument("--spec")
    parser.add_argument("--wxml")
    parser.add_argument("--wxss")
    parser.add_argument("--out", required=True)
    parser.add_argument("--page-name")
    parser.add_argument("--group-path")
    parser.add_argument("--project-root")
    parser.add_argument("--target-file")
    parser.add_argument("--write-mode", default="none", choices=["none", "generated", "replace-block"])
    parser.add_argument("--mode", default="full", choices=["full", "partial", "screenshot", "fallback"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec, spec_ref, name_seed = resolve_spec(args)
    page_name = pascal_case(args.page_name or name_seed)
    if not page_name.endswith("Page"):
        page_name += "Page"
    ctx = FlutterContext(
        page_name=page_name,
        mode=args.mode,
        low_precision=args.mode in LOW_PRECISION_MODES,
        colors=spec["colors"],
    )
    dart_code = render_dart(ctx, spec)
    colors_file = render_colors_file(spec["colors"])
    strings_file = render_strings_file(ctx.strings)
    icon_md = render_icon_markdown(ctx.icons)
    page_file_name = f"{snake_case(page_name)}.dart"

    (out_dir / page_file_name).write_text(dart_code, encoding="utf-8")
    (out_dir / "app_colors.dart").write_text(colors_file, encoding="utf-8")
    (out_dir / "app_strings.dart").write_text(strings_file, encoding="utf-8")
    (out_dir / "icon_placeholders.md").write_text(icon_md, encoding="utf-8")

    integration = None
    if args.write_mode != "none":
        project_root = Path(args.project_root) if args.project_root else find_flutter_project_root(Path.cwd())
        if project_root is None:
            raise ValueError("未找到 Flutter 工程根目录，请通过 --project-root 显式指定")
        if not detect_flutter_project(project_root):
            print("WARNING: 目标工程未检测到明确 Flutter 信号，已继续执行写回。")
        if args.write_mode == "generated":
            integration = write_generated_files(
                project_root=project_root,
                group_path=args.group_path,
                page_file_name=page_file_name,
                dart_code=dart_code,
                colors_content=colors_file,
                strings_content=strings_file,
            )
        else:
            if not args.target_file:
                raise ValueError("--write-mode replace-block 需要同时提供 --target-file")
            integration = replace_marked_block(Path(args.target_file), dart_code)

    print(f"SPEC_SOURCE:{spec_ref}")
    print(f"PAGE:{out_dir / page_file_name}")
    print(f"COLORS:{out_dir / 'app_colors.dart'}")
    print(f"STRINGS:{out_dir / 'app_strings.dart'}")
    print(f"ICONS:{out_dir / 'icon_placeholders.md'}")
    print(f"SUMMARY:nodes={len(spec['tree'])}, strings={len(ctx.strings)}, icons={len(ctx.icons)}")
    if integration:
        print(f"INTEGRATION_MODE:{integration.mode}")
        if integration.dart_path:
            print(f"INTEGRATED_DART:{integration.dart_path}")
        if integration.colors_path:
            print(f"INTEGRATED_COLORS:{integration.colors_path}")
        if integration.strings_path:
            print(f"INTEGRATED_STRINGS:{integration.strings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
