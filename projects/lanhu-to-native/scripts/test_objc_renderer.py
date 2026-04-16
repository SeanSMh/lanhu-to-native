#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "objc_renderer.py"
TESTDATA = ROOT / "testdata"


def run_renderer(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RENDERER), *args],
        text=True,
        capture_output=True,
        check=True,
    )


def assert_contains(path: Path, expected: str) -> None:
    content = path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"{path.name} missing: {expected!r}")


def test_basic_render() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_basic_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
        )
        assert_contains(out / "LoginView.h", "@interface LoginView : UIView")
        assert_contains(out / "LoginView.m", "mas_makeConstraints")
        assert_contains(out / "LoginView.m", "// BEGIN AUTO-GENERATED LANHU UI")
        assert_contains(out / "LoginView.m", "// END AUTO-GENERATED LANHU UI")
        assert_contains(out / "LoginViewController.h", "@interface LoginViewController : UIViewController")
        assert_contains(out / "LoginViewController.m", "viewDidLoad")
        assert_contains(out / "LoginViewController.m", "LoginView")
        assert_contains(out / "LHColors.h", "UIColorFromRGB")
        assert_contains(out / "LHColors.h", "LHColor_white")
        assert_contains(out / "LHStrings.h", "LHStr_")
        assert (out / "icon_placeholders.md").exists()


def test_view_h_properties() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_props_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
        )
        h_content = (out / "LoginView.h").read_text(encoding="utf-8")
        assert "@property (nonatomic, strong)" in h_content
        assert "UILabel" in h_content or "UITextField" in h_content or "UIButton" in h_content


def test_strings_coverage() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_strings_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
        )
        strings_content = (out / "LHStrings.h").read_text(encoding="utf-8")
        # basic_spec has texts: "登录", "请输入手机号", "继续"
        for text in ("登录", "请输入手机号", "继续"):
            if text not in strings_content:
                raise AssertionError(f"LHStrings.h missing text: {text!r}")


def test_colors_count() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_colors_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
        )
        import json
        spec = json.loads((TESTDATA / "basic_spec.json").read_text())
        colors_content = (out / "LHColors.h").read_text(encoding="utf-8")
        define_count = colors_content.count("#define LHColor_")
        assert define_count == len(spec["colors"]), (
            f"Expected {len(spec['colors'])} color defines, got {define_count}"
        )


def test_fallback_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_fallback_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
            "--mode", "fallback",
        )
        view_m = (out / "LoginView.m").read_text(encoding="utf-8")
        assert "低精度模式" in view_m, "Missing low-precision warning"
        assert "估算值" in view_m, "Missing 估算值 annotation"


def test_stdout_contract() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_stdout_") as tmp:
        out = Path(tmp) / "out"
        result = run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
        )
        stdout = result.stdout
        for marker in ("SPEC_SOURCE:", "VIEW_H:", "VIEW_M:", "CONTROLLER_H:", "CONTROLLER_M:",
                        "COLORS:", "STRINGS:", "ICONS:", "SUMMARY:"):
            if marker not in stdout:
                raise AssertionError(f"stdout missing marker: {marker!r}")


def test_generated_write_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_write_") as tmp:
        root = Path(tmp)
        project = root / "mock_project"
        (project / "SomeFeature").mkdir(parents=True)
        # Plant an ObjC signal so detect_objc_project passes
        vc = project / "SomeFeature" / "SomeViewController.m"
        vc.write_text("#import <UIKit/UIKit.h>\n@implementation SomeViewController\n@end\n")
        out = root / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
            "--project-root", str(project),
            "--write-mode", "generated",
        )
        generated = project / "Generated"
        assert (generated / "LoginView.h").exists(), "LoginView.h not written"
        assert (generated / "LoginView.m").exists(), "LoginView.m not written"
        assert (generated / "LoginViewController.h").exists(), "LoginViewController.h not written"
        assert (generated / "LoginViewController.m").exists(), "LoginViewController.m not written"


def test_replace_view_block() -> None:
    with tempfile.TemporaryDirectory(prefix="objc_renderer_replace_") as tmp:
        root = Path(tmp)
        target = root / "LoginView.m"
        target.write_text(
            '#import "LoginView.h"\n'
            '#import <Masonry/Masonry.h>\n'
            "\n"
            "@implementation LoginView\n"
            "\n"
            "- (instancetype)initWithFrame:(CGRect)frame {\n"
            "    self = [super initWithFrame:frame];\n"
            "    if (self) { [self initSubviews]; }\n"
            "    return self;\n"
            "}\n"
            "\n"
            "// BEGIN AUTO-GENERATED LANHU UI\n"
            "- (void)initSubviews {\n"
            "    // old content\n"
            "}\n"
            "// END AUTO-GENERATED LANHU UI\n"
            "\n"
            "@end\n",
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec", str(TESTDATA / "basic_spec.json"),
            "--out", str(out),
            "--view-name", "LoginView",
            "--project-root", str(root),
            "--target-file", str(target),
            "--write-mode", "replace-view-block",
        )
        content = target.read_text(encoding="utf-8")
        assert "old content" not in content, "Old content was not replaced"
        assert "mas_makeConstraints" in content, "New constraints not injected"
        assert "// BEGIN AUTO-GENERATED LANHU UI" in content
        assert "// END AUTO-GENERATED LANHU UI" in content


def main() -> int:
    tests = [
        test_basic_render,
        test_view_h_properties,
        test_strings_coverage,
        test_colors_count,
        test_fallback_mode,
        test_stdout_contract,
        test_generated_write_mode,
        test_replace_view_block,
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
