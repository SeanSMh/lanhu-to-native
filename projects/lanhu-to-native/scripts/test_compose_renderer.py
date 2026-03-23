#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "compose_renderer.py"
TESTDATA = ROOT / "compose_testdata"
if not TESTDATA.exists():
    TESTDATA = ROOT / "testdata"


def run_renderer(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(RENDERER), *args]
    return subprocess.run(cmd, text=True, capture_output=True, check=True)


def assert_contains(path: Path, expected: str) -> None:
    content = path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"{path} missing expected text: {expected}")


def test_basic_render() -> None:
    with tempfile.TemporaryDirectory(prefix="compose_renderer_basic_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--screen-name",
            "LoginScreen",
        )
        kt = out / "LoginScreen.kt"
        assert_contains(kt, "OutlinedTextField(")
        assert_contains(kt, "Button(")
        assert_contains(kt, "stringResource(id = R.string.login_screen_text_1)")


def test_lazy_column_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="compose_renderer_lazy_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "lazy_spec.json"),
            "--out",
            str(out),
            "--screen-name",
            "LazyDemoScreen",
        )
        assert_contains(out / "LazyDemoScreen.kt", "LazyColumn(")


def test_mixed_advanced_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="compose_renderer_mixed_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "mixed_spec.json"),
            "--out",
            str(out),
            "--screen-name",
            "MixedDemoScreen",
        )
        kt = out / "MixedDemoScreen.kt"
        assert_contains(kt, "TabRow(")
        assert_contains(kt, "HorizontalPager(")
        assert_contains(kt, "ConstraintLayout(")


def test_complex_style_and_scroll() -> None:
    with tempfile.TemporaryDirectory(prefix="compose_renderer_complex_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "complex_scroll_spec.json"),
            "--out",
            str(out),
            "--screen-name",
            "ComplexStyleScreen",
        )
        kt = out / "ComplexStyleScreen.kt"
        assert_contains(kt, "horizontalScroll(rememberScrollState())")
        assert_contains(kt, "Brush.linearGradient")
        assert_contains(kt, ".shadow(")
        assert_contains(kt, ".alpha(0.9f)")
        assert_contains(kt, "FontWeight.Bold")
        assert_contains(kt, "TextAlign.Center")


def test_generated_write_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="compose_renderer_write_") as tmp:
        root = Path(tmp)
        project = root / "mock_project"
        (project / "app" / "src" / "main" / "res" / "values").mkdir(parents=True)
        (project / "settings.gradle.kts").write_text(
            'rootProject.name = "mock"\ninclude(":app")\n', encoding="utf-8"
        )
        (project / "app" / "build.gradle.kts").write_text(
            'android { buildFeatures { compose = true } }\n'
            'dependencies { implementation("androidx.compose.ui:ui:1.7.0") }\n',
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--screen-name",
            "LoginScreen",
            "--package-name",
            "com.example.generated",
            "--project-root",
            str(project),
            "--write-mode",
            "generated",
        )
        assert (project / "app" / "src" / "main" / "java" / "com" / "example" / "generated" / "LoginScreen.kt").exists()
        assert (project / "app" / "src" / "main" / "res" / "values" / "colors_lanhu_generated.xml").exists()
        assert (project / "app" / "src" / "main" / "res" / "values" / "strings_lanhu_generated.xml").exists()


def test_replace_block_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="compose_renderer_replace_") as tmp:
        root = Path(tmp)
        project = root / "mock_project"
        (project / "app").mkdir(parents=True)
        (project / "settings.gradle.kts").write_text(
            'rootProject.name = "mock"\ninclude(":app")\n', encoding="utf-8"
        )
        (project / "app" / "build.gradle.kts").write_text(
            'android { buildFeatures { compose = true } }\n'
            'dependencies { implementation("androidx.compose.ui:ui:1.7.0") }\n',
            encoding="utf-8",
        )
        target = project / "app" / "LoginHost.kt"
        target.write_text(
            "package com.example\n\n"
            "// BEGIN AUTO-GENERATED LANHU UI\n"
            "old body\n"
            "// END AUTO-GENERATED LANHU UI\n",
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--screen-name",
            "LoginScreen",
            "--package-name",
            "com.example.generated",
            "--project-root",
            str(project),
            "--target-file",
            str(target),
            "--write-mode",
            "replace-block",
        )
        content = target.read_text(encoding="utf-8")
        if "old body" in content:
            raise AssertionError("replace-block did not replace old content")
        if "fun LoginScreen()" not in content:
            raise AssertionError("replace-block did not inject generated content")


def main() -> int:
    if not RENDERER.exists():
        raise FileNotFoundError(f"missing renderer: {RENDERER}")
    tests = [
        test_basic_render,
        test_lazy_column_detection,
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
