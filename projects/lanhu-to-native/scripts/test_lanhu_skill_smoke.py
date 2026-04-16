#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

TEST_SCRIPTS = [
    "test_lanhu_capture.py",
    "test_compose_renderer.py",
    "test_xml_renderer.py",
    "test_swiftui_renderer.py",
    "test_flutter_renderer.py",
    "test_objc_renderer.py",
]


def run_test(script_name: str) -> tuple[bool, str]:
    script_path = ROOT / script_name
    if not script_path.exists():
        return False, f"missing script: {script_path}"
    result = subprocess.run(
        [sys.executable, str(script_path)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stdout.strip() or result.stderr.strip() or f"exit={result.returncode}"
        return False, detail
    return True, result.stdout.strip() or "ok"


def main() -> int:
    failures: list[str] = []
    for script_name in TEST_SCRIPTS:
        ok, detail = run_test(script_name)
        if ok:
            print(f"PASS {script_name}")
        else:
            failures.append(f"{script_name}: {detail}")
            print(f"FAIL {script_name}: {detail}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("ALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
