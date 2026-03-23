from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class IntegrationResult:
    swift_path: Path | None = None
    strings_path: Path | None = None
    colors_path: Path | None = None
    mode: str = "none"


def find_xcode_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for base in [current, *current.parents]:
        if any(base.glob("*.xcodeproj")) or any(base.glob("*.xcworkspace")):
            return base
        if (base / "Package.swift").exists():
            return base
    return None


def detect_swiftui_project(project_root: Path) -> bool:
    for source in project_root.rglob("*.swift"):
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "import SwiftUI" in text or "struct " in text and "View {" in text:
            return True
    return False


def write_generated_files(
    project_root: Path,
    group_path: str | None,
    view_name: str,
    swift_code: str,
    strings_content: str,
    colors_content: str,
) -> IntegrationResult:
    target_root = project_root / group_path if group_path else project_root / "Generated"
    target_root.mkdir(parents=True, exist_ok=True)
    resources_dir = target_root / "Resources"
    resources_dir.mkdir(parents=True, exist_ok=True)
    swift_path = target_root / f"{view_name}.swift"
    strings_path = resources_dir / "Localizable.strings"
    colors_path = resources_dir / "ColorAssets.txt"
    swift_path.write_text(swift_code, encoding="utf-8")
    strings_path.write_text(strings_content, encoding="utf-8")
    colors_path.write_text(colors_content, encoding="utf-8")
    return IntegrationResult(
        swift_path=swift_path,
        strings_path=strings_path,
        colors_path=colors_path,
        mode="generated",
    )


def replace_marked_block(target_file: Path, swift_body: str) -> IntegrationResult:
    content = target_file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?sm)^(?P<indent>[ \t]*)// BEGIN AUTO-GENERATED LANHU UI\n.*?\n(?P=indent)// END AUTO-GENERATED LANHU UI"
    )

    def repl(match: re.Match[str]) -> str:
        indent = match.group("indent")
        indented_body = "\n".join(
            f"{indent}{line}" if line else ""
            for line in swift_body.rstrip().splitlines()
        )
        return (
            f"{indent}// BEGIN AUTO-GENERATED LANHU UI\n"
            f"{indented_body}\n"
            f"{indent}// END AUTO-GENERATED LANHU UI"
        )

    updated, count = pattern.subn(repl, content, count=1)
    if count == 0:
        raise ValueError("目标文件中未找到 SwiftUI 自动生成标记区块")
    target_file.write_text(updated, encoding="utf-8")
    return IntegrationResult(swift_path=target_file, mode="replace_block")
