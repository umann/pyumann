"""Coverage guard: compare per-file coverage against a stored baseline.

Usage:
  python tests/utils/coverage_guard.py

Behavior:
  - Parses coverage.xml for per-file line-rate (rounded to 1 decimal)
  - Loads coverage-baseline.yaml
  - If any file's coverage falls: fails with exit 1
  - If coverage stays same or improves: auto-writes new baseline
  - Warns if baseline updated and git tree was clean (helps catch accidental updates)
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

COVERAGE_XML = Path("coverage.xml")
BASELINE_YAML = Path("coverage-baseline.yaml")


def round_it(value: float, decimals: int = 1) -> float:
    """Round a float to a given number of decimal places, defaults to 1."""
    return round(value, decimals)


def load_current_coverage(xml_path: Path) -> dict[str, float]:
    """Parse coverage XML and return per-file coverage percentages (1 decimal)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    current: dict[str, float] = {}
    for cls in root.findall(".//classes/class"):
        try:
            pct = round_it(float(cls.get("line-rate")) * 100)
            key = Path(cls.get("filename")).as_posix()
        except (ValueError, TypeError):
            continue
        current[key] = pct
    return current


def is_git_tree_clean() -> bool:
    """Check if git working directory is clean (no uncommitted changes)."""
    # Do or do not, there is no try. Git must be there.
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False)
    return result.returncode == 0 and not result.stdout.strip()


def main() -> int:
    """Run coverage guard check."""
    current = load_current_coverage(COVERAGE_XML)

    # Load baseline or initialize empty if missing
    # Do or do not, there is no try. Restore from repo if you deleted it by accident.
    baseline = yaml.safe_load(BASELINE_YAML.read_text(encoding="utf-8")) or {}

    # Check for regressions
    errors: list[str] = []
    for fname, old_pct in baseline.items():
        old_pct = round_it(old_pct)
        try:
            new_pct = round_it(current[fname])
        except KeyError:  # File missing from current report (deleted or filtered)
            continue
        # Fail if coverage falls (beyond rounding tolerance)
        if new_pct + 1e-9 < old_pct:
            errors.append(f"  {fname}: {old_pct}% -> {new_pct}% ({new_pct - old_pct}%)")

    if errors:
        print("\n".join(["Coverage regression detected:"] + errors))
        return 1

    # No regressions: check if baseline changed
    if current != baseline:
        was_clean = is_git_tree_clean()
        BASELINE_YAML.write_text(yaml.dump(current, sort_keys=True), encoding="utf-8")
        print(f"[OK] Coverage baseline updated in {BASELINE_YAML} ({len(current)} files)")
        if was_clean:
            print("[WARNING] git tree became dirty with baseline update")
    else:
        print("[OK] Coverage: no changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
