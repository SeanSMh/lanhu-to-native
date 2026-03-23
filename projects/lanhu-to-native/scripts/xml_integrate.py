from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class IntegrationResult:
    layout_path: Path | None = None
    values_paths: list[Path] | None = None
    drawable_paths: list[Path] | None = None
    extra_layout_paths: list[Path] | None = None
    mode: str = "none"


def find_android_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for base in [current, *current.parents]:
        if (
            (base / "settings.gradle").exists()
            or (base / "settings.gradle.kts").exists()
            or (base / "gradle" / "libs.versions.toml").exists()
        ):
            return base
    return None


def detect_android_xml_project(project_root: Path) -> bool:
    res_layout = list(project_root.rglob("res/layout/*.xml"))
    if res_layout:
        return True
    for gradle_file in [
        project_root / "build.gradle",
        project_root / "build.gradle.kts",
        project_root / "app" / "build.gradle",
        project_root / "app" / "build.gradle.kts",
    ]:
        if gradle_file.exists():
            text = gradle_file.read_text(encoding="utf-8", errors="ignore")
            if "setContentView" in text or "viewBinding" in text or "dataBinding" in text:
                return True
    return False


def write_generated_files(
    project_root: Path,
    module_name: str | None,
    layout_name: str,
    layout_xml: str,
    values_files: dict[str, str],
    drawable_files: dict[str, str],
    extra_layouts: dict[str, str],
) -> IntegrationResult:
    module_root = project_root / module_name if module_name else project_root / "app"
    res_root = module_root / "src" / "main" / "res"
    layout_dir = res_root / "layout"
    values_dir = res_root / "values"
    drawable_dir = res_root / "drawable"
    layout_dir.mkdir(parents=True, exist_ok=True)
    values_dir.mkdir(parents=True, exist_ok=True)
    drawable_dir.mkdir(parents=True, exist_ok=True)
    layout_path = layout_dir / f"{layout_name}.xml"
    layout_path.write_text(layout_xml, encoding="utf-8")
    values_paths: list[Path] = []
    for file_name, content in values_files.items():
        path = values_dir / file_name
        path.write_text(content, encoding="utf-8")
        values_paths.append(path)
    drawable_paths: list[Path] = []
    for file_name, content in drawable_files.items():
        path = drawable_dir / file_name
        path.write_text(content, encoding="utf-8")
        drawable_paths.append(path)
    extra_layout_paths: list[Path] = []
    for file_name, content in extra_layouts.items():
        path = layout_dir / file_name
        path.write_text(content, encoding="utf-8")
        extra_layout_paths.append(path)
    return IntegrationResult(
        layout_path=layout_path,
        values_paths=values_paths,
        drawable_paths=drawable_paths,
        extra_layout_paths=extra_layout_paths,
        mode="generated",
    )


def replace_marked_block(target_file: Path, replacement: str) -> IntegrationResult:
    content = target_file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?s)<!-- BEGIN AUTO-GENERATED LANHU UI -->.*?<!-- END AUTO-GENERATED LANHU UI -->"
    )
    updated, count = pattern.subn(
        f"<!-- BEGIN AUTO-GENERATED LANHU UI -->\n{replacement.rstrip()}\n<!-- END AUTO-GENERATED LANHU UI -->",
        content,
        count=1,
    )
    if count == 0:
        raise ValueError("目标文件中未找到 XML 自动生成标记区块")
    target_file.write_text(updated, encoding="utf-8")
    return IntegrationResult(layout_path=target_file, mode="replace_block")
