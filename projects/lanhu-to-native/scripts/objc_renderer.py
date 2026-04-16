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
from objc_detect import detect_kind
from objc_integrate import (
    detect_objc_project,
    find_xcode_project_root,
    replace_view_block,
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
    parts = snake_case(value).split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


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


@dataclass
class ObjcContext:
    view_name: str
    controller_name: str
    package_prefix: str
    mode: str
    low_precision: bool
    colors: dict[str, dict]
    strings: dict[str, str] = field(default_factory=dict)
    icons: list[tuple[str, str]] = field(default_factory=list)
    prop_declarations: list[tuple[str, str]] = field(default_factory=list)
    _prop_counts: dict = field(default_factory=dict)
    _image_counter: int = 0

    def _unique_prop(self, base: str) -> str:
        count = self._prop_counts.get(base, 0)
        self._prop_counts[base] = count + 1
        return base if count == 0 else f"{base}{count + 1}"

    def new_prop(self, uikit_class: str, classes: list[str]) -> str:
        prefix_map = {
            "UILabel": "label",
            "UITextField": "textField",
            "UITextView": "textView",
            "UIImageView": "imageView",
            "UIButton": "button",
            "UIScrollView": "scrollView",
            "UISegmentedControl": "segmentedControl",
            "UIView": "containerView",
        }
        base_prefix = prefix_map.get(uikit_class, "view")
        class_suffix = camel_case(classes[0]) if classes else ""
        base = f"{base_prefix}{class_suffix.capitalize()}" if class_suffix else base_prefix
        prop_name = self._unique_prop(base)
        self.prop_declarations.append((uikit_class, prop_name))
        return prop_name

    def string_macro(self, text: str) -> str:
        for key, value in self.strings.items():
            if value == text:
                return f"{self.package_prefix}Str_{key}"
        key = f"{snake_case(self.view_name)}_text_{len(self.strings) + 1}"
        self.strings[key] = text
        return f"{self.package_prefix}Str_{key}"

    def color_expr(self, style: dict, key: str) -> str | None:
        value = style.get(key)
        if not isinstance(value, str):
            return None
        if value in self.colors:
            name = self.colors[value]["name"]
            return f"{self.package_prefix}Color_{name}"
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raw = value.lstrip("#").upper()
            suffix = " // 估算值" if self.low_precision else ""
            return f"UIColorFromRGB(0x{raw}){suffix}"
        if re.fullmatch(r"#[0-9A-Fa-f]{8}", value):
            raw = value.lstrip("#").upper()
            suffix = " // 估算值" if self.low_precision else ""
            return f"UIColorFromRGBA(0x{raw}){suffix}"
        return None

    def image_placeholder(self, node: dict) -> str:
        self._image_counter += 1
        classes = "_".join(node.get("classes", []))
        semantic = "image"
        for candidate in ("back", "avatar", "icon", "logo", "close"):
            if candidate in classes:
                semantic = candidate
                break
        name = f"ic{self.view_name}{semantic.capitalize()}{self._image_counter}"
        desc = " / ".join(p for p in [node.get("tag", "image"), classes or None] if p)
        self.icons.append((name, desc))
        return name


def _font_weight(value: object) -> str | None:
    if isinstance(value, str):
        lower = value.lower()
        if lower in {"bold", "700"}:
            return "UIFontWeightBold"
        if lower in {"600", "semibold"}:
            return "UIFontWeightSemibold"
        if lower in {"500", "medium"}:
            return "UIFontWeightMedium"
        if lower in {"light", "300"}:
            return "UIFontWeightLight"
    if isinstance(value, (int, float)):
        n = int(value)
        if n >= 700:
            return "UIFontWeightBold"
        if n >= 600:
            return "UIFontWeightSemibold"
        if n >= 500:
            return "UIFontWeightMedium"
    return None


def _config_label(ctx: ObjcContext, node: dict, var: str) -> list[str]:
    style = node.get("style", {})
    lines: list[str] = []
    text = (node.get("text") or "").strip()
    if text:
        lines.append(f"        {var}.text = {ctx.string_macro(text)};")
    font_size = style.get("font-size")
    if isinstance(font_size, (int, float)):
        weight = _font_weight(style.get("font-weight"))
        if weight:
            lines.append(f"        {var}.font = [UIFont systemFontOfSize:{format_number(font_size)} weight:{weight}];")
        else:
            lines.append(f"        {var}.font = [UIFont systemFontOfSize:{format_number(font_size)}];")
    color = ctx.color_expr(style, "color")
    if color:
        lines.append(f"        {var}.textColor = {color};")
    max_lines = style.get("max-lines")
    lines.append(f"        {var}.numberOfLines = {int(max_lines) if isinstance(max_lines, (int, float)) else 0};")
    align_map = {"left": "NSTextAlignmentLeft", "center": "NSTextAlignmentCenter", "right": "NSTextAlignmentRight"}
    ns_align = align_map.get(str(style.get("text-align", "")))
    if ns_align:
        lines.append(f"        {var}.textAlignment = {ns_align};")
    return lines


def _config_textfield(ctx: ObjcContext, node: dict, var: str, multiline: bool) -> list[str]:
    style = node.get("style", {})
    lines: list[str] = []
    text = (node.get("text") or "").strip()
    if text:
        attr = "text" if multiline else "placeholder"
        lines.append(f"        {var}.{attr} = {ctx.string_macro(text)};")
    color = ctx.color_expr(style, "color")
    if color:
        lines.append(f"        {var}.textColor = {color};")
    font_size = style.get("font-size")
    if isinstance(font_size, (int, float)):
        lines.append(f"        {var}.font = [UIFont systemFontOfSize:{format_number(font_size)}];")
    return lines


def _config_button(ctx: ObjcContext, node: dict, var: str) -> list[str]:
    style = node.get("style", {})
    lines: list[str] = []
    text = (node.get("text") or "").strip()
    if text:
        lines.append(f"        [{var} setTitle:{ctx.string_macro(text)} forState:UIControlStateNormal];")
    bg = ctx.color_expr(style, "background-color")
    if bg:
        lines.append(f"        {var}.backgroundColor = {bg};")
    color = ctx.color_expr(style, "color")
    if color:
        lines.append(f"        [{var} setTitleColor:{color} forState:UIControlStateNormal];")
    radius = style.get("border-radius")
    if isinstance(radius, (int, float)):
        lines.append(f"        {var}.layer.cornerRadius = {format_number(radius)};")
        lines.append(f"        {var}.layer.masksToBounds = YES;")
    return lines


def _config_imageview(ctx: ObjcContext, node: dict, var: str) -> list[str]:
    name = ctx.image_placeholder(node)
    return [
        f'        {var}.image = [UIImage imageNamed:@"{name}"]; // TODO: replace icon asset',
        f"        {var}.contentMode = UIViewContentModeScaleAspectFill;",
        f"        {var}.clipsToBounds = YES;",
    ]


def _config_view(ctx: ObjcContext, node: dict, var: str) -> list[str]:
    style = node.get("style", {})
    lines: list[str] = []
    bg = ctx.color_expr(style, "background-color") or ctx.color_expr(style, "background")
    if bg:
        lines.append(f"        {var}.backgroundColor = {bg};")
    radius = style.get("border-radius")
    if isinstance(radius, (int, float)):
        lines.append(f"        {var}.layer.cornerRadius = {format_number(radius)};")
        lines.append(f"        {var}.layer.masksToBounds = YES;")
    opacity = style.get("opacity")
    if isinstance(opacity, (int, float)):
        lines.append(f"        {var}.alpha = {format_number(opacity)};")
    return lines


def _make_constraints(
    ctx: ObjcContext,
    node: dict,
    prop_name: str,
    parent_prop: str,
    prev_sibling: str | None,
    container_kind: str,
) -> list[str]:
    style = node.get("style", {})
    est = " // 估算值" if ctx.low_precision else ""
    parent_ref = "self" if parent_prop == "self" else f"self.{parent_prop}"
    lines = [f"    [self.{prop_name} mas_makeConstraints:^(MASConstraintMaker *make) {{"]

    width = style.get("width")
    if width == "match_parent":
        lines.append(f"        make.left.right.equalTo({parent_ref});")
    elif isinstance(width, (int, float)):
        lines.append(f"        make.width.mas_equalTo({format_number(width)});{est}")

    height = style.get("height")
    if isinstance(height, (int, float)):
        lines.append(f"        make.height.mas_equalTo({format_number(height)});{est}")

    if node.get("positioned") == "absolute":
        left = style.get("left")
        top = style.get("top")
        if isinstance(left, (int, float)):
            lines.append(f"        make.left.equalTo({parent_ref}).offset({format_number(left)});{est}")
        if isinstance(top, (int, float)):
            lines.append(f"        make.top.equalTo({parent_ref}).offset({format_number(top)});{est}")
    elif container_kind in {"hstack", "hscroll"}:
        if prev_sibling:
            lines.append(f"        make.left.equalTo(self.{prev_sibling}.mas_right);")
        else:
            padding = style.get("padding") or {}
            pad_left = padding.get("left", 0) if isinstance(padding, dict) else 0
            if isinstance(pad_left, (int, float)) and pad_left > 0:
                lines.append(f"        make.left.equalTo({parent_ref}).offset({format_number(pad_left)});{est}")
            else:
                lines.append(f"        make.left.equalTo({parent_ref});")
        lines.append(f"        make.top.equalTo({parent_ref});")
    else:
        # vstack / vscroll / zstack / root: stack vertically
        if prev_sibling:
            lines.append(f"        make.top.equalTo(self.{prev_sibling}.mas_bottom);")
        else:
            padding = style.get("padding") or {}
            pad_top = padding.get("top", 0) if isinstance(padding, dict) else 0
            if isinstance(pad_top, (int, float)) and pad_top > 0:
                lines.append(f"        make.top.equalTo({parent_ref}).offset({format_number(pad_top)});{est}")
            else:
                lines.append(f"        make.top.equalTo({parent_ref});")
        if width != "match_parent" and not isinstance(width, (int, float)):
            padding = style.get("padding") or {}
            pad_left = padding.get("left", 0) if isinstance(padding, dict) else 0
            if isinstance(pad_left, (int, float)) and pad_left > 0:
                lines.append(f"        make.left.equalTo({parent_ref}).offset({format_number(pad_left)});{est}")
            else:
                lines.append(f"        make.left.equalTo({parent_ref});")

    lines.append("    }];")
    return lines


_UIKIT_CLASS = {
    "label": "UILabel",
    "textfield": "UITextField",
    "imageview": "UIImageView",
    "button": "UIButton",
    "tabbar": "UISegmentedControl",
    "vscroll": "UIScrollView",
    "hscroll": "UIScrollView",
    "vstack": "UIView",
    "hstack": "UIView",
    "zstack": "UIView",
    "view": "UIView",
}


def render_node(
    ctx: ObjcContext,
    node: dict,
    parent_prop: str,
    prev_sibling: str | None,
    container_kind: str,
    node_path: str,
    init_lines: list[str],
    constraint_lines: list[str],
) -> str:
    detection = detect_kind(node)
    kind = detection.kind
    uikit_class = _UIKIT_CLASS.get(kind, "UIView")
    multiline = node.get("tag") == "textarea"
    if multiline:
        uikit_class = "UITextView"

    prop_name = ctx.new_prop(uikit_class, node.get("classes", []))
    parent_ref = "self" if parent_prop == "self" else f"self.{parent_prop}"

    init_lines.append(f"    self.{prop_name} = ({{")
    init_lines.append(f"        {uikit_class} *v = [{uikit_class} new];")

    if kind == "label":
        init_lines.extend(_config_label(ctx, node, "v"))
    elif kind == "textfield":
        init_lines.extend(_config_textfield(ctx, node, "v", multiline))
    elif kind == "button":
        init_lines.extend(_config_button(ctx, node, "v"))
    elif kind == "imageview":
        init_lines.extend(_config_imageview(ctx, node, "v"))
    else:
        init_lines.extend(_config_view(ctx, node, "v"))

    init_lines.append(f"        [{parent_ref} addSubview:v]; v;")
    init_lines.append("    });")

    constraint_lines.extend(_make_constraints(ctx, node, prop_name, parent_prop, prev_sibling, container_kind))

    children = node.get("children", [])
    if children and kind not in {"label", "textfield", "button", "imageview"}:
        child_parent = prop_name
        child_kind = kind

        if kind in {"vscroll", "hscroll"}:
            cv_prop = ctx.new_prop("UIView", [])
            init_lines.append(f"    self.{cv_prop} = ({{")
            init_lines.append(f"        UIView *v = [UIView new];")
            init_lines.append(f"        [self.{prop_name} addSubview:v]; v;")
            init_lines.append("    });")
            constraint_lines.append(f"    [self.{cv_prop} mas_makeConstraints:^(MASConstraintMaker *make) {{")
            constraint_lines.append(f"        make.edges.equalTo(self.{prop_name});")
            if kind == "vscroll":
                constraint_lines.append(f"        make.width.equalTo(self.{prop_name});")
            else:
                constraint_lines.append(f"        make.height.equalTo(self.{prop_name});")
            constraint_lines.append("    }];")
            child_parent = cv_prop
            child_kind = "vstack" if kind == "vscroll" else "hstack"

        if kind == "tabbar":
            titles = [c.get("text", "").strip() for c in children if c.get("text")]
            if titles:
                items = ", ".join(f'@"{t}"' for t in titles)
                init_lines.append(f"    // TODO: UISegmentedControl items: [{items}]")
        else:
            prev: str | None = None
            for index, child in enumerate(children):
                prev = render_node(ctx, child, child_parent, prev, child_kind,
                                   f"{node_path}_{index}", init_lines, constraint_lines)

    return prop_name


def render_view_h(ctx: ObjcContext) -> str:
    lines = [
        "#import <UIKit/UIKit.h>",
        "",
        "NS_ASSUME_NONNULL_BEGIN",
        "",
        f"@interface {ctx.view_name} : UIView",
        "",
    ]
    for uikit_class, prop_name in ctx.prop_declarations:
        lines.append(f"@property (nonatomic, strong) {uikit_class} *{prop_name};")
    lines += [
        "",
        "- (instancetype)initWithFrame:(CGRect)frame NS_DESIGNATED_INITIALIZER;",
        "",
        "@end",
        "",
        "NS_ASSUME_NONNULL_END",
        "",
    ]
    return "\n".join(lines)


def render_view_m(ctx: ObjcContext, init_lines: list[str], constraint_lines: list[str]) -> str:
    body = "\n".join(init_lines) + "\n\n" + "\n".join(constraint_lines)
    prefix = ""
    if ctx.low_precision:
        prefix = "// ⚠️ 低精度模式：尺寸为视觉估算值，颜色为近似值，建议提供蓝湖链接获取精确数据。\n\n"
    lines = [
        f'{prefix}#import "{ctx.view_name}.h"',
        "#import <Masonry/Masonry.h>",
        '#import "LHColors.h"',
        '#import "LHStrings.h"',
        "",
        f"@implementation {ctx.view_name}",
        "",
        "- (instancetype)initWithFrame:(CGRect)frame {",
        "    self = [super initWithFrame:frame];",
        "    if (self) { [self initSubviews]; }",
        "    return self;",
        "}",
        "",
        "// BEGIN AUTO-GENERATED LANHU UI",
        "- (void)initSubviews {",
        body,
        "}",
        "// END AUTO-GENERATED LANHU UI",
        "",
        "@end",
        "",
    ]
    return "\n".join(lines)


def render_controller_h(ctx: ObjcContext) -> str:
    return "\n".join([
        "#import <UIKit/UIKit.h>",
        "",
        "NS_ASSUME_NONNULL_BEGIN",
        "",
        f"@interface {ctx.controller_name} : UIViewController",
        "",
        "@end",
        "",
        "NS_ASSUME_NONNULL_END",
        "",
    ])


def render_controller_m(ctx: ObjcContext) -> str:
    return "\n".join([
        f'#import "{ctx.controller_name}.h"',
        f'#import "{ctx.view_name}.h"',
        "#import <Masonry/Masonry.h>",
        "",
        f"@interface {ctx.controller_name} ()",
        f"@property (nonatomic, strong) {ctx.view_name} *contentView;",
        "@end",
        "",
        f"@implementation {ctx.controller_name}",
        "",
        "- (void)viewDidLoad {",
        "    [super viewDidLoad];",
        f"    self.contentView = [{ctx.view_name} new];",
        "    [self.view addSubview:self.contentView];",
        "    [self.contentView mas_makeConstraints:^(MASConstraintMaker *make) {",
        "        make.edges.equalTo(self.view);",
        "    }];",
        "}",
        "",
        "@end",
        "",
    ])


def render_colors_h(colors: dict[str, dict], prefix: str) -> str:
    lines = [
        "#ifndef LHColors_h",
        "#define LHColors_h",
        "// RGB（6位 hex）",
        "#define UIColorFromRGB(hex) \\",
        "    [UIColor colorWithRed:((hex>>16)&0xFF)/255.0 \\",
        "                   green:((hex>>8)&0xFF)/255.0 \\",
        "                    blue:(hex&0xFF)/255.0 alpha:1.0]",
        "// RGBA（8位 hex，格式 RRGGBBAA）",
        "#define UIColorFromRGBA(hex) \\",
        "    [UIColor colorWithRed:((hex>>24)&0xFF)/255.0 \\",
        "                   green:((hex>>16)&0xFF)/255.0 \\",
        "                    blue:((hex>>8)&0xFF)/255.0 \\",
        "                   alpha:(hex&0xFF)/255.0]",
        "",
    ]
    for _, entry in sorted(colors.items(), key=lambda item: item[1]["name"]):
        name = entry["name"]
        raw = entry["hex"].lstrip("#").upper()
        macro = "UIColorFromRGBA" if len(raw) == 8 else "UIColorFromRGB"
        lines.append(f"#define {prefix}Color_{name}  {macro}(0x{raw})")
    lines += ["#endif", ""]
    return "\n".join(lines)


def render_strings_h(strings: dict[str, str], prefix: str) -> str:
    lines = ["#ifndef LHStrings_h", "#define LHStrings_h", ""]
    for key, value in strings.items():
        escaped = value.replace('"', '\\"')
        lines.append(f'#define {prefix}Str_{key}  @"{escaped}"')
    lines += ["#endif", ""]
    return "\n".join(lines)


def render_icon_markdown(icons: list[tuple[str, str]]) -> str:
    if not icons:
        return "# Icon Placeholders\n\n- No icon placeholders.\n"
    lines = ["# Icon Placeholders", ""]
    for name, desc in icons:
        lines.append(f"- `{name}` -> {desc}")
    lines.append("")
    return "\n".join(lines)


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
        wxml_path, wxss_path = Path(args.wxml), Path(args.wxss)
        if not wxml_path.exists() or not wxss_path.exists():
            raise ValueError("WXML/WXSS 文件不存在")
        with tempfile.TemporaryDirectory(prefix="objc_renderer_spec_") as tmp:
            tmp_spec = Path(tmp) / "spec.json"
            spec = generate_spec(wxml_path, wxss_path, tmp_spec)
            return spec, f"generated-from:{wxml_path}", wxml_path.stem
    raise ValueError("需要提供 --spec，或同时提供 --wxml 和 --wxss")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render ObjC UIView+UIViewController from lanhu spec.json")
    parser.add_argument("--spec")
    parser.add_argument("--wxml")
    parser.add_argument("--wxss")
    parser.add_argument("--out", required=True)
    parser.add_argument("--view-name")
    parser.add_argument("--package-prefix", default="LH")
    parser.add_argument("--group-path")
    parser.add_argument("--project-root")
    parser.add_argument("--target-file")
    parser.add_argument("--write-mode", default="none",
                        choices=["none", "generated", "replace-view-block"])
    parser.add_argument("--mode", default="full",
                        choices=["full", "partial", "screenshot", "fallback"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec, spec_ref, name_seed = resolve_spec(args)

    view_name = pascal_case(args.view_name or name_seed)
    if not view_name.endswith("View"):
        view_name += "View"
    controller_name = view_name[:-4] + "ViewController"

    ctx = ObjcContext(
        view_name=view_name,
        controller_name=controller_name,
        package_prefix=args.package_prefix,
        mode=args.mode,
        low_precision=args.mode in LOW_PRECISION_MODES,
        colors=spec["colors"],
    )

    init_lines: list[str] = []
    constraint_lines: list[str] = []
    roots = spec["tree"]
    if len(roots) == 1:
        render_node(ctx, roots[0], "self", None, "root", "0", init_lines, constraint_lines)
    else:
        prev: str | None = None
        for index, root in enumerate(roots):
            prev = render_node(ctx, root, "self", prev, "root", str(index), init_lines, constraint_lines)

    view_h = render_view_h(ctx)
    view_m = render_view_m(ctx, init_lines, constraint_lines)
    controller_h = render_controller_h(ctx)
    controller_m = render_controller_m(ctx)
    colors_h = render_colors_h(spec["colors"], args.package_prefix)
    strings_h = render_strings_h(ctx.strings, args.package_prefix)
    icon_md = render_icon_markdown(ctx.icons)

    view_h_path = out_dir / f"{view_name}.h"
    view_m_path = out_dir / f"{view_name}.m"
    controller_h_path = out_dir / f"{controller_name}.h"
    controller_m_path = out_dir / f"{controller_name}.m"
    colors_path = out_dir / "LHColors.h"
    strings_path = out_dir / "LHStrings.h"
    icons_path = out_dir / "icon_placeholders.md"

    view_h_path.write_text(view_h, encoding="utf-8")
    view_m_path.write_text(view_m, encoding="utf-8")
    controller_h_path.write_text(controller_h, encoding="utf-8")
    controller_m_path.write_text(controller_m, encoding="utf-8")
    colors_path.write_text(colors_h, encoding="utf-8")
    strings_path.write_text(strings_h, encoding="utf-8")
    icons_path.write_text(icon_md, encoding="utf-8")

    integration = None
    if args.write_mode != "none":
        project_root = (
            Path(args.project_root) if args.project_root else find_xcode_project_root(Path.cwd())
        )
        if project_root is None:
            raise ValueError("未找到 iOS 工程根目录，请通过 --project-root 显式指定")
        if not detect_objc_project(project_root):
            print("WARNING: 目标工程未检测到明确 ObjC UIKit 信号，已继续执行写回。", file=sys.stderr)
        if args.write_mode == "generated":
            integration = write_generated_files(
                project_root=project_root,
                group_path=args.group_path,
                view_name=view_name,
                view_h=view_h,
                view_m=view_m,
                controller_h=controller_h,
                controller_m=controller_m,
                colors_content=colors_h,
                strings_content=strings_h,
            )
        else:  # replace-view-block
            if not args.target_file:
                raise ValueError("--write-mode replace-view-block 需要同时提供 --target-file")
            target = Path(args.target_file)
            if not target.name.endswith("View.m"):
                raise ValueError("--target-file 必须指向 *View.m 文件")
            method_lines = ["- (void)initSubviews {"]
            method_lines.extend(init_lines)
            method_lines.append("")
            method_lines.extend(constraint_lines)
            method_lines.append("}")
            integration = replace_view_block(target, "\n".join(method_lines))

    print(f"SPEC_SOURCE:{spec_ref}")
    print(f"VIEW_H:{view_h_path}")
    print(f"VIEW_M:{view_m_path}")
    print(f"CONTROLLER_H:{controller_h_path}")
    print(f"CONTROLLER_M:{controller_m_path}")
    print(f"COLORS:{colors_path}")
    print(f"STRINGS:{strings_path}")
    print(f"ICONS:{icons_path}")
    print(f"SUMMARY:nodes={len(spec['tree'])}, strings={len(ctx.strings)}, icons={len(ctx.icons)}")
    if integration:
        print(f"INTEGRATION_MODE:{integration.mode}")
        if integration.view_h_path:
            print(f"INTEGRATED_VIEW_H:{integration.view_h_path}")
        if integration.view_m_path:
            print(f"INTEGRATED_VIEW_M:{integration.view_m_path}")
        if integration.controller_h_path:
            print(f"INTEGRATED_CONTROLLER_H:{integration.controller_h_path}")
        if integration.controller_m_path:
            print(f"INTEGRATED_CONTROLLER_M:{integration.controller_m_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
