from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class IntegrationResult:
    kotlin_path: Path | None = None
    colors_path: Path | None = None
    strings_path: Path | None = None
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


def detect_compose_project(project_root: Path) -> bool:
    candidates = [
        project_root / "build.gradle",
        project_root / "build.gradle.kts",
        project_root / "app" / "build.gradle",
        project_root / "app" / "build.gradle.kts",
        project_root / "gradle" / "libs.versions.toml",
    ]
    markers = [
        "buildFeatures.compose = true",
        "compose true",
        "androidx.compose",
        "compose-bom",
        "material3",
        "@Composable",
    ]
    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8", errors="ignore")
            if any(marker in content for marker in markers):
                return True
    for source in project_root.rglob("*.kt"):
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@Composable" in text:
            return True
    return False


def resolve_java_src_root(project_root: Path, module_name: str | None = None) -> Path:
    module_root = project_root / module_name if module_name else project_root / "app"
    src_root = module_root / "src" / "main" / "java"
    src_root.mkdir(parents=True, exist_ok=True)
    return src_root


def package_to_dir(src_root: Path, package_name: str) -> Path:
    target = src_root
    for part in package_name.split("."):
        target /= part
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_generated_files(
    project_root: Path,
    module_name: str | None,
    package_name: str,
    screen_name: str,
    kotlin: str,
    colors_xml: str,
    strings_xml: str,
) -> IntegrationResult:
    src_root = resolve_java_src_root(project_root, module_name)
    kotlin_dir = package_to_dir(src_root, package_name)
    module_root = project_root / module_name if module_name else project_root / "app"
    res_values = module_root / "src" / "main" / "res" / "values"
    res_values.mkdir(parents=True, exist_ok=True)
    kotlin_path = kotlin_dir / f"{screen_name}.kt"
    colors_path = res_values / "colors_lanhu_generated.xml"
    strings_path = res_values / "strings_lanhu_generated.xml"
    kotlin_path.write_text(kotlin, encoding="utf-8")
    colors_path.write_text(colors_xml, encoding="utf-8")
    strings_path.write_text(strings_xml, encoding="utf-8")
    return IntegrationResult(
        kotlin_path=kotlin_path,
        colors_path=colors_path,
        strings_path=strings_path,
        mode="generated",
    )


def replace_marked_block(target_file: Path, kotlin_body: str) -> IntegrationResult:
    content = target_file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?s)// BEGIN AUTO-GENERATED LANHU UI\n.*?\n// END AUTO-GENERATED LANHU UI"
    )
    replacement = (
        "// BEGIN AUTO-GENERATED LANHU UI\n"
        f"{kotlin_body.rstrip()}\n"
        "// END AUTO-GENERATED LANHU UI"
    )
    updated, count = pattern.subn(replacement, content, count=1)
    if count == 0:
        raise ValueError("目标文件中未找到自动生成标记区块")
    target_file.write_text(updated, encoding="utf-8")
    return IntegrationResult(kotlin_path=target_file, mode="replace_block")
