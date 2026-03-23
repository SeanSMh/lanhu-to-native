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
from xml_detect import detect_kind, is_status_bar_mock
from xml_integrate import (
    detect_android_xml_project,
    find_android_project_root,
    replace_marked_block,
    write_generated_files,
)


LOW_PRECISION_MODES = {"screenshot", "fallback"}


def snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^0-9a-zA-Z]+", "_", value).strip("_")
    value = re.sub(r"_+", "_", value)
    return value.lower() or "lanhu"


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


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


def build_dimen_name(prefix: str, raw_value: int | float | str) -> str:
    text = str(raw_value).replace(".", "_").replace("-", "neg_")
    return f"lh_{prefix}_{text}".lower()


@dataclass
class XmlContext:
    layout_name: str
    mode: str
    low_precision: bool
    colors: dict[str, dict]
    strings: dict[str, str] = field(default_factory=dict)
    dimens: dict[str, str] = field(default_factory=dict)
    drawable_files: dict[str, str] = field(default_factory=dict)
    extra_layouts: dict[str, str] = field(default_factory=dict)
    icons: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    string_counter: int = 0
    image_counter: int = 0
    drawable_counter: int = 0
    id_counts: dict = field(default_factory=dict)

    def unique_view_id(self, base_id: str) -> str:
        count = self.id_counts.get(base_id, 0)
        self.id_counts[base_id] = count + 1
        return base_id if count == 0 else f"{base_id}_{count}"

    def string_ref(self, text: str) -> str:
        if text not in self.strings.values():
            self.string_counter += 1
            key = f"{self.layout_name}_text_{self.string_counter}"
            self.strings[key] = text
            return key
        for key, value in self.strings.items():
            if value == text:
                return key
        raise AssertionError("unreachable")

    def dimen_ref(self, prefix: str, value: int | float | str, unit: str) -> str:
        key = build_dimen_name(prefix, value)
        if key not in self.dimens:
            self.dimens[key] = f"{format_number(value)}{unit}"
        return f"@dimen/{key}"

    def image_placeholder(self, node_path: str, node: dict) -> str:
        self.image_counter += 1
        classes = "_".join(node.get("classes", []))
        semantic = "image"
        for candidate in ("back", "avatar", "icon", "logo", "close"):
            if candidate in classes:
                semantic = candidate
                break
        name = f"ic_{self.layout_name}_{semantic}_{self.image_counter}"
        desc = " / ".join(part for part in [node.get("tag", "image"), classes or None] if part)
        self.icons.append((name, desc))
        return name

    def drawable_ref(self, style: dict) -> str | None:
        gradient = parse_gradient(style.get("background"))
        bg_color = extract_color(self, style, "background-color") or extract_color(self, style, "background")
        radius = style.get("border-radius")
        border_color = extract_color(self, style, "border-color")
        border_width = style.get("border-width")
        if not any([gradient, radius, border_color, border_width, bg_color]):
            return None
        self.drawable_counter += 1
        name = f"bg_{self.layout_name}_{self.drawable_counter}.xml"
        self.drawable_files[name] = build_shape_drawable(
            gradient=gradient,
            solid_color=bg_color,
            radius=radius,
            stroke_color=border_color,
            stroke_width=border_width,
        )
        return f"@drawable/{name[:-4]}"


def parse_gradient(value: object) -> list[str] | None:
    if not isinstance(value, str) or "linear-gradient" not in value:
        return None
    colors = re.findall(r"#[0-9A-Fa-f]{6,8}", value)
    return colors[:3] if len(colors) >= 2 else None


def build_shape_drawable(
    gradient: list[str] | None,
    solid_color: str | None,
    radius: object,
    stroke_color: str | None,
    stroke_width: object,
) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', '<shape xmlns:android="http://schemas.android.com/apk/res/android">']
    if gradient:
        lines.append(
            f'    <gradient android:angle="0" android:startColor="{gradient[0]}" android:endColor="{gradient[1]}"/>'
        )
    elif solid_color:
        lines.append(f'    <solid android:color="{solid_color}"/>')
    if isinstance(radius, (int, float)):
        lines.append(f'    <corners android:radius="{format_number(radius)}dp"/>')
    if stroke_color and isinstance(stroke_width, (int, float)):
        lines.append(
            f'    <stroke android:width="{format_number(stroke_width)}dp" android:color="{stroke_color}"/>'
        )
    lines.append("</shape>")
    return "\n".join(lines) + "\n"


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
        with tempfile.TemporaryDirectory(prefix="xml_renderer_spec_") as temp_dir:
            temp_spec_path = Path(temp_dir) / "spec.json"
            spec = generate_spec(wxml_path, wxss_path, temp_spec_path)
            return spec, f"generated-from:{wxml_path}", wxml_path.stem
    raise ValueError("需要提供 --spec，或同时提供 --wxml 和 --wxss")


def extract_color(ctx: XmlContext, style: dict, key: str) -> str | None:
    value = style.get(key)
    if not isinstance(value, str):
        return None
    if value in ctx.colors:
        return ctx.colors[value]["hex"]
    if re.fullmatch(r"#[0-9A-Fa-f]{6,8}", value):
        return value.upper()
    return None


def view_tag_for_node(node: dict) -> str:
    detection = detect_kind(node).kind
    return {
        "linear_vertical": "LinearLayout",
        "linear_horizontal": "LinearLayout",
        "vertical_scroll": "ScrollView",
        "horizontal_scroll": "HorizontalScrollView",
        "constraint": "androidx.constraintlayout.widget.ConstraintLayout",
        "tab_layout": "com.google.android.material.tabs.TabLayout",
        "view_pager": "androidx.viewpager2.widget.ViewPager2",
        "recycler_view": "androidx.recyclerview.widget.RecyclerView",
        "text": "TextView",
        "image": "ImageView",
        "button": "Button",
        "input": "EditText",
        "frame": "FrameLayout",
        "view": "View",
    }[detection]


def open_tag(tag: str, level: int, attrs: list[tuple[str, str]], self_close: bool = False) -> list[str]:
    indent_str = " " * (level * 4)
    lines = [f"{indent_str}<{tag}"]
    for key, value in attrs:
        lines.append(f'{indent_str}    {key}="{xml_escape(value)}"')
    if self_close:
        lines.append(f"{indent_str}/>")
        return lines
    lines.append(f"{indent_str}>")
    return lines


def close_tag(tag: str, level: int) -> str:
    return f"{' ' * (level * 4)}</{tag}>"


def build_common_attrs(ctx: XmlContext, node: dict, view_id: str) -> list[tuple[str, str]]:
    style = node.get("style", {})
    detection = detect_kind(node).kind
    attrs = [("android:id", f"@+id/{view_id}")]

    width = style.get("width")
    height = style.get("height")
    attrs.append(("android:layout_width", "match_parent" if width == "match_parent" else (
        ctx.dimen_ref("width", width, "dp") if isinstance(width, (int, float)) else "wrap_content"
    )))
    attrs.append(("android:layout_height", "match_parent" if height == "match_parent" else (
        ctx.dimen_ref("height", height, "dp") if isinstance(height, (int, float)) else "wrap_content"
    )))

    if detection == "linear_horizontal":
        attrs.append(("android:orientation", "horizontal"))
    if detection == "linear_vertical":
        attrs.append(("android:orientation", "vertical"))

    padding = style.get("padding")
    if isinstance(padding, dict):
        for attr_name, key in (
            ("android:paddingLeft", "left"),
            ("android:paddingTop", "top"),
            ("android:paddingRight", "right"),
            ("android:paddingBottom", "bottom"),
        ):
            if isinstance(padding.get(key), (int, float)):
                attrs.append((attr_name, ctx.dimen_ref("padding", padding[key], "dp")))

    margin = style.get("margin")
    if isinstance(margin, dict):
        for attr_name, key in (
            ("android:layout_marginLeft", "left"),
            ("android:layout_marginTop", "top"),
            ("android:layout_marginRight", "right"),
            ("android:layout_marginBottom", "bottom"),
        ):
            if isinstance(margin.get(key), (int, float)):
                attrs.append((attr_name, ctx.dimen_ref("margin", margin[key], "dp")))

    drawable_ref = ctx.drawable_ref(style)
    if drawable_ref:
        attrs.append(("android:background", drawable_ref))
    else:
        bg = extract_color(ctx, style, "background-color")
        if bg:
            color_name = ctx.colors.get(bg, {}).get("name")
            attrs.append(("android:background", f"@color/{color_name}" if color_name else bg))

    opacity = style.get("opacity")
    if isinstance(opacity, (int, float)):
        attrs.append(("android:alpha", format_number(opacity)))

    shadow = style.get("box-shadow")
    if isinstance(shadow, str):
        nums = re.findall(r"-?\d+(?:\.\d+)?", shadow)
        if len(nums) >= 3:
            attrs.append(("android:elevation", ctx.dimen_ref("elevation", float(nums[2]), "dp")))

    if node.get("positioned") == "absolute":
        left = style.get("left")
        top = style.get("top")
        if isinstance(left, (int, float)):
            attrs.append(("android:layout_marginStart", ctx.dimen_ref("left", left, "dp")))
            attrs.append(("app:layout_constraintStart_toStartOf", "parent"))
        if isinstance(top, (int, float)):
            attrs.append(("android:layout_marginTop", ctx.dimen_ref("top", top, "dp")))
            attrs.append(("app:layout_constraintTop_toTopOf", "parent"))

    return attrs


def build_text_attrs(ctx: XmlContext, node: dict) -> list[tuple[str, str]]:
    style = node.get("style", {})
    attrs: list[tuple[str, str]] = []
    text = (node.get("text") or "").strip()
    if text:
        attrs.append(("android:text", f"@string/{ctx.string_ref(text)}"))
    color = extract_color(ctx, style, "color")
    if color:
        color_name = ctx.colors.get(color, {}).get("name")
        attrs.append(("android:textColor", f"@color/{color_name}" if color_name else color))
    if isinstance(style.get("font-size"), (int, float)):
        attrs.append(("android:textSize", ctx.dimen_ref("text", style["font-size"], "sp")))
    if isinstance(style.get("line-height"), (int, float)):
        attrs.append(("android:lineHeight", ctx.dimen_ref("line_height", style["line-height"], "sp")))
    font_weight = style.get("font-weight")
    if isinstance(font_weight, str):
        lower = font_weight.lower()
        if lower in {"bold", "700", "600", "semibold"}:
            attrs.append(("android:textStyle", "bold"))
    elif isinstance(font_weight, (int, float)) and int(font_weight) >= 600:
        attrs.append(("android:textStyle", "bold"))
    align = style.get("text-align")
    if isinstance(align, str):
        attrs.append(("android:gravity", {"left": "start", "center": "center", "right": "end"}.get(align, align)))
    max_lines = style.get("max-lines")
    if isinstance(max_lines, (int, float)):
        attrs.append(("android:maxLines", str(int(max_lines))))
    return attrs


def build_input_attrs(ctx: XmlContext, node: dict) -> list[tuple[str, str]]:
    attrs = build_text_attrs(ctx, node)
    hint = (node.get("text") or "").strip()
    if hint:
        attrs.append(("android:hint", f"@string/{ctx.string_ref(hint)}"))
    attrs.append(("android:background", "@android:drawable/edit_text"))
    return attrs


def build_image_attrs(ctx: XmlContext, node: dict, node_path: str) -> list[tuple[str, str]]:
    placeholder = ctx.image_placeholder(node_path, node)
    return [("android:src", f"@drawable/{placeholder}"), ("android:scaleType", "centerCrop")]


def build_button_attrs(ctx: XmlContext, node: dict) -> list[tuple[str, str]]:
    attrs = build_text_attrs(ctx, node)
    return attrs


_SEMANTIC_PREFIX = {
    "text": "tv", "input": "et", "image": "iv", "button": "btn",
    "recycler_view": "rv", "constraint": "cl",
    "linear_horizontal": "ll", "linear_vertical": "ll",
    "vertical_scroll": "sv", "horizontal_scroll": "hsv",
    "tab_layout": "tl", "view_pager": "vp",
    "frame": "fl", "view": "v",
}


def item_layout_name(ctx: XmlContext) -> str:
    return f"{ctx.layout_name}_item_sample"


def _collect_all_text_strings(ctx: XmlContext, nodes: list) -> None:
    """Recursively register every text string found in *nodes* into ctx.strings."""
    for node in nodes:
        if node.get("tag") == "text":
            text = (node.get("text") or "").strip()
            if text:
                ctx.string_ref(text)
        _collect_all_text_strings(ctx, node.get("children", []))


def render_node(ctx: XmlContext, node: dict, level: int, node_path: str, root: bool = False) -> list[str]:
    detection = detect_kind(node).kind
    tag = view_tag_for_node(node)

    # Semantic view ID: {layout}_{kind_prefix}_{class_or_path}
    prefix = _SEMANTIC_PREFIX.get(detection, "v")
    classes = node.get("classes", [])
    class_suffix = snake_case(classes[0]) if classes else ""
    base_id = (
        f"{ctx.layout_name}_{prefix}_{class_suffix}"
        if class_suffix
        else f"{ctx.layout_name}_{prefix}_{node_path.replace('.', '_')}"
    )
    view_id = ctx.unique_view_id(base_id)

    attrs = build_common_attrs(ctx, node, view_id)

    if root:
        # Root layout must always fill parent, not use design canvas pixel dimensions
        for i, (k, _) in enumerate(attrs):
            if k == "android:layout_height":
                attrs[i] = ("android:layout_height", "match_parent")
                break
        attrs.insert(0, ("xmlns:android", "http://schemas.android.com/apk/res/android"))
        attrs.insert(1, ("xmlns:app", "http://schemas.android.com/apk/res-auto"))
        attrs.insert(2, ("xmlns:tools", "http://schemas.android.com/tools"))

    if detection == "text":
        attrs.extend(build_text_attrs(ctx, node))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "input":
        attrs.extend(build_input_attrs(ctx, node))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "image":
        attrs.extend(build_image_attrs(ctx, node, node_path))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "button":
        attrs.extend(build_button_attrs(ctx, node))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "tab_layout":
        attrs.append(("tools:tabCount", str(max(2, len(node.get("children", []))))))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "view_pager":
        attrs.append(("tools:itemCount", str(max(1, len(node.get("children", []))))))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "recycler_view":
        sample_name = item_layout_name(ctx)
        sample_layout = render_sample_item_layout(ctx, node)
        ctx.extra_layouts[f"{sample_name}.xml"] = sample_layout
        # Collect strings from ALL children so strings.xml is complete
        _collect_all_text_strings(ctx, node.get("children", []))
        attrs.append(("tools:listitem", f"@layout/{sample_name}"))
        attrs.append(("tools:itemCount", str(len(node.get("children", [])))))
        return open_tag(tag, level, attrs, self_close=True)
    if detection == "vertical_scroll":
        lines = open_tag(tag, level, attrs)
        inner_attrs = [
            ("android:layout_width", "match_parent"),
            ("android:layout_height", "wrap_content"),
            ("android:orientation", "vertical"),
        ]
        lines.extend(open_tag("LinearLayout", level + 1, inner_attrs))
        for index, child in enumerate(node.get("children", [])):
            if is_status_bar_mock(child):
                continue
            lines.extend(render_node(ctx, child, level + 2, f"{node_path}_{index}"))
        lines.append(close_tag("LinearLayout", level + 1))
        lines.append(close_tag(tag, level))
        return lines
    if detection == "horizontal_scroll":
        lines = open_tag(tag, level, attrs)
        inner_attrs = [
            ("android:layout_width", "wrap_content"),
            ("android:layout_height", "match_parent"),
            ("android:orientation", "horizontal"),
        ]
        lines.extend(open_tag("LinearLayout", level + 1, inner_attrs))
        for index, child in enumerate(node.get("children", [])):
            if is_status_bar_mock(child):
                continue
            lines.extend(render_node(ctx, child, level + 2, f"{node_path}_{index}"))
        lines.append(close_tag("LinearLayout", level + 1))
        lines.append(close_tag(tag, level))
        return lines

    lines = open_tag(tag, level, attrs)
    for index, child in enumerate(node.get("children", [])):
        if is_status_bar_mock(child):
            continue
        lines.extend(render_node(ctx, child, level + 1, f"{node_path}_{index}"))
    lines.append(close_tag(tag, level))
    return lines


def render_sample_item_layout(ctx: XmlContext, node: dict) -> str:
    children = node.get("children", [])
    sample = children[0] if children else {"tag": "view", "widgets": {"android": "LinearLayout[vertical]"}, "style": {}, "children": []}
    lines = render_node(ctx, sample, 0, "sample", root=True)
    return "\n".join(lines) + "\n"


def render_layout(ctx: XmlContext, spec: dict) -> str:
    roots = spec["tree"]
    if len(roots) == 1:
        lines = render_node(ctx, roots[0], 0, "0", root=True)
    else:
        wrapper = {
            "tag": "view",
            "widgets": {"android": "LinearLayout[vertical]"},
            "style": {"width": "match_parent", "height": "match_parent"},
            "children": roots,
        }
        lines = render_node(ctx, wrapper, 0, "root", root=True)
    return "\n".join(lines) + "\n"


def render_values_xml(tag: str, entries: dict[str, str]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for key, value in entries.items():
        lines.append(f'    <{tag} name="{key}">{xml_escape(value)}</{tag}>')
    lines.append("</resources>")
    return "\n".join(lines) + "\n"


def render_colors_xml(colors: dict[str, dict]) -> str:
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<resources>"]
    for _, value in sorted(colors.items(), key=lambda item: item[1]["name"]):
        lines.append(f'    <color name="{value["name"]}">{value["hex"]}</color>')
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
    parser = argparse.ArgumentParser(description="Render Android XML UI from lanhu spec.json")
    parser.add_argument("--spec")
    parser.add_argument("--wxml")
    parser.add_argument("--wxss")
    parser.add_argument("--out", required=True)
    parser.add_argument("--layout-name")
    parser.add_argument("--project-root")
    parser.add_argument("--module-name")
    parser.add_argument("--target-file")
    parser.add_argument("--write-mode", default="none", choices=["none", "generated", "replace-block"])
    parser.add_argument("--mode", default="full", choices=["full", "partial", "screenshot", "fallback"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec, spec_ref, name_seed = resolve_spec(args)
    layout_name = snake_case(args.layout_name or name_seed)
    ctx = XmlContext(
        layout_name=layout_name,
        mode=args.mode,
        low_precision=args.mode in LOW_PRECISION_MODES,
        colors=spec["colors"],
    )

    layout_xml = render_layout(ctx, spec)
    colors_xml = render_colors_xml(spec["colors"])
    strings_xml = render_values_xml("string", ctx.strings)
    dimens_xml = render_values_xml("dimen", ctx.dimens)
    icon_md = render_icon_markdown(ctx.icons)

    (out_dir / f"{layout_name}.xml").write_text(layout_xml, encoding="utf-8")
    (out_dir / "colors.xml").write_text(colors_xml, encoding="utf-8")
    (out_dir / "strings.xml").write_text(strings_xml, encoding="utf-8")
    (out_dir / "dimens.xml").write_text(dimens_xml, encoding="utf-8")
    (out_dir / "icon_placeholders.md").write_text(icon_md, encoding="utf-8")
    drawable_dir = out_dir / "drawable"
    drawable_dir.mkdir(exist_ok=True)
    for file_name, content in ctx.drawable_files.items():
        (drawable_dir / file_name).write_text(content, encoding="utf-8")
    extra_layout_dir = out_dir / "extra_layouts"
    extra_layout_dir.mkdir(exist_ok=True)
    for file_name, content in ctx.extra_layouts.items():
        (extra_layout_dir / file_name).write_text(content, encoding="utf-8")

    integration = None
    if args.write_mode != "none":
        project_root = Path(args.project_root) if args.project_root else find_android_project_root(Path.cwd())
        if project_root is None:
            raise ValueError("未找到 Android 工程根目录，请通过 --project-root 显式指定")
        if not detect_android_xml_project(project_root):
            print("WARNING: 目标工程未检测到明确 XML 信号，已继续执行写回。")
        if args.write_mode == "generated":
            integration = write_generated_files(
                project_root=project_root,
                module_name=args.module_name,
                layout_name=layout_name,
                layout_xml=layout_xml,
                values_files={
                    "colors_lanhu_generated.xml": colors_xml,
                    "strings_lanhu_generated.xml": strings_xml,
                    "dimens_lanhu_generated.xml": dimens_xml,
                },
                drawable_files=ctx.drawable_files,
                extra_layouts=ctx.extra_layouts,
            )
        else:
            if not args.target_file:
                raise ValueError("--write-mode replace-block 需要同时提供 --target-file")
            integration = replace_marked_block(Path(args.target_file), layout_xml)

    print(f"SPEC_SOURCE:{spec_ref}")
    print(f"LAYOUT:{out_dir / f'{layout_name}.xml'}")
    print(f"COLORS:{out_dir / 'colors.xml'}")
    print(f"STRINGS:{out_dir / 'strings.xml'}")
    print(f"DIMENS:{out_dir / 'dimens.xml'}")
    print(f"DRAWABLE_DIR:{drawable_dir}")
    print(f"EXTRA_LAYOUT_DIR:{extra_layout_dir}")
    print(f"ICONS:{out_dir / 'icon_placeholders.md'}")
    print(
        f"SUMMARY:nodes={len(spec['tree'])}, strings={len(ctx.strings)}, dimens={len(ctx.dimens)}, drawables={len(ctx.drawable_files)}, extra_layouts={len(ctx.extra_layouts)}, icons={len(ctx.icons)}"
    )
    if integration:
        print(f"INTEGRATION_MODE:{integration.mode}")
        if integration.layout_path:
            print(f"INTEGRATED_LAYOUT:{integration.layout_path}")
        if integration.values_paths:
            for path in integration.values_paths:
                print(f"INTEGRATED_VALUES:{path}")
        if integration.drawable_paths:
            for path in integration.drawable_paths:
                print(f"INTEGRATED_DRAWABLE:{path}")
        if integration.extra_layout_paths:
            for path in integration.extra_layout_paths:
                print(f"INTEGRATED_EXTRA_LAYOUT:{path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
