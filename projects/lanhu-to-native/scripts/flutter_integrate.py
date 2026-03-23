from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass
class IntegrationResult:
    dart_path: Path | None = None
    colors_path: Path | None = None
    strings_path: Path | None = None
    mode: str = "none"


def find_flutter_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for base in [current, *current.parents]:
        if (base / "pubspec.yaml").exists():
            return base
    return None


def detect_flutter_project(project_root: Path) -> bool:
    pubspec = project_root / "pubspec.yaml"
    if pubspec.exists():
        try:
            text = pubspec.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if "flutter:" in text:
            return True
    return (project_root / "lib").exists()


def write_generated_files(
    project_root: Path,
    group_path: str | None,
    page_file_name: str,
    dart_code: str,
    colors_content: str,
    strings_content: str,
) -> IntegrationResult:
    target_root = project_root / group_path if group_path else project_root / "lib" / "generated"
    target_root.mkdir(parents=True, exist_ok=True)
    dart_path = target_root / page_file_name
    colors_path = target_root / "app_colors.dart"
    strings_path = target_root / "app_strings.dart"
    dart_path.write_text(dart_code, encoding="utf-8")
    colors_path.write_text(colors_content, encoding="utf-8")
    strings_path.write_text(strings_content, encoding="utf-8")
    return IntegrationResult(
        dart_path=dart_path,
        colors_path=colors_path,
        strings_path=strings_path,
        mode="generated",
    )


def replace_marked_block(target_file: Path, dart_body: str) -> IntegrationResult:
    content = target_file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?sm)^(?P<indent>[ \t]*)// BEGIN AUTO-GENERATED LANHU UI\n.*?\n(?P=indent)// END AUTO-GENERATED LANHU UI"
    )

    def repl(match: re.Match[str]) -> str:
        indent = match.group("indent")
        indented_body = "\n".join(
            f"{indent}{line}" if line else ""
            for line in dart_body.rstrip().splitlines()
        )
        return (
            f"{indent}// BEGIN AUTO-GENERATED LANHU UI\n"
            f"{indented_body}\n"
            f"{indent}// END AUTO-GENERATED LANHU UI"
        )

    updated, count = pattern.subn(repl, content, count=1)
    if count == 0:
        raise ValueError("目标文件中未找到 Flutter 自动生成标记区块")
    target_file.write_text(updated, encoding="utf-8")
    return IntegrationResult(dart_path=target_file, mode="replace_block")
