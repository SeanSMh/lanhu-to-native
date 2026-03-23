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

from lanhu_parser import generate_spec
from swiftui_detect import detect_kind
from swiftui_integrate import (
    detect_swiftui_project,
    find_xcode_project_root,
    replace_marked_block,
    write_generated_files,
)


LOW_PRECISION_MODES = {"screenshot", "fallback"}


def snake_case(value: str) -> str:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", normalized).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.lower() or "view"


def pascal_case(value: str) -> str:
    parts = re.split(r"[^0-9a-zA-Z]+", value)
    merged = "".join(part[:1].upper() + part[1:] for part in parts if part)
    return merged or "LanhuView"


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


def swift_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def color_asset_name(color_entry: dict) -> str:
    return camel_case(color_entry["name"])


def parse_gradient(value: object) -> list[str] | None:
    if not isinstance(value, str) or "linear-gradient" not in value:
        return None
    colors = re.findall(r"#[0-9A-Fa-f]{6,8}", value)
    return colors[:3] if len(colors) >= 2 else None


def font_weight_expr(value: object) -> str | None:
    if isinstance(value, str):
        lower = value.lower()
        if lower in {"bold", "700"}:
            return ".bold"
        if lower in {"600", "semibold"}:
            return ".semibold"
        if lower in {"500", "medium"}:
            return ".medium"
        if lower in {"light", "300"}:
            return ".light"
    if isinstance(value, (int, float)):
        number = int(value)
        if number >= 700:
            return ".bold"
        if number >= 600:
            return ".semibold"
        if number >= 500:
            return ".medium"
    return None


def text_align_expr(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    mapping = {
        "left": ".leading",
        "center": ".center",
        "right": ".trailing",
    }
    return mapping.get(value.lower())


@dataclass
class SwiftUIContext:
    view_name: str
    mode: str
    low_precision: bool
    colors: dict[str, dict]
    strings: dict[str, str] = field(default_factory=dict)
    icons: list[tuple[str, str]] = field(default_factory=list)
    image_counter: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def view_snake(self) -> str:
        return snake_case(self.view_name)

    def string_key(self, text: str) -> str:
        for key, value in self.strings.items():
            if value == text:
                return key
        key = f"{self.view_snake}_text_{len(self.strings) + 1}"
        self.strings[key] = text
        return key

    def image_name(self, node_path: str, node: dict) -> str:
        self.image_counter += 1
        classes = "_".join(node.get("classes", []))
        semantic = "image"
        for candidate in ("back", "avatar", "icon", "logo", "close"):
            if candidate in classes:
                semantic = candidate
                break
        name = f"ic{self.view_name}{semantic.capitalize()}{self.image_counter}"
        desc = " / ".join(part for part in [node.get("tag", "image"), classes or None] if part)
        self.icons.append((name, desc))
        return name


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
        with tempfile.TemporaryDirectory(prefix="swiftui_renderer_spec_") as temp_dir:
            temp_spec_path = Path(temp_dir) / "spec.json"
            spec = generate_spec(wxml_path, wxss_path, temp_spec_path)
            return spec, f"generated-from:{wxml_path}", wxml_path.stem
    raise ValueError("需要提供 --spec，或同时提供 --wxml 和 --wxss")


def indent(level: int) -> str:
    return " " * (level * 4)


def swiftui_color(ctx: SwiftUIContext, style: dict, key: str) -> str | None:
    value = style.get(key)
    if not isinstance(value, str):
        return None
    if value in ctx.colors:
        return f'Color("{color_asset_name(ctx.colors[value])}")'
    if re.fullmatch(r"#[0-9A-Fa-f]{6,8}", value):
        return f'Color(hex: "{value.upper()}")'
    return None


def modifier_lines(ctx: SwiftUIContext, node: dict) -> list[str]:
    style = node.get("style", {})
    lines: list[str] = []

    width = style.get("width")
    height = style.get("height")
    if width == "match_parent":
        lines.append(".frame(maxWidth: .infinity)")
    elif isinstance(width, (int, float)):
        lines.append(f".frame(width: {format_number(width)})")
    if height == "match_parent":
        lines.append(".frame(maxHeight: .infinity)")
    elif isinstance(height, (int, float)):
        lines.append(f".frame(height: {format_number(height)})")

    padding = style.get("padding")
    if isinstance(padding, dict):
        entries = []
        for name, key in (
            ("top", "top"),
            ("leading", "left"),
            ("bottom", "bottom"),
            ("trailing", "right"),
        ):
            if isinstance(padding.get(key), (int, float)):
                entries.append(f"{name}: {format_number(padding[key])}")
        if entries:
            lines.append(f".padding(EdgeInsets({', '.join(entries)}))")

    gradient = parse_gradient(style.get("background"))
    background = swiftui_color(ctx, style, "background-color") or swiftui_color(ctx, style, "background")
    if gradient:
        colors = ", ".join(f'Color(hex: "{color}")' for color in gradient)
        lines.append(
            f".background(LinearGradient(colors: [{colors}], startPoint: .leading, endPoint: .trailing))"
        )
    elif background:
        lines.append(f".background({background})")

    radius = style.get("border-radius")
    if isinstance(radius, (int, float)):
        lines.append(f".clipShape(RoundedRectangle(cornerRadius: {format_number(radius)}))")

    border_color = swiftui_color(ctx, style, "border-color")
    border_width = style.get("border-width")
    if border_color and isinstance(border_width, (int, float)):
        corner = format_number(radius or 0)
        lines.append(
            f".overlay(RoundedRectangle(cornerRadius: {corner}).stroke({border_color}, lineWidth: {format_number(border_width)}))"
        )

    shadow_raw = style.get("box-shadow")
    if isinstance(shadow_raw, str):
        numbers = re.findall(r"-?\d+(?:\.\d+)?", shadow_raw)
        colors = re.findall(r"#[0-9A-Fa-f]{6,8}", shadow_raw)
        if len(numbers) >= 3:
            shadow_color = f'Color(hex: "{colors[0]}")' if colors else ".black.opacity(0.2)"
            lines.append(
                f".shadow(color: {shadow_color}, radius: {numbers[2]}, x: {numbers[0]}, y: {numbers[1]})"
            )

    opacity = style.get("opacity")
    if isinstance(opacity, (int, float)):
        lines.append(f".opacity({format_number(opacity)})")

    if node.get("positioned") == "absolute":
        x = style.get("left")
        y = style.get("top")
        if isinstance(x, (int, float)) or isinstance(y, (int, float)):
            lines.append(f".offset(x: {format_number(x or 0)}, y: {format_number(y or 0)})")

    if ctx.low_precision:
        lines = [line + " // estimated" if any(k in line for k in (".frame(", ".padding(", ".offset(")) else line for line in lines]

    return lines


def apply_modifiers(lines: list[str], modifiers: list[str], level: int) -> list[str]:
    result = list(lines)
    for modifier in modifiers:
        result.append(f"{indent(level)}{modifier}")
    return result


def render_text(ctx: SwiftUIContext, node: dict, level: int) -> list[str]:
    style = node.get("style", {})
    key = ctx.string_key((node.get("text") or "").strip())
    lines = [f'{indent(level)}Text("{key}")']
    font_size = style.get("font-size")
    if isinstance(font_size, (int, float)):
        weight = font_weight_expr(style.get("font-weight")) or ".regular"
        lines.append(
            f"{indent(level)}    .font(.system(size: {format_number(font_size)}, weight: {weight}))"
        )
    color = swiftui_color(ctx, style, "color")
    if color:
        lines.append(f"{indent(level)}    .foregroundStyle({color})")
    line_height = style.get("line-height")
    if isinstance(line_height, (int, float)) and isinstance(font_size, (int, float)) and line_height > font_size:
        lines.append(f"{indent(level)}    .lineSpacing({format_number(line_height - font_size)})")
    text_align = text_align_expr(style.get("text-align"))
    if text_align:
        lines.append(f"{indent(level)}    .multilineTextAlignment({text_align})")
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_button(ctx: SwiftUIContext, node: dict, level: int) -> list[str]:
    key = ctx.string_key((node.get("text") or "按钮").strip())
    lines = [
        f"{indent(level)}Button {{",
        f"{indent(level + 1)}}} label: {{",
        f'{indent(level + 2)}Text("{key}")',
        f"{indent(level + 1)}}}",
    ]
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_input(ctx: SwiftUIContext, node: dict, level: int) -> list[str]:
    key = ctx.string_key((node.get("text") or "").strip() or "placeholder")
    tag = node.get("tag")
    if tag == "textarea":
        lines = [
            f"{indent(level)}TextEditor(text: .constant({swift_string(node.get('text') or '')}))"
        ]
    else:
        lines = [
            f'{indent(level)}TextField("{key}", text: .constant(""))'
        ]
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_image(ctx: SwiftUIContext, node: dict, level: int, node_path: str) -> list[str]:
    image_name = ctx.image_name(node_path, node)
    lines = [f'{indent(level)}Image("{image_name}")']
    lines.append(f"{indent(level + 1)}.resizable() // TODO: replace icon asset")
    lines.append(f"{indent(level + 1)}.scaledToFill()")
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_children(ctx: SwiftUIContext, children: list[dict], level: int, path: str) -> list[str]:
    lines: list[str] = []
    for index, child in enumerate(children):
        lines.extend(render_node(ctx, child, level, f"{path}_{index}"))
    return lines


def render_container(ctx: SwiftUIContext, node: dict, level: int, node_path: str, kind: str) -> list[str]:
    name = {
        "vstack": "VStack(alignment: .leading, spacing: 0)",
        "hstack": "HStack(alignment: .center, spacing: 0)",
        "zstack": "ZStack(alignment: .topLeading)",
    }[kind]
    lines = [f"{indent(level)}{name} {{"]
    lines.extend(render_children(ctx, node.get("children", []), level + 1, node_path))
    lines.append(f"{indent(level)}}}")
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_scroll(ctx: SwiftUIContext, node: dict, level: int, node_path: str, axis: str) -> list[str]:
    axis_value = ".horizontal" if axis == "horizontal" else ".vertical"
    inner = "HStack(alignment: .center, spacing: 0)" if axis == "horizontal" else "VStack(alignment: .leading, spacing: 0)"
    lines = [f"{indent(level)}ScrollView({axis_value}, showsIndicators: false) {{", f"{indent(level + 1)}{inner} {{"]
    lines.extend(render_children(ctx, node.get("children", []), level + 2, node_path))
    lines.append(f"{indent(level + 1)}}}")
    lines.append(f"{indent(level)}}}")
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_lazy_vstack(ctx: SwiftUIContext, node: dict, level: int, node_path: str) -> list[str]:
    lines = [f"{indent(level)}ScrollView {{", f"{indent(level + 1)}LazyVStack(alignment: .leading, spacing: 0) {{"]
    lines.extend(render_children(ctx, node.get("children", []), level + 2, node_path))
    lines.append(f"{indent(level + 1)}}}")
    lines.append(f"{indent(level)}}}")
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_tab_view(ctx: SwiftUIContext, node: dict, level: int, node_path: str) -> list[str]:
    lines = [f"{indent(level)}TabView {{"]
    for index, child in enumerate(node.get("children", [])):
        child_lines = render_node(ctx, child, level + 1, f"{node_path}_{index}")
        if child_lines:
            child_lines[-1] = child_lines[-1] + f'\n{indent(level + 2)}.tag({index})'
        lines.extend(child_lines)
    lines.append(f"{indent(level)}}}")
    lines.append(f"{indent(level + 1)}.tabViewStyle(.page(indexDisplayMode: .automatic))")
    return apply_modifiers(lines, modifier_lines(ctx, node), level + 1)


def render_spacer(level: int) -> list[str]:
    return [f"{indent(level)}Spacer(minLength: 0)"]


def render_node(ctx: SwiftUIContext, node: dict, level: int, node_path: str) -> list[str]:
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
    if kind == "vertical_scroll":
        return render_scroll(ctx, node, level, node_path, "vertical")
    if kind == "horizontal_scroll":
        return render_scroll(ctx, node, level, node_path, "horizontal")
    if kind == "lazy_vstack":
        return render_lazy_vstack(ctx, node, level, node_path)
    if kind == "tab_view":
        return render_tab_view(ctx, node, level, node_path)
    if kind in {"vstack", "hstack", "zstack"}:
        return render_container(ctx, node, level, node_path, kind)
    if node.get("children"):
        return render_container(ctx, node, level, node_path, "zstack")
    return render_spacer(level)


def render_swift(ctx: SwiftUIContext, spec: dict) -> str:
    body_lines: list[str] = []
    for index, node in enumerate(spec["tree"]):
        body_lines.extend(render_node(ctx, node, 3, str(index)))

    lines = [
        "import SwiftUI",
        "",
        "private extension Color {",
        "    init(hex: String) {",
        '        let hex = hex.replacingOccurrences(of: "#", with: "")',
        "        var int: UInt64 = 0",
        '        Scanner(string: hex).scanHexInt64(&int)',
        "        let a, r, g, b: UInt64",
        "        switch hex.count {",
        "        case 8:",
        "            (r, g, b, a) = ((int >> 24) & 0xff, (int >> 16) & 0xff, (int >> 8) & 0xff, int & 0xff)",
        "        default:",
        "            (r, g, b, a) = ((int >> 16) & 0xff, (int >> 8) & 0xff, int & 0xff, 255)",
        "        }",
        "        self.init(",
        "            .sRGB,",
        "            red: Double(r) / 255,",
        "            green: Double(g) / 255,",
        "            blue: Double(b) / 255,",
        "            opacity: Double(a) / 255",
        "        )",
        "    }",
        "}",
        "",
        f"struct {ctx.view_name}: View {{",
        "    var body: some View {",
        f"        {ctx.view_name}Content()",
        "    }",
        "}",
        "",
        f"private struct {ctx.view_name}Content: View {{",
        "    var body: some View {",
        "        VStack(alignment: .leading, spacing: 0) {",
        *body_lines,
        "        }",
        "    }",
        "}",
        "",
        "#Preview {",
        f"    {ctx.view_name}()",
        "}",
        "",
    ]
    return "\n".join(lines)


def render_strings_file(strings: dict[str, str]) -> str:
    lines: list[str] = []
    for key, value in strings.items():
        escaped = value.replace('"', '\\"')
        lines.append(f'"{key}" = "{escaped}";')
    return "\n".join(lines) + ("\n" if lines else "")


def render_colors_file(colors: dict[str, dict]) -> str:
    lines = ["# Color Assets"]
    for _, value in sorted(colors.items(), key=lambda item: item[1]["name"]):
        lines.append(f'{color_asset_name(value)} = {value["hex"]}')
    lines.append("")
    return "\n".join(lines)


def render_icon_markdown(icons: list[tuple[str, str]]) -> str:
    if not icons:
        return "# Icon Placeholders\n\n- No icon placeholders.\n"
    lines = ["# Icon Placeholders", ""]
    for name, desc in icons:
        lines.append(f"- `{name}` -> {desc}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render SwiftUI View from lanhu spec.json")
    parser.add_argument("--spec")
    parser.add_argument("--wxml")
    parser.add_argument("--wxss")
    parser.add_argument("--out", required=True)
    parser.add_argument("--view-name")
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
    view_name = pascal_case(args.view_name or name_seed)
    if not view_name.endswith("View"):
        view_name += "View"
    ctx = SwiftUIContext(
        view_name=view_name,
        mode=args.mode,
        low_precision=args.mode in LOW_PRECISION_MODES,
        colors=spec["colors"],
    )
    swift_code = render_swift(ctx, spec)
    strings_file = render_strings_file(ctx.strings)
    colors_file = render_colors_file(spec["colors"])
    icon_md = render_icon_markdown(ctx.icons)

    (out_dir / f"{view_name}.swift").write_text(swift_code, encoding="utf-8")
    (out_dir / "Localizable.strings").write_text(strings_file, encoding="utf-8")
    (out_dir / "ColorAssets.txt").write_text(colors_file, encoding="utf-8")
    (out_dir / "icon_placeholders.md").write_text(icon_md, encoding="utf-8")

    integration = None
    if args.write_mode != "none":
        project_root = Path(args.project_root) if args.project_root else find_xcode_project_root(Path.cwd())
        if project_root is None:
            raise ValueError("未找到 iOS 工程根目录，请通过 --project-root 显式指定")
        if not detect_swiftui_project(project_root):
            print("WARNING: 目标工程未检测到明确 SwiftUI 信号，已继续执行写回。")
        if args.write_mode == "generated":
            integration = write_generated_files(
                project_root=project_root,
                group_path=args.group_path,
                view_name=view_name,
                swift_code=swift_code,
                strings_content=strings_file,
                colors_content=colors_file,
            )
        else:
            if not args.target_file:
                raise ValueError("--write-mode replace-block 需要同时提供 --target-file")
            integration = replace_marked_block(Path(args.target_file), swift_code)

    print(f"SPEC_SOURCE:{spec_ref}")
    print(f"VIEW:{out_dir / f'{view_name}.swift'}")
    print(f"STRINGS:{out_dir / 'Localizable.strings'}")
    print(f"COLORS:{out_dir / 'ColorAssets.txt'}")
    print(f"ICONS:{out_dir / 'icon_placeholders.md'}")
    print(f"SUMMARY:nodes={len(spec['tree'])}, strings={len(ctx.strings)}, icons={len(ctx.icons)}")
    if integration:
        print(f"INTEGRATION_MODE:{integration.mode}")
        if integration.swift_path:
            print(f"INTEGRATED_SWIFT:{integration.swift_path}")
        if integration.strings_path:
            print(f"INTEGRATED_STRINGS:{integration.strings_path}")
        if integration.colors_path:
            print(f"INTEGRATED_COLORS:{integration.colors_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
