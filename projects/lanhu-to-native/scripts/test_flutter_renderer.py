#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "flutter_renderer.py"
TESTDATA = ROOT / "compose_testdata"
if not TESTDATA.exists():
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
        raise AssertionError(f"{path} missing expected text: {expected}")


def test_basic_render() -> None:
    with tempfile.TemporaryDirectory(prefix="flutter_renderer_basic_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--page-name",
            "LoginPage",
        )
        dart_file = out / "login_page.dart"
        assert_contains(dart_file, "class LoginPage extends StatelessWidget")
        assert_contains(dart_file, "TextField(")
        assert_contains(dart_file, "ElevatedButton(")
        assert_contains(out / "app_strings.dart", "loginPageText1")


def test_list_view_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="flutter_renderer_list_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "lazy_spec.json"),
            "--out",
            str(out),
            "--page-name",
            "LazyDemoPage",
        )
        assert_contains(out / "lazy_demo_page.dart", "ListView.builder(")


def test_mixed_advanced_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="flutter_renderer_mixed_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "mixed_spec.json"),
            "--out",
            str(out),
            "--page-name",
            "MixedDemoPage",
        )
        dart_file = out / "mixed_demo_page.dart"
        assert_contains(dart_file, "TabBar(")
        assert_contains(dart_file, "PageView(")
        assert_contains(dart_file, "Stack(")


def test_complex_style_and_scroll() -> None:
    with tempfile.TemporaryDirectory(prefix="flutter_renderer_complex_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "complex_scroll_spec.json"),
            "--out",
            str(out),
            "--page-name",
            "ComplexStylePage",
        )
        dart_file = out / "complex_style_page.dart"
        assert_contains(dart_file, "SingleChildScrollView(")
        assert_contains(dart_file, "scrollDirection: Axis.horizontal")
        assert_contains(dart_file, "LinearGradient(")
        assert_contains(dart_file, "BoxShadow(")
        assert_contains(dart_file, "opacity: 0.9")
        assert_contains(dart_file, "TextAlign.center")


def test_generated_write_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="flutter_renderer_write_") as tmp:
        root = Path(tmp)
        project = root / "mock_flutter_project"
        (project / "lib").mkdir(parents=True)
        (project / "pubspec.yaml").write_text("name: mock\nflutter:\n  uses-material-design: true\n", encoding="utf-8")
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--page-name",
            "LoginPage",
            "--project-root",
            str(project),
            "--group-path",
            "lib/generated/ui",
            "--write-mode",
            "generated",
        )
        assert (project / "lib" / "generated" / "ui" / "login_page.dart").exists()
        assert (project / "lib" / "generated" / "ui" / "app_colors.dart").exists()
        assert (project / "lib" / "generated" / "ui" / "app_strings.dart").exists()


def test_replace_block_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="flutter_renderer_replace_") as tmp:
        root = Path(tmp)
        project = root / "mock_flutter_project"
        (project / "lib").mkdir(parents=True)
        (project / "pubspec.yaml").write_text("name: mock\nflutter:\n  uses-material-design: true\n", encoding="utf-8")
        target = project / "lib" / "host_page.dart"
        target.write_text(
            "import 'package:flutter/material.dart';\n\n"
            "class HostPage extends StatelessWidget {\n"
            "  const HostPage({super.key});\n\n"
            "  @override\n"
            "  Widget build(BuildContext context) {\n"
            "    return Column(\n"
            "      children: [\n"
            "        // BEGIN AUTO-GENERATED LANHU UI\n"
            "        old body\n"
            "        // END AUTO-GENERATED LANHU UI\n"
            "      ],\n"
            "    );\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--page-name",
            "LoginPage",
            "--project-root",
            str(project),
            "--target-file",
            str(target),
            "--write-mode",
            "replace-block",
        )
        content = target.read_text(encoding="utf-8")
        if "old body" in content:
            raise AssertionError("replace-block did not replace old Flutter content")
        if "class LoginPage extends StatelessWidget" not in content:
            raise AssertionError("replace-block did not inject generated Flutter code")


def main() -> int:
    tests = [
        test_basic_render,
        test_list_view_detection,
        test_mixed_advanced_detection,
        test_complex_style_and_scroll,
        test_generated_write_mode,
        test_replace_block_mode,
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
