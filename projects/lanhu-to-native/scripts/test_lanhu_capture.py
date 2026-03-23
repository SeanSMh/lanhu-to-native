#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "lanhu_capture.py"
TESTDATA = ROOT / "compose_testdata"
if not TESTDATA.exists():
    TESTDATA = ROOT / "testdata"

sys.path.insert(0, str(ROOT))
import lanhu_capture  # noqa: E402


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=True,
    )


def assert_contains(text: str, expected: str) -> None:
    if expected not in text:
        raise AssertionError(f"missing expected text: {expected}")


def test_local_input_machine_readable_output() -> None:
    result = run_script(str(TESTDATA / "basic_spec.json"))
    assert_contains(result.stdout, "DEPENDENCY_STATUS:not_required")
    assert_contains(result.stdout, "DEPENDENCY_ACTION:continue")
    assert_contains(result.stdout, "DEPENDENCY_HINT:当前输入为本地文件，不需要 Playwright 或蓝湖登录态")
    assert_contains(result.stdout, "DEPENDENCY_BOOTSTRAP_ALLOWED:false")
    assert_contains(result.stdout, f"SCREENSHOT:{TESTDATA / 'basic_spec.json'}")


def test_dependency_action_mapping() -> None:
    if lanhu_capture._dependency_action("ok") != "continue":
        raise AssertionError("ok should map to continue")
    if lanhu_capture._dependency_action("missing_python_pkg") != "install_dependency":
        raise AssertionError("missing_python_pkg should map to install_dependency")
    if lanhu_capture._dependency_action("browser_verification_blocked") != "allow_macos_binary":
        raise AssertionError("browser_verification_blocked should map to allow_macos_binary")
    if lanhu_capture._dependency_action("cookie_permission_denied") != "grant_macos_permission":
        raise AssertionError("cookie_permission_denied should map to grant_macos_permission")
    if lanhu_capture._dependency_action("cookie_unavailable") != "check_chrome_access":
        raise AssertionError("cookie_unavailable should map to check_chrome_access")
    if lanhu_capture._dependency_action("auth_cookie_missing") != "login_lanhu":
        raise AssertionError("auth_cookie_missing should map to login_lanhu")


def test_bootstrap_allowed_mapping() -> None:
    if lanhu_capture._dependency_bootstrap_allowed("missing_python_pkg") != "true":
        raise AssertionError("missing_python_pkg should allow bootstrap")
    if lanhu_capture._dependency_bootstrap_allowed("missing_browser") != "true":
        raise AssertionError("missing_browser should allow bootstrap")
    if lanhu_capture._dependency_bootstrap_allowed("auth_cookie_missing") != "false":
        raise AssertionError("auth_cookie_missing should not allow bootstrap")


def test_missing_python_package_status() -> None:
    with (
        mock.patch.object(lanhu_capture, "_missing_python_packages", return_value=["playwright"]),
        mock.patch.object(lanhu_capture, "_chromium_installed", return_value=True),
    ):
        status, reason = lanhu_capture.ensure_runtime_dependencies(bootstrap=False)
    if status != "missing_python_pkg" or reason != "playwright":
        raise AssertionError(f"unexpected result: {status} {reason}")


def test_missing_browser_status() -> None:
    with (
        mock.patch.object(lanhu_capture, "_missing_python_packages", return_value=[]),
        mock.patch.object(lanhu_capture, "_chromium_installed", return_value=False),
    ):
        status, reason = lanhu_capture.ensure_runtime_dependencies(bootstrap=False)
    if status != "missing_browser" or reason != "chromium_not_installed":
        raise AssertionError(f"unexpected result: {status} {reason}")


def test_auth_cookie_missing_status() -> None:
    with (
        mock.patch.object(lanhu_capture, "_missing_python_packages", return_value=[]),
        mock.patch.object(lanhu_capture, "_chromium_installed", return_value=True),
        mock.patch.object(lanhu_capture, "get_cookies", return_value=[]),
    ):
        status, reason = lanhu_capture.ensure_runtime_dependencies(bootstrap=False)
    if status != "auth_cookie_missing" or reason != "user_token_not_found":
        raise AssertionError(f"unexpected result: {status} {reason}")


def test_cookie_permission_denied_status() -> None:
    with (
        mock.patch.object(lanhu_capture, "_missing_python_packages", return_value=[]),
        mock.patch.object(lanhu_capture, "_chromium_installed", return_value=True),
        mock.patch.object(lanhu_capture, "get_cookies", side_effect=PermissionError("Operation not permitted")),
    ):
        status, reason = lanhu_capture.ensure_runtime_dependencies(bootstrap=False)
    if status != "cookie_permission_denied" or reason != "PermissionError":
        raise AssertionError(f"unexpected result: {status} {reason}")


def test_cookie_permission_hint() -> None:
    hint = lanhu_capture._dependency_hint("cookie_permission_denied")
    if "完全磁盘访问权限" not in hint:
        raise AssertionError("permission hint should mention 完全磁盘访问权限")
    if "重新打开当前宿主应用" not in hint:
        raise AssertionError("permission hint should mention restart host app")


def test_browser_verification_blocked_hint() -> None:
    hint = lanhu_capture._dependency_hint("browser_verification_blocked")
    if "Playwright 下载的 Chromium 组件" not in hint:
        raise AssertionError("browser verification hint should mention Chromium component")
    if "libvk_swiftshader.dylib" not in hint:
        raise AssertionError("browser verification hint should mention libvk_swiftshader.dylib")
    if "系统设置 -> 隐私与安全性" not in hint:
        raise AssertionError("browser verification hint should mention 隐私与安全性")


def test_browser_verification_error_detection() -> None:
    error = RuntimeError("libvk_swiftshader.dylib cannot be opened because the developer cannot be verified")
    if not lanhu_capture._is_browser_verification_blocked_error(error):
        raise AssertionError("should detect browser verification block")


def test_ok_status() -> None:
    cookies = [{"name": "user_token", "value": "token"}]
    with (
        mock.patch.object(lanhu_capture, "_missing_python_packages", return_value=[]),
        mock.patch.object(lanhu_capture, "_chromium_installed", return_value=True),
        mock.patch.object(lanhu_capture, "get_cookies", return_value=cookies),
    ):
        status, reason = lanhu_capture.ensure_runtime_dependencies(bootstrap=False)
    if status != "ok" or reason != "":
        raise AssertionError(f"unexpected result: {status} {reason}")


def main() -> int:
    tests = [
        test_local_input_machine_readable_output,
        test_dependency_action_mapping,
        test_bootstrap_allowed_mapping,
        test_missing_python_package_status,
        test_missing_browser_status,
        test_auth_cookie_missing_status,
        test_cookie_permission_denied_status,
        test_cookie_permission_hint,
        test_browser_verification_blocked_hint,
        test_browser_verification_error_detection,
        test_ok_status,
    ]
    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL {test.__name__}: {exc}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
