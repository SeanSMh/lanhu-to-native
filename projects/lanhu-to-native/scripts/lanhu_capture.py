#!/usr/bin/env python3
"""
蓝湖设计稿抓取脚本 v5
原理：直接访问 DDS URL，注入 localStorage.token，
优先从 #imgPreview 对应的已加载图片响应中保存原始设计图，
再拦截「复制代码」按钮的 clipboard 写入，获取完整 WXML + WXSS，
然后调用 lanhu_parser 生成结构化 spec.json（单位已换算为 dp/sp）。

用法：
    python3 lanhu_capture.py '<蓝湖 detailDetach URL>'
    python3 lanhu_capture.py --bootstrap '<蓝湖 detailDetach URL>'

输出（供 Skill 解析）：
    RUN_DIR:/path/to/output/runs/<run_id>
    SCREENSHOT:/path/to/design.png
    SCREENSHOT_META:/path/to/design.meta.json
    SCREENSHOT_STATUS:ok
    WXML_TREE:/path/to/wxml_tree.json
    WXML:/path/to/wxml.txt
    WXSS:/path/to/wxss.txt
    SPEC:/path/to/spec.json
    SOURCE_STATUS:ok|partial|source_not_ready|unavailable|auth_failed
    SOURCE_REASON:...
"""

import asyncio
import argparse
import datetime as _dt
import importlib
import importlib.util
import json as _json
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

# 解析器（同目录）
SCRIPT_DIR = Path(__file__).resolve().parent
FALLBACK_SKILL_SCRIPT_DIR = Path.home() / ".codex/skills/lanhu-to-native/scripts"
sys.path.insert(0, str(SCRIPT_DIR))
if FALLBACK_SKILL_SCRIPT_DIR != SCRIPT_DIR:
    sys.path.append(str(FALLBACK_SKILL_SCRIPT_DIR))
from lanhu_parser import generate_spec, parse_wxml, parse_wxss

def _resolve_base_output_dir() -> Path:
    candidates = [
        SCRIPT_DIR / "output",
        Path(tempfile.gettempdir()) / "lanhu-to-native-output",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue
    raise RuntimeError("无法创建输出目录，请检查脚本目录或 /tmp 写权限")


BASE_OUTPUT_DIR = _resolve_base_output_dir()
RUNS_DIR = BASE_OUTPUT_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_PACKAGES = ("browser_cookie3", "playwright")


def _create_run_dir() -> Path:
    run_id = f"{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def extract_dds_url(lanhu_url: str) -> Optional[str]:
    """从蓝湖 URL 中提取 ddsUrl 参数，返回 DDS 直接访问 URL"""
    parsed = urlparse(lanhu_url)
    fragment = parsed.fragment  # /item/project/detailDetach?pid=...
    if "?" in fragment:
        _, frag_query = fragment.split("?", 1)
        params = parse_qs(frag_query)
    else:
        params = parse_qs(parsed.query)

    dds_url_raw = params.get("ddsUrl", [None])[0]
    if dds_url_raw:
        return unquote(dds_url_raw)

    # 如果没有 ddsUrl，尝试从 version_id 构建
    version_id = None
    for key in ["version_id", "vid"]:
        v = params.get(key, [None])[0]
        if v:
            version_id = v
            break
    if not version_id:
        # 尝试从 ddsUrl 参数的 value 里找
        m = re.search(r"version_id=([a-f0-9\-]+)", lanhu_url)
        if m:
            version_id = m.group(1)

    if version_id:
        # Fix: 去掉 plugin_version 硬编码，避免版本过期导致 DDS 拒绝请求
        return f"https://dds.lanhuapp.com/#/?version_id={version_id}&source=detailDetachTab"

    return None


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _missing_python_packages() -> list[str]:
    return [name for name in PYTHON_PACKAGES if not _module_available(name)]


def _playwright_browser_cache_dirs() -> list[Path]:
    return [
        Path.home() / "Library/Caches/ms-playwright",
        Path.home() / ".cache/ms-playwright",
    ]


def _chromium_installed() -> bool:
    prefixes = ("chromium-", "chromium_headless_shell-", "chrome-")
    for base_dir in _playwright_browser_cache_dirs():
        if not base_dir.exists():
            continue
        try:
            if any(child.is_dir() and child.name.startswith(prefixes) for child in base_dir.iterdir()):
                return True
        except OSError:
            continue
    return False


def _dependency_hint(reason: str, detail: str = "") -> str:
    if reason == "ok":
        return "运行环境检查通过"
    if reason == "not_required":
        return "当前输入为本地文件，不需要 Playwright 或蓝湖登录态"
    if reason == "missing_python_pkg":
        return "建议执行: pip3 install browser-cookie3 playwright"
    if reason == "missing_browser":
        return "建议执行: python3 -m playwright install chromium"
    if reason == "browser_verification_blocked":
        return "请在“系统设置 -> 隐私与安全性”中允许 Playwright 下载的 Chromium 组件，例如 libvk_swiftshader.dylib"
    if reason == "cookie_permission_denied":
        host = Path(sys.executable).name
        return (
            f"请在 macOS 的“系统设置 -> 隐私与安全性 -> 完全磁盘访问权限”中，"
            f"为当前运行宿主（如 {host}、Codex、Terminal、iTerm）授权访问 Chrome 数据；"
            "授权后请完全退出并重新打开当前宿主应用，再重试"
        )
    if reason == "cookie_unavailable":
        return "请确认本机已安装 Chrome，且当前用户有权限读取 Chrome cookies"
    if reason == "auth_cookie_missing":
        return "请先在本机 Chrome 中登录蓝湖后重试"
    return detail


def _dependency_action(status: str, reason: str = "") -> str:
    if status in {"ok", "not_required"}:
        return "continue"
    if status in {"missing_python_pkg", "missing_browser"}:
        return "install_dependency"
    if status == "browser_verification_blocked":
        return "allow_macos_binary"
    if status == "cookie_permission_denied":
        return "grant_macos_permission"
    if status == "cookie_unavailable":
        return "check_chrome_access"
    if status == "auth_cookie_missing":
        return "login_lanhu"
    return "stop"


def _dependency_bootstrap_allowed(status: str) -> str:
    return "true" if status in {"missing_python_pkg", "missing_browser"} else "false"


def _is_permission_denied_error(exc: Exception) -> bool:
    if isinstance(exc, PermissionError):
        return True
    text = str(exc).lower()
    markers = (
        "operation not permitted",
        "permission denied",
        "not authorized",
        "access denied",
    )
    return any(marker in text for marker in markers)


def _is_browser_verification_blocked_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = (
        "libvk_swiftshader.dylib",
        "libegl.dylib",
        "cannot be opened because the developer cannot be verified",
        "developer cannot be verified",
        "cannot be verified",
        "damaged and can’t be opened",
        "damaged and can't be opened",
        "was blocked from use because it is not from an identified developer",
    )
    return any(marker in text for marker in markers)


def print_dependency_status(status: str, reason: str = "") -> None:
    print(f"DEPENDENCY_STATUS:{status}")
    if reason:
        print(f"DEPENDENCY_REASON:{reason}")
    print(f"DEPENDENCY_ACTION:{_dependency_action(status, reason)}")
    hint = _dependency_hint(status, reason)
    if hint:
        print(f"DEPENDENCY_HINT:{hint}")
    print(f"DEPENDENCY_BOOTSTRAP_ALLOWED:{_dependency_bootstrap_allowed(status)}")


def ensure_runtime_dependencies(bootstrap: bool) -> tuple[str, str]:
    missing = _missing_python_packages()
    if missing:
        if bootstrap:
            print(f"正在安装缺失 Python 依赖: {', '.join(missing)}", file=sys.stderr)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "browser-cookie3", "playwright"],
                check=True,
            )
            importlib.invalidate_caches()
            missing = _missing_python_packages()
        if missing:
            return "missing_python_pkg", ",".join(missing)

    if not _chromium_installed():
        if bootstrap:
            print("正在安装 Playwright Chromium...", file=sys.stderr)
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        if not _chromium_installed():
            return "missing_browser", "chromium_not_installed"

    try:
        cookies = get_cookies()
    except Exception as exc:  # noqa: BLE001
        if _is_permission_denied_error(exc):
            return "cookie_permission_denied", exc.__class__.__name__
        return "cookie_unavailable", exc.__class__.__name__

    if not any(cookie["name"] == "user_token" for cookie in cookies):
        return "auth_cookie_missing", "user_token_not_found"

    return "ok", ""


def load_playwright():
    from playwright.async_api import async_playwright

    return async_playwright


def get_cookies() -> list[dict]:
    """从 Chrome 读取蓝湖 cookies，转换为 Playwright 格式"""
    import browser_cookie3

    raw = browser_cookie3.chrome(domain_name=".lanhuapp.com")
    return [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": False,
        }
        for c in raw
    ]


CLIPBOARD_INTERCEPT = """
window.__clipboardData = [];
const _origWrite = navigator.clipboard.writeText.bind(navigator.clipboard);
navigator.clipboard.writeText = function(text) {
    window.__clipboardData.push(text);
    return _origWrite(text);
};
const _origExec = document.execCommand.bind(document);
document.execCommand = function(cmd, ...args) {
    if (cmd === 'copy') {
        const sel = window.getSelection();
        if (sel) window.__clipboardData.push(sel.toString());
    }
    return _origExec(cmd, ...args);
};
"""


def _strip_query(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def _guess_image_suffix(content_type: str, url: str) -> str:
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type == "image/png":
        return ".png"
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/webp":
        return ".webp"
    path = urlparse(url).path.lower()
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        if path.endswith(suffix):
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


async def _find_preview_image(page, timeout_seconds: float = 15.0):
    """
    在整棵页面树（主文档 + 所有 iframe）中查找设计图图片节点。
    优先命中 #imgPreview，其次回退到蓝湖设计图常见 CDN 图片。
    """
    candidate_selectors = (
        "img#imgPreview",
        "img[src*='SketchCover']",
        "img[src*='alipic.lanhuapp.com']",
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    while True:
        for frame in page.frames:
            for selector in candidate_selectors:
                try:
                    handles = await frame.query_selector_all(selector)
                except Exception:
                    continue

                for handle in handles:
                    try:
                        meta = await handle.evaluate(
                            """
                            img => ({
                                src: img.currentSrc || img.src || "",
                                naturalWidth: img.naturalWidth || 0,
                                naturalHeight: img.naturalHeight || 0,
                                clientWidth: img.clientWidth || 0,
                                clientHeight: img.clientHeight || 0,
                                complete: !!img.complete,
                                id: img.id || "",
                                className: img.className || "",
                                frameUrl: window.location.href
                            })
                            """
                        )
                        box = await handle.bounding_box()
                    except Exception:
                        continue

                    if not meta.get("src"):
                        continue

                    visible_enough = (
                        (box and box.get("width", 0) > 0 and box.get("height", 0) > 0)
                        or meta.get("clientWidth", 0) > 0
                        or meta.get("naturalWidth", 0) > 0
                    )
                    if not visible_enough:
                        continue

                    return handle, meta

        if loop.time() >= deadline:
            return None, {}
        await asyncio.sleep(0.25)


async def _wait_for_cached_image(
    image_url: str,
    image_responses: dict[str, dict],
    response_tasks: list[asyncio.Task],
    timeout_seconds: float = 4.0,
) -> Optional[dict]:
    """等待并匹配 #imgPreview 对应的已缓存图片响应。"""
    if not image_url:
        return None

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    processed = 0
    target_url = _strip_query(image_url)

    while True:
        pending = response_tasks[processed:]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            processed = len(response_tasks)

        exact = image_responses.get(image_url)
        if exact:
            return exact

        for cached_url, cached_entry in image_responses.items():
            if _strip_query(cached_url) == target_url:
                return cached_entry

        if loop.time() >= deadline:
            return None
        await asyncio.sleep(0.2)


async def _find_copy_buttons(page, timeout_seconds: float = 8.0):
    """兼容旧调用，返回主源码面板中的复制按钮。"""
    panel = await _find_source_panel(page, timeout_seconds=timeout_seconds)
    return panel["buttons"] if panel else []


async def _collect_page_tree_text(page) -> str:
    """汇总主文档和所有 iframe 的可见文本，用于弱状态判断。"""
    parts: list[str] = []
    for frame in page.frames:
        try:
            text = await frame.evaluate("() => document.body ? (document.body.innerText || '') : ''")
        except Exception:
            continue
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _get_visible_copy_buttons(frame):
    buttons = []
    try:
        handles = await frame.query_selector_all("text=复制代码")
    except Exception:
        return buttons

    for handle in handles:
        try:
            box = await handle.bounding_box()
        except Exception:
            box = None
        if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
            buttons.append((handle, box))
    buttons.sort(key=lambda item: (item[1].get("y", 0), item[1].get("x", 0)))
    return buttons


async def _find_source_panel(page, timeout_seconds: float = 8.0):
    """
    在整棵页面树中选择"最像源码区"的 frame。
    最小方案：按复制按钮数量、WXML/WXSS/微信小程序文本、代码片段特征做粗排序。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    code_like_re = re.compile(r"<(?:view|text|image|button|scroll-view|input)\b|\.[A-Za-z0-9_-]+\s*\{")

    best_panel = None
    best_score = -1

    while True:
        for frame in page.frames:
            try:
                text = await frame.evaluate("() => document.body ? (document.body.innerText || '') : ''")
            except Exception:
                text = ""

            button_pairs = await _get_visible_copy_buttons(frame)
            buttons = [item[0] for item in button_pairs]
            score = 0
            if buttons:
                score += 4
            if len(buttons) >= 2:
                score += 2
            if any(token in text for token in ("WXML", "WXSS", "微信小程序")):
                score += 3
            if code_like_re.search(text or ""):
                score += 2

            if score > best_score:
                best_score = score
                best_panel = {
                    "frame": frame,
                    "buttons": buttons,
                    "score": score,
                    "text": text or "",
                }

        if best_panel and best_panel["buttons"] and (
            len(best_panel["buttons"]) >= 2 or best_panel["score"] >= 7
        ):
            return best_panel

        if loop.time() >= deadline:
            return best_panel
        await asyncio.sleep(0.25)


async def capture(input_url: str, bootstrap: bool = False):
    # 判断输入：本地文件 or 蓝湖 URL
    if not input_url.startswith("http"):
        path = Path(input_url).expanduser()
        if path.exists():
            print_dependency_status("not_required", "local_input")
            print(f"SCREENSHOT:{path}")
            return
        print(f"ERROR: 文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    dep_status, dep_reason = ensure_runtime_dependencies(bootstrap=bootstrap)
    if dep_status != "ok":
        print_dependency_status(dep_status, dep_reason)
        print(f"ERROR: 蓝湖抓取环境检查失败: {dep_status}", file=sys.stderr)
        hint = _dependency_hint(dep_status, dep_reason)
        if hint:
            print(hint, file=sys.stderr)
        sys.exit(1)

    print_dependency_status("ok")

    # 提取 DDS URL
    dds_url = extract_dds_url(input_url)
    target_url = dds_url or input_url
    if dds_url:
        print(f"DDS URL: {dds_url[:80]}...", file=sys.stderr)
    else:
        print("WARNING: URL 未包含 ddsUrl/version_id，已回退到直接打开原始蓝湖页面", file=sys.stderr)

    cookies = get_cookies()
    print(f"读取到 {len(cookies)} 个 Chrome cookies", file=sys.stderr)
    user_token = next((c["value"] for c in cookies if c["name"] == "user_token"), None)
    if not user_token:
        print("ERROR: 未检测到蓝湖登录态，请先在本机 Chrome 中登录蓝湖后重试", file=sys.stderr)
        sys.exit(1)

    async_playwright = load_playwright()
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001
            if _is_browser_verification_blocked_error(exc):
                print_dependency_status("browser_verification_blocked", "chromium_dynamic_library_blocked")
                print("ERROR: macOS 已阻止 Playwright Chromium 组件运行", file=sys.stderr)
                sys.exit(1)
            raise
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cookies)

        # 在任何 JS 执行前注入：localStorage.token + clipboard 拦截
        # Fix: 使用 json.dumps 序列化 token，防止单引号等特殊字符破坏 JS 语法
        init_script = f"localStorage.setItem('token', {_json.dumps(user_token)});\n" if user_token else ""
        init_script += CLIPBOARD_INTERCEPT
        await ctx.add_init_script(init_script)

        image_responses: dict[str, dict] = {}
        response_tasks: list[asyncio.Task] = []

        async def cache_image_response(response):
            try:
                url = response.url
                content_type = response.headers.get("content-type", "")
                is_image = (
                    response.request.resource_type == "image"
                    or content_type.lower().startswith("image/")
                    or "alipic.lanhuapp.com" in url
                    or "SketchCover" in url
                )
                if not is_image or response.status != 200:
                    return
                body = await response.body()
                if body:
                    image_responses[url] = {
                        "body": body,
                        "content_type": content_type,
                    }
            except Exception:
                return

        def on_response(response):
            response_tasks.append(asyncio.create_task(cache_image_response(response)))

        page = await ctx.new_page()
        page.on("response", on_response)
        print("正在加载蓝湖页面...", file=sys.stderr)
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        run_dir = _create_run_dir()
        print(f"本次输出目录: {run_dir}", file=sys.stderr)

        screenshot_path = run_dir / "design.png"
        screenshot_meta_path = run_dir / "design.meta.json"
        wxml_tree_path = None
        wxml_path = None
        wxss_path = None
        spec_path = None
        screenshot_written = False
        wxml_tree_written = False
        wxml_written = False
        wxss_written = False
        spec_written = False
        screenshot_meta = {
            "captureMode": "page_screenshot",
            "imageUrl": "",
            "naturalWidth": 0,
            "naturalHeight": 0,
            "clientWidth": 0,
            "clientHeight": 0,
        }

        img_handle = None
        img_meta = {}
        try:
            img_handle, img_meta = await _find_preview_image(page, timeout_seconds=18.0)
            if img_handle:
                # 找到节点后，再给图片一点时间完成真实加载，避免 naturalWidth 仍为 0。
                for _ in range(20):
                    if img_meta.get("complete") and img_meta.get("naturalWidth", 0) > 0 and img_meta.get("naturalHeight", 0) > 0:
                        break
                    await asyncio.sleep(0.25)
                    try:
                        img_meta = await img_handle.evaluate(
                            """
                            img => ({
                                src: img.currentSrc || img.src || "",
                                naturalWidth: img.naturalWidth || 0,
                                naturalHeight: img.naturalHeight || 0,
                                clientWidth: img.clientWidth || 0,
                                clientHeight: img.clientHeight || 0,
                                complete: !!img.complete,
                                id: img.id || "",
                                className: img.className || "",
                                frameUrl: window.location.href
                            })
                            """
                        )
                    except Exception:
                        break
        except Exception:
            img_handle = None
            img_meta = {}

        screenshot_meta.update(
            {
                "imageUrl": img_meta.get("src", ""),
                "naturalWidth": img_meta.get("naturalWidth", 0),
                "naturalHeight": img_meta.get("naturalHeight", 0),
                "clientWidth": img_meta.get("clientWidth", 0),
                "clientHeight": img_meta.get("clientHeight", 0),
            }
        )

        image_url = img_meta.get("src", "")
        image_entry = await _wait_for_cached_image(image_url, image_responses, response_tasks)

        if image_entry and img_meta.get("naturalWidth", 0) > 0 and img_meta.get("naturalHeight", 0) > 0:
            suffix = _guess_image_suffix(image_entry.get("content_type", ""), image_url)
            screenshot_path = run_dir / f"design{suffix}"
            screenshot_path.write_bytes(image_entry["body"])
            screenshot_written = True
            screenshot_meta["captureMode"] = "raw_response"
            screenshot_meta["contentType"] = image_entry.get("content_type", "")
            print("设计图已按原始响应保存", file=sys.stderr)
        elif img_handle and image_url:
            await img_handle.screenshot(path=str(screenshot_path))
            screenshot_written = True
            screenshot_meta["captureMode"] = "element_screenshot"
            print("设计图已按页面树中的图片节点截图保存", file=sys.stderr)
        else:
            await page.screenshot(path=str(screenshot_path), full_page=False)
            screenshot_written = True
            print("WARNING: 未在页面树中定位到设计图图片节点，已回退到整页截图", file=sys.stderr)

        screenshot_meta_path.write_text(
            _json.dumps(screenshot_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        screenshot_status = "ok" if screenshot_written else "unavailable"
        source_status = "unavailable"
        source_reason = ""

        # 点击主源码面板中的前两个「复制代码」按钮（优先对应 WXML + WXSS）
        source_panel = await _find_source_panel(page, timeout_seconds=8.0)
        btns = source_panel["buttons"] if source_panel else []
        panel_score = source_panel["score"] if source_panel else 0
        print(f"主源码面板候选得分 {panel_score}，找到 {len(btns)} 个「复制代码」按钮", file=sys.stderr)
        page_text = await _collect_page_tree_text(page)
        login_markers = ("重新登录", "请登录", "登录后", "登录")
        if btns:
            for btn in btns[:2]:
                await btn.click()
                await asyncio.sleep(1.0)  # Fix: 给 clipboard write 足够时间，避免漏抓
        elif source_panel and panel_score > 0:
            source_status = "source_not_ready"
            source_reason = "source_panel_found_without_copy_button"
            print("WARNING: 已识别源码面板，但未找到可点击复制按钮，源码抓取已降级", file=sys.stderr)
        elif any(marker in page_text for marker in login_markers):
            source_status = "auth_failed"
            source_reason = "copy_button_not_found_with_login_prompt"
            print("WARNING: 未找到复制代码按钮，且页面存在登录提示，源码抓取已降级", file=sys.stderr)
        else:
            source_status = "source_not_ready"
            source_reason = "source_panel_not_found"
            print("WARNING: 未识别到源码面板，源码抓取已降级", file=sys.stderr)

        await asyncio.sleep(1)

        # 读取拦截到的 clipboard 数据
        clipboard_data: list[str] = await page.evaluate("window.__clipboardData || []")

        # 去重
        seen, unique = set(), []
        for text in clipboard_data:
            if text and text not in seen:
                seen.add(text)
                unique.append(text)

        # 按内容分类（Fix: 改用正则，不依赖特定类名或 rpx 单位）
        _wxml_re = re.compile(r"<(?:view|text|image|button|scroll-view|input|swiper|picker)\b")
        _wxss_re = re.compile(r"\.\w[\w\-]*\s*\{")
        wxml_text = next((t for t in unique if _wxml_re.search(t)), "")
        wxss_text = next((t for t in unique if _wxss_re.search(t) and not _wxml_re.search(t)), "")

        wxml_path = run_dir / "wxml.txt" if wxml_text else None
        wxss_path = run_dir / "wxss.txt" if wxss_text else None
        if wxml_path:
            wxml_path.write_text(wxml_text, encoding="utf-8")
            wxml_written = True
        if wxss_path:
            wxss_path.write_text(wxss_text, encoding="utf-8")
            wxss_written = True

        if wxml_text:
            print(f"WXML: {len(wxml_text)} 字符", file=sys.stderr)
        else:
            print("WARNING: 未获取到 WXML", file=sys.stderr)

        if wxss_text:
            print(f"WXSS: {len(wxss_text)} 字符", file=sys.stderr)
        else:
            print("WARNING: 未获取到 WXSS", file=sys.stderr)

        if wxml_text and wxss_text:
            source_status = "ok"
            source_reason = ""
        elif wxml_text or wxss_text:
            source_status = "partial"
            source_reason = "wxml_or_wxss_missing"
        elif not source_reason:
            source_status = "unavailable"
            source_reason = "no_source_detected"

        await browser.close()

    # 生成结构化 spec.json
    if wxml_written and wxml_path:
        try:
            styles = parse_wxss(wxss_path.read_text(encoding="utf-8")) if wxss_written and wxss_path else {}
            tree = parse_wxml(wxml_path.read_text(encoding="utf-8"), styles)
            wxml_tree_path = run_dir / "wxml_tree.json"
            wxml_tree_path.write_text(
                _json.dumps(tree, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            wxml_tree_written = True
        except Exception as e:
            print(f"WARNING: wxml_tree.json 生成失败: {e}", file=sys.stderr)
            wxml_tree_path = None

    spec_path = run_dir / "spec.json"
    if wxml_written and wxss_written and wxml_path and wxss_path:
        try:
            spec = generate_spec(wxml_path, wxss_path, spec_path)
            spec_written = True
            print(
                f"spec.json: {len(spec['colors'])} 个颜色 / {len(spec['tree'])} 个根节点",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"WARNING: spec.json 生成失败: {e}", file=sys.stderr)
            spec_path = None
    else:
        spec_path = None

    print(f"RUN_DIR:{run_dir}")
    print(f"SCREENSHOT:{screenshot_path}")
    print(f"SCREENSHOT_META:{screenshot_meta_path}")
    print(f"SCREENSHOT_STATUS:{screenshot_status}")
    print(f"SOURCE_STATUS:{source_status}")
    if source_reason:
        print(f"SOURCE_REASON:{source_reason}")
    if wxml_tree_written and wxml_tree_path:
        print(f"WXML_TREE:{wxml_tree_path}")
    if wxml_written and wxml_path:
        print(f"WXML:{wxml_path}")
    if wxss_written and wxss_path:
        print(f"WXSS:{wxss_path}")
    if spec_written and spec_path:
        print(f"SPEC:{spec_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取蓝湖设计图并生成结构化输出")
    parser.add_argument("target", nargs="?")
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="缺少 browser-cookie3 / playwright / chromium 时尝试自动安装",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not args.target:
        print("用法: python3 lanhu_capture.py [--bootstrap] '<蓝湖URL 或 本地截图路径>'", file=sys.stderr)
        sys.exit(1)
    asyncio.run(capture(args.target, bootstrap=args.bootstrap))
