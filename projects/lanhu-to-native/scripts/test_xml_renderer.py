#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "xml_renderer.py"
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
    with tempfile.TemporaryDirectory(prefix="xml_renderer_basic_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "login_page",
        )
        assert_contains(out / "login_page.xml", "<LinearLayout")
        assert_contains(out / "login_page.xml", "<EditText")
        assert_contains(out / "strings.xml", "login_page_text_1")
        assert_contains(out / "colors.xml", "<color name=\"blue\">#0080FF</color>")


def test_recycler_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="xml_renderer_recycler_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "lazy_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "lazy_page",
        )
        assert_contains(out / "lazy_page.xml", "androidx.recyclerview.widget.RecyclerView")
        sample_layout = out / "extra_layouts" / "lazy_page_item_sample.xml"
        if not sample_layout.exists():
            raise AssertionError("RecyclerView sample layout was not generated")


def test_mixed_advanced_detection() -> None:
    with tempfile.TemporaryDirectory(prefix="xml_renderer_mixed_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "mixed_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "mixed_page",
        )
        layout = out / "mixed_page.xml"
        assert_contains(layout, "com.google.android.material.tabs.TabLayout")
        assert_contains(layout, "androidx.viewpager2.widget.ViewPager2")
        assert_contains(layout, "androidx.constraintlayout.widget.ConstraintLayout")


def test_complex_style_and_scroll() -> None:
    with tempfile.TemporaryDirectory(prefix="xml_renderer_complex_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "complex_scroll_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "complex_page",
        )
        layout = out / "complex_page.xml"
        assert_contains(layout, "<HorizontalScrollView")
        assert_contains(layout, "android:alpha=\"0.9\"")
        assert_contains(layout, "android:elevation=")
        drawable = next((out / "drawable").glob("*.xml"))
        assert_contains(drawable, "<gradient")


def test_generated_write_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="xml_renderer_write_") as tmp:
        root = Path(tmp)
        project = root / "mock_project"
        (project / "app" / "src" / "main" / "res" / "layout").mkdir(parents=True)
        (project / "settings.gradle.kts").write_text(
            'rootProject.name = "mock"\ninclude(":app")\n', encoding="utf-8"
        )
        (project / "app" / "build.gradle.kts").write_text(
            "android { buildFeatures { viewBinding = true } }\n", encoding="utf-8"
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "login_page",
            "--project-root",
            str(project),
            "--write-mode",
            "generated",
        )
        if not (project / "app" / "src" / "main" / "res" / "layout" / "login_page.xml").exists():
            raise AssertionError("generated write mode did not write layout file")


def test_replace_block_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="xml_renderer_replace_") as tmp:
        root = Path(tmp)
        project = root / "mock_project"
        (project / "app" / "src" / "main" / "res" / "layout").mkdir(parents=True)
        (project / "settings.gradle.kts").write_text(
            'rootProject.name = "mock"\ninclude(":app")\n', encoding="utf-8"
        )
        (project / "app" / "build.gradle.kts").write_text(
            "android { buildFeatures { viewBinding = true } }\n", encoding="utf-8"
        )
        target = project / "app" / "src" / "main" / "res" / "layout" / "host.xml"
        target.write_text(
            "<LinearLayout>\n"
            "<!-- BEGIN AUTO-GENERATED LANHU UI -->\n"
            "old block\n"
            "<!-- END AUTO-GENERATED LANHU UI -->\n"
            "</LinearLayout>\n",
            encoding="utf-8",
        )
        out = root / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "basic_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "login_page",
            "--project-root",
            str(project),
            "--target-file",
            str(target),
            "--write-mode",
            "replace-block",
        )
        content = target.read_text(encoding="utf-8")
        if "old block" in content:
            raise AssertionError("replace-block did not replace old XML content")
        if "<EditText" not in content:
            raise AssertionError("replace-block did not inject generated XML")


def test_root_height_match_parent() -> None:
    """Root layout height must be match_parent, not the design canvas pixel value."""
    with tempfile.TemporaryDirectory(prefix="xml_renderer_root_height_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "status_bar_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "management_page",
        )
        content = (out / "management_page.xml").read_text(encoding="utf-8")
        if 'android:layout_height="match_parent"' not in content.split("\n")[1:10]:
            # Check the first element has match_parent height
            root_lines = content[:500]
            if "640" in root_lines:
                raise AssertionError("Root layout used canvas pixel height instead of match_parent")
            if 'android:layout_height="match_parent"' not in root_lines:
                raise AssertionError("Root layout did not get match_parent height")


def test_status_bar_mock_filtered() -> None:
    """Status bar mock nodes (containing HH:MM time text) must be excluded from output."""
    with tempfile.TemporaryDirectory(prefix="xml_renderer_statusbar_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "status_bar_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "management_page",
        )
        content = (out / "management_page.xml").read_text(encoding="utf-8")
        strings = (out / "strings.xml").read_text(encoding="utf-8")
        if "14:01" in strings:
            raise AssertionError("Status bar time text leaked into strings.xml")
        if "Management" not in strings:
            raise AssertionError("Real toolbar title missing from strings.xml after status bar filtering")


def test_recycler_all_strings_collected() -> None:
    """All item strings from RecyclerView children must appear in strings.xml."""
    with tempfile.TemporaryDirectory(prefix="xml_renderer_recycler_strings_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "lazy_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "lazy_page",
        )
        strings_content = (out / "strings.xml").read_text(encoding="utf-8")
        for expected in ("A", "B", "C"):
            if f">{expected}<" not in strings_content:
                raise AssertionError(f"RecyclerView child string '{expected}' missing from strings.xml")


def test_semantic_view_ids() -> None:
    """Generated view IDs should use semantic prefixes (tv_, rv_, iv_, etc.)."""
    with tempfile.TemporaryDirectory(prefix="xml_renderer_semids_") as tmp:
        out = Path(tmp) / "out"
        run_renderer(
            "--spec",
            str(TESTDATA / "lazy_spec.json"),
            "--out",
            str(out),
            "--layout-name",
            "lazy_page",
        )
        content = (out / "lazy_page.xml").read_text(encoding="utf-8")
        if 'android:id="@+id/lazy_page_rv_' not in content:
            raise AssertionError("RecyclerView did not get rv_ semantic ID prefix")


def main() -> int:
    tests = [
        test_basic_render,
        test_recycler_detection,
        test_mixed_advanced_detection,
        test_complex_style_and_scroll,
        test_generated_write_mode,
        test_replace_block_mode,
        test_root_height_match_parent,
        test_status_bar_mock_filtered,
        test_recycler_all_strings_collected,
        test_semantic_view_ids,
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
