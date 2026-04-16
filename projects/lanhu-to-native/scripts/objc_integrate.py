from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IntegrationResult:
    view_h_path: Path | None = None
    view_m_path: Path | None = None
    controller_h_path: Path | None = None
    controller_m_path: Path | None = None
    colors_path: Path | None = None
    strings_path: Path | None = None
    mode: str = "none"


def find_xcode_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for base in [current, *current.parents]:
        if any(base.glob("*.xcodeproj")) or any(base.glob("*.xcworkspace")):
            return base
        if (base / "Package.swift").exists():
            return base
    return None


def detect_objc_project(project_root: Path) -> bool:
    for source in project_root.rglob("*.m"):
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "#import" in text and "UIKit" in text:
            return True
    return False


def write_generated_files(
    project_root: Path,
    group_path: str | None,
    view_name: str,
    view_h: str,
    view_m: str,
    controller_h: str,
    controller_m: str,
    colors_content: str,
    strings_content: str,
) -> IntegrationResult:
    target_root = project_root / group_path if group_path else project_root / "Generated"
    target_root.mkdir(parents=True, exist_ok=True)
    controller_name = (
        view_name[:-4] + "ViewController" if view_name.endswith("View") else f"{view_name}ViewController"
    )
    view_h_path = target_root / f"{view_name}.h"
    view_m_path = target_root / f"{view_name}.m"
    controller_h_path = target_root / f"{controller_name}.h"
    controller_m_path = target_root / f"{controller_name}.m"
    colors_path = target_root / "LHColors.h"
    strings_path = target_root / "LHStrings.h"
    view_h_path.write_text(view_h, encoding="utf-8")
    view_m_path.write_text(view_m, encoding="utf-8")
    controller_h_path.write_text(controller_h, encoding="utf-8")
    controller_m_path.write_text(controller_m, encoding="utf-8")
    colors_path.write_text(colors_content, encoding="utf-8")
    strings_path.write_text(strings_content, encoding="utf-8")
    return IntegrationResult(
        view_h_path=view_h_path,
        view_m_path=view_m_path,
        controller_h_path=controller_h_path,
        controller_m_path=controller_m_path,
        colors_path=colors_path,
        strings_path=strings_path,
        mode="generated",
    )


def replace_view_block(target_file: Path, new_method: str) -> IntegrationResult:
    """Replace // BEGIN AUTO-GENERATED LANHU UI ... // END AUTO-GENERATED LANHU UI in a *View.m file."""
    content = target_file.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?sm)^(?P<indent>[ \t]*)// BEGIN AUTO-GENERATED LANHU UI\n.*?\n(?P=indent)// END AUTO-GENERATED LANHU UI"
    )

    def repl(match: re.Match[str]) -> str:
        ind = match.group("indent")
        indented = "\n".join(
            f"{ind}{line}" if line else ""
            for line in new_method.rstrip().splitlines()
        )
        return (
            f"{ind}// BEGIN AUTO-GENERATED LANHU UI\n"
            f"{indented}\n"
            f"{ind}// END AUTO-GENERATED LANHU UI"
        )

    updated, count = pattern.subn(repl, content, count=1)
    if count == 0:
        raise ValueError("目标文件中未找到 ObjC 自动生成标记区块")
    target_file.write_text(updated, encoding="utf-8")
    return IntegrationResult(view_m_path=target_file, mode="replace_view_block")
