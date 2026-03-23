#!/usr/bin/env python3
"""
蓝湖 WXML/WXSS 通用解析器 v2
支持 Android / iOS / Flutter 三端。

spec.json 结构：
  canvas  : "750rpx"（画布基准）
  scale   : 2（rpx ÷ 2 = 逻辑像素）
  colors  : {hex: {name, android, ios, flutter}} — 三端颜色引用
  tree    : 组件树，每节点含：
              widgets  : {android, ios, flutter} 三端视图类型
              style    : 已解析样式（尺寸为纯数字逻辑像素，无单位后缀）
                           Android: 加 dp/sp 后缀
                           iOS: 直接用 CGFloat
                           Flutter: 直接用 double
                           padding/margin: {top, right, bottom, left} 数字字典
                           color: 保留 hex，配合 colors 字典转换为三端引用
              positioned: "absolute"（绝对定位节点，父容器已自动改为 ConstraintLayout/ZStack/Stack）
              text     : 文字内容（可选）
              children : 子节点列表（可选）
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Union


# ─── 逻辑像素换算 ────────────────────────────────────────────────

_RPX_RE = re.compile(r"(-?\d+(?:\.\d+)?)rpx")


def _to_lp(rpx: float) -> Union[int, float]:
    """rpx → 逻辑像素（三端通用数值，Android=dp, iOS=pt, Flutter=double）"""
    lp = rpx / 2
    return int(lp) if lp == int(lp) else round(lp, 1)


# ─── 行号清理 ────────────────────────────────────────────────────


def strip_line_numbers(text: str) -> str:
    """移除蓝湖复制代码时夹带的行号行和「复制代码」标题"""
    result = []
    for line in text.splitlines():
        s = line.strip()
        if s == "复制代码" or s.isdigit():
            continue
        result.append(line)
    return "\n".join(result)


# ─── 颜色处理 ────────────────────────────────────────────────────

_KNOWN_COLORS: dict[str, str] = {
    "#FFFFFF": "white",
    "#000000": "black",
    "#333333": "text_primary",
    "#666666": "text_secondary",
    "#999999": "text_hint",
    "#CCCCCC": "divider",        # Fix: was #CCCCCD (typo)
    "#F5F5F5": "bg_light",
    "#F8F8F8": "bg_page",
    "#007AFF": "accent_blue",
    "#0080FF": "blue",           # Fix: was also "accent_blue" (duplicate)
    "#FF3B30": "error_red",
    "#34C759": "success_green",
    "#FF9500": "warning_orange",
    "#00CE98": "teal",           # Fix: was also "success_green" (duplicate)
}

_RGBA_RE = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)"
)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3}$|^#[0-9a-fA-F]{4}$|^#[0-9a-fA-F]{6}$|^#[0-9a-fA-F]{8}$")
_COLOR_PROPS = {
    "color", "background-color", "background",
    "border-color", "border-top-color", "border-bottom-color",
    "border-left-color", "border-right-color",
}


def _rgba_to_hex(r: int, g: int, b: int, a: float = 1.0) -> str:
    if a < 1.0:
        return f"#{r:02X}{g:02X}{b:02X}{int(a * 255):02X}"
    return f"#{r:02X}{g:02X}{b:02X}"


def _normalize_color(val: str) -> Optional[str]:
    """统一将颜色值转为大写 hex（#RRGGBB 或 #RRGGBBAA），失败返回 None"""
    val = val.strip()
    if _HEX_RE.match(val):
        upper = val.upper()
        # Fix: 展开 3-digit (#RGB → #RRGGBB) 和 4-digit (#RGBA → #RRGGBBAA)
        # 不展开会导致 _suggest_color_name 读取错误通道，_build_color_entry 生成非法 Flutter 常量
        if len(upper) == 4:   # #RGB
            return f"#{upper[1]*2}{upper[2]*2}{upper[3]*2}"
        if len(upper) == 5:   # #RGBA
            return f"#{upper[1]*2}{upper[2]*2}{upper[3]*2}{upper[4]*2}"
        return upper
    if m := _RGBA_RE.fullmatch(val):
        a = float(m.group(4)) if m.group(4) else 1.0
        return _rgba_to_hex(int(m.group(1)), int(m.group(2)), int(m.group(3)), a)
    return None


def _to_camel(snake: str) -> str:
    parts = snake.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _suggest_color_name(hex_upper: str) -> str:
    if hex_upper in _KNOWN_COLORS:
        return _KNOWN_COLORS[hex_upper]
    try:
        r, g, b = int(hex_upper[1:3], 16), int(hex_upper[3:5], 16), int(hex_upper[5:7], 16)
    except ValueError:
        return f"color_{hex_upper[1:7].lower()}"
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    suffix = hex_upper[1:7].lower()
    return f"bg_{suffix}" if brightness > 180 else f"color_{suffix}"


def _build_color_entry(hex_upper: str, name: str) -> dict:
    """构建三端颜色引用"""
    camel = _to_camel(name)
    raw = hex_upper[1:]
    # Flutter Color 格式：0xAARRGGBB
    if len(raw) == 8:  # RRGGBBAA → AARRGGBB
        flutter_hex = f"0x{raw[6:8]}{raw[:6]}"
    else:
        flutter_hex = f"0xFF{raw[:6]}"
    return {
        "name": name,
        "hex": hex_upper,
        "android": f"@color/{name}",
        "ios": f'Color("{camel}")',       # Fix: SwiftUI Color asset (was UIKit UIColor)
        "flutter": f"const Color({flutter_hex})",
    }


def extract_colors(styles: dict[str, dict]) -> dict[str, dict]:
    """返回 {hex_upper: {name, android, ios, flutter}}"""
    seen: dict[str, dict] = {}
    for props in styles.values():
        for prop, val in props.items():
            if prop in _COLOR_PROPS and isinstance(val, str):
                key = _normalize_color(val)
                if key and key not in seen:
                    seen[key] = _build_color_entry(key, _suggest_color_name(key))
    return seen


# ─── WXSS 解析 ───────────────────────────────────────────────────

_SHORTHAND_EXPAND = {
    1: lambda c: (c[0], c[0], c[0], c[0]),
    2: lambda c: (c[0], c[1], c[0], c[1]),
    3: lambda c: (c[0], c[1], c[2], c[1]),
    4: lambda c: (c[0], c[1], c[2], c[3]),
}


def _parse_value(prop: str, raw: str) -> object:
    """
    解析单个 CSS 属性值：
    - rpx → 逻辑像素数值（int/float，三端通用）
    - padding/margin → {top, right, bottom, left} 数字字典
    - width: 750rpx → "match_parent"
    - rgba() → 大写 hex 字符串
    - 其他原样返回字符串
    """
    raw = raw.strip()

    # 全宽特判
    if prop in ("width", "min-width") and raw == "750rpx":
        return "match_parent"

    # padding / margin shorthand → 展开为字典
    if prop in ("padding", "margin"):
        parts = raw.split()
        converted: list = []
        for p in parts:
            if m := _RPX_RE.fullmatch(p):
                converted.append(_to_lp(float(m.group(1))))
            elif p == "0":
                converted.append(0)
            else:
                converted.append(p)
        if not converted:          # Fix: 防止空值 IndexError
            return raw
        n = min(len(converted), 4)
        top, right, bottom, left = _SHORTHAND_EXPAND.get(n, _SHORTHAND_EXPAND[1])(converted)
        return {"top": top, "right": right, "bottom": bottom, "left": left}

    # 颜色值 → 统一转 hex
    if prop in _COLOR_PROPS:
        return _normalize_color(raw) or raw

    # 纯 rpx 值 → 逻辑像素数值
    if m := _RPX_RE.fullmatch(raw):
        return _to_lp(float(m.group(1)))

    # 含 rpx 的混合值 → 逐一替换为数值字符串
    if _RPX_RE.search(raw):
        parts = raw.split()
        converted = []
        for p in parts:
            if m := _RPX_RE.fullmatch(p):
                converted.append(str(_to_lp(float(m.group(1)))))
            elif p == "0":
                converted.append("0")
            else:
                converted.append(p)
        return " ".join(converted)

    return raw


def parse_wxss(wxss_text: str) -> dict[str, dict]:
    """
    解析 WXSS → {className: {prop: value}}
    rpx 已换算为逻辑像素数值，rgba() 已转 hex。
    """
    clean = strip_line_numbers(wxss_text)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)

    styles: dict[str, dict] = {}
    block_re = re.compile(r"\.([a-zA-Z0-9_\-]+)\s*\{([^}]*)\}", re.DOTALL)

    for bm in block_re.finditer(clean):
        props: dict[str, object] = {}
        for line in bm.group(2).split(";"):
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if key and val:
                props[key] = _parse_value(key, val)
        if props:
            styles[bm.group(1)] = props

    return styles


# ─── 视图类型映射（三端）────────────────────────────────────────

_TAG_WIDGETS: dict[str, dict[str, str]] = {
    # Fix: ios values changed from UIKit → SwiftUI
    "text":        {"android": "TextView",            "ios": "Text",        "flutter": "Text"},
    "input":       {"android": "EditText",            "ios": "TextField",   "flutter": "TextField"},
    "image":       {"android": "ImageView",           "ios": "Image",       "flutter": "Image.asset"},
    "button":      {"android": "MaterialButton",      "ios": "Button",      "flutter": "ElevatedButton"},
    "scroll-view": {"android": "ScrollView",          "ios": "ScrollView",  "flutter": "SingleChildScrollView"},
    "swiper":      {"android": "ViewPager2",          "ios": "TabView",     "flutter": "PageView"},
    "textarea":    {"android": "EditText[multiline]", "ios": "TextEditor",  "flutter": "TextField(maxLines)"},
    "picker":      {"android": "Spinner",             "ios": "Picker",      "flutter": "DropdownButton"},
}


def _infer_widgets(tag: str, style: dict) -> dict[str, str]:
    if tag in _TAG_WIDGETS:
        return dict(_TAG_WIDGETS[tag])
    if tag == "view":
        is_row = style.get("flex-direction") == "row"
        return {
            "android": f"LinearLayout[{'horizontal' if is_row else 'vertical'}]",
            "ios":     "HStack" if is_row else "VStack",   # Fix: SwiftUI (was UIStackView)
            "flutter": "Row" if is_row else "Column",
        }
    return {"android": "View", "ios": "EmptyView", "flutter": "Container"}


# ─── WXML 解析 ───────────────────────────────────────────────────


_OVERLAY_WIDGETS = {
    "android": "ConstraintLayout",
    "ios":     "ZStack",
    "flutter": "Stack",
}

_TIME_TEXT_RE = re.compile(r"^\d{1,2}:\d{2}$")


def _elem_to_dict(elem: ET.Element, styles: dict[str, dict]) -> dict:
    tag = elem.tag
    classes = elem.get("class", "").split()

    # 合并所有 class 的样式
    resolved: dict[str, object] = {}
    for cls in classes:
        if cls in styles:
            resolved.update(styles[cls])

    node: dict = {
        "tag": tag,
        "classes": classes,
        "widgets": _infer_widgets(tag, resolved),
        "style": resolved,
    }

    # 标记自身是绝对定位的节点
    if resolved.get("position") == "absolute":
        node["positioned"] = "absolute"

    if text := (elem.text or "").strip():
        node["text"] = text

    children = [_elem_to_dict(c, styles) for c in elem]

    # Fix: 如果有任意绝对定位子节点 → 父容器改为 overlay 布局
    if children and any(c.get("positioned") == "absolute" for c in children):
        node["widgets"] = dict(_OVERLAY_WIDGETS)

    if children:
        node["children"] = children

    return node


def _iter_descendants(node: dict):
    for child in node.get("children", []):
        yield child
        yield from _iter_descendants(child)


def _collect_texts(node: dict) -> list[str]:
    texts = []
    if text := (node.get("text") or "").strip():
        texts.append(text)
    for child in node.get("children", []):
        texts.extend(_collect_texts(child))
    return texts


def _style_number(style: dict, key: str):
    value = style.get(key)
    return value if isinstance(value, (int, float)) else None


def _is_small_graphic_leaf(node: dict) -> bool:
    if node.get("children") or node.get("text"):
        return False
    style = node.get("style", {})
    width = _style_number(style, "width")
    height = _style_number(style, "height")
    if width is None or height is None:
        return False
    return 0 < width <= 24 and 0 < height <= 24


def _is_status_bar_mock(node: dict, depth: int) -> bool:
    """
    最小规则（仅影响解析树，不修改原始 WXML）：
    - 有一个短时间文本（如 09:41）
    - 至少两个小图形叶子节点
    - 没有其他非时间文本（避免误删业务标题）
    - 仅在较浅层节点生效，降低误删风险
    """
    if depth > 4:
        return False

    texts = [t for t in _collect_texts(node) if t]
    time_texts = [t for t in texts if _TIME_TEXT_RE.fullmatch(t)]
    non_time_texts = [t for t in texts if not _TIME_TEXT_RE.fullmatch(t)]
    if len(time_texts) != 1 or non_time_texts:
        return False

    descendants = list(_iter_descendants(node))
    small_graphics = sum(1 for child in descendants if _is_small_graphic_leaf(child))
    if small_graphics < 2:
        return False

    heights = [
        _style_number(item.get("style", {}), "height")
        for item in [node, *descendants]
    ]
    numeric_heights = [h for h in heights if isinstance(h, (int, float))]
    if numeric_heights and max(numeric_heights) > 24:
        return False

    return True


def _filter_status_bar_nodes(nodes: list[dict], depth: int = 0) -> list[dict]:
    filtered = []
    for node in nodes:
        children = _filter_status_bar_nodes(node.get("children", []), depth + 1)
        if children:
            node["children"] = children
        else:
            node.pop("children", None)

        if _is_status_bar_mock(node, depth):
            continue
        filtered.append(node)
    return filtered


def parse_wxml(wxml_text: str, styles: dict[str, dict]) -> list[dict]:
    """解析 WXML → 组件树列表"""
    clean = strip_line_numbers(wxml_text)
    clean = (clean
             .replace("&nbsp;", "\u00a0")
             .replace("&amp;", "&")
             .replace("&lt;", "<")
             .replace("&gt;", ">"))

    def try_parse(text: str) -> ET.Element:
        return ET.fromstring(f"<root>{text}</root>")

    try:
        root = try_parse(clean)
    except ET.ParseError:
        clean2 = re.sub(r'"[^"]*"', lambda m: m.group(0).replace("&", ""), clean)
        try:
            root = try_parse(clean2)
        except ET.ParseError as e:
            print(f"WARNING: WXML 解析失败 ({e})", file=sys.stderr)
            return []

    tree = [_elem_to_dict(c, styles) for c in root]
    return _filter_status_bar_nodes(tree)


# ─── 主入口 ──────────────────────────────────────────────────────


def generate_spec(wxml_path: Path, wxss_path: Path, output_path: Path) -> dict:
    """
    读取 wxml.txt + wxss.txt → 解析 → 写入 spec.json
    """
    wxml_text = wxml_path.read_text(encoding="utf-8") if wxml_path.exists() else ""
    wxss_text = wxss_path.read_text(encoding="utf-8") if wxss_path.exists() else ""

    styles = parse_wxss(wxss_text) if wxss_text else {}
    tree   = parse_wxml(wxml_text, styles) if wxml_text else []
    colors = extract_colors(styles)

    spec = {
        "canvas": "750rpx",
        "scale": 2,
        "note": (
            "style 中的尺寸值为逻辑像素（rpx÷2）："
            "Android 加 dp/sp 后缀，iOS 直接用 CGFloat，Flutter 直接用 double；"
            "颜色保留 hex，配合 colors 字典获取三端引用；"
            "widgets 字段提供三端推荐视图类型；"
            "positioned=absolute 表示绝对定位节点，其父节点 widgets 已自动设为 ConstraintLayout/ZStack/Stack"
        ),
        "colors": colors,
        # Fix: 移除顶层 styles 字段（与 tree 节点内联数据重复），减小 spec.json 体积
        "tree": tree,
    }

    output_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return spec


if __name__ == "__main__":
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "output"
    spec = generate_spec(base / "wxml.txt", base / "wxss.txt", base / "spec.json")
    print(
        f"✓ spec.json 生成：{len(spec['colors'])} 个颜色 / {len(spec['tree'])} 个根节点"
    )
