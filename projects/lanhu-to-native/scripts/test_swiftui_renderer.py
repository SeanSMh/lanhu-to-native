#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "swiftui_renderer.py"
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
    with tempfile.TemporaryDirectory(prefix="swiftui_renderer_basic_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--view-name",
            "LoginView",
        )
        swift_file = out / "LoginView.swift"
        assert_contains(swift_file, "struct LoginView: View")
        assert_contains(swift_file, "TextField(")
        assert_contains(swift_file, "Button {")
        assert_contains(out / "Localizable.strings", "login_view_text_1")


def test_lazy_vstack_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="swiftui_renderer_lazy_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "lazy_spec.json"),
            "--out",
            str(out),
            "--view-name",
            "LazyDemoView",
        )
        assert_contains(out / "LazyDemoView.swift", "LazyVStack(")


def test_mixed_advanced_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="swiftui_renderer_mixed_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "mixed_spec.json"),
            "--out",
            str(out),
            "--view-name",
            "MixedDemoView",
        )
        swift_file = out / "MixedDemoView.swift"
        assert_contains(swift_file, "TabView {")
        assert_contains(swift_file, "ZStack(alignment: .topLeading)")


def test_complex_style_and_scroll() -> None:
    with tempfile.TemporaryDirectory(prefix="swiftui_renderer_complex_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "complex_scroll_spec.json"),
            "--out",
            str(out),
            "--view-name",
            "ComplexStyleView",
        )
        swift_file = out / "ComplexStyleView.swift"
        assert_contains(swift_file, "ScrollView(.horizontal, showsIndicators: false)")
        assert_contains(swift_file, "LinearGradient(")
        assert_contains(swift_file, ".shadow(")
        assert_contains(swift_file, ".opacity(0.9)")
        assert_contains(swift_file, ".multilineTextAlignment(.center)")


def test_generated_write_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="swiftui_renderer_write_") as tmp:
        root = Path(tmp)
        project = root / "mock_ios_project"
        (project / "MockApp.xcodeproj").mkdir(parents=True)
        (project / "ExistingView.swift").write_text(
            "import SwiftUI\n\nstruct ExistingView: View {\n    var body: some View { Text(\"ok\") }\n}\n",
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--view-name",
            "LoginView",
            "--project-root",
            str(project),
            "--group-path",
            "Generated/UI",
            "--write-mode",
            "generated",
        )
        assert (project / "Generated" / "UI" / "LoginView.swift").exists()
        assert (project / "Generated" / "UI" / "Resources" / "Localizable.strings").exists()
        assert (project / "Generated" / "UI" / "Resources" / "ColorAssets.txt").exists()


def test_replace_block_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="swiftui_renderer_replace_") as tmp:
        root = Path(tmp)
        project = root / "mock_ios_project"
        (project / "MockApp.xcodeproj").mkdir(parents=True)
        (project / "ExistingView.swift").write_text(
            "import SwiftUI\n\nstruct ExistingView: View {\n    var body: some View { Text(\"ok\") }\n}\n",
            encoding="utf-8",
        )
        target = project / "HostView.swift"
        target.write_text(
            "import SwiftUI\n\n"
            "struct HostView: View {\n"
            "    var body: some View {\n"
            "        VStack {\n"
            "            // BEGIN AUTO-GENERATED LANHU UI\n"
            "            old body\n"
            "            // END AUTO-GENERATED LANHU UI\n"
            "        }\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--view-name",
            "LoginView",
            "--project-root",
            str(project),
            "--target-file",
            str(target),
            "--write-mode",
            "replace-block",
        )
        content = target.read_text(encoding="utf-8")
        if "old body" in content:
            raise AssertionError("replace-block did not replace old SwiftUI content")
        if "struct LoginView: View" not in content:
            raise AssertionError("replace-block did not inject generated SwiftUI code")


def main() -> int:
    tests = [
        test_basic_render,
        test_lazy_vstack_detection,
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
