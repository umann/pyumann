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

import subprocess
import sys
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path

import yaml

from umann.utils.data_utils import get_multi, pop_multi, set_multi

COVERAGE_XML = Path("coverage.xml")
BASELINE_YAML = Path("coverage-baseline.yaml")
DECIMALS = 1


def round_it(value) -> float:
    """Round a float to a given number of decimal places, defaults to 1."""
    return None if value is None else round(value, DECIMALS)


def load_current_coverage():
    tree = ET.parse(COVERAGE_XML)
    root = tree.getroot()

    def get_rate():
        rate = root.get("line-rate")
        with suppress(TypeError, ValueError):
            return round_it(float(rate) * 100.0)

        # Fallback calculation
        rate = 0.0  # default
        with suppress(TypeError, ValueError, ZeroDivisionError):
            covered = float(root.get("lines-covered") or 0)
            valid = float(root.get("lines-valid") or 0)
            rate = covered / valid
        return round_it(rate * 100.0)

    current: dict = {"overall": get_rate(), "files": {}}
    for cls in root.findall(".//classes/class"):
        try:
            pct = round_it(float(cls.get("line-rate")) * 100)
            key = Path(cls.get("filename")).as_posix()
        except (ValueError, TypeError):
            continue
        current["files"][key] = pct
    return current


# def load_current_coverage(xml_path: Path) -> dict[str, float]:
#     """Parse coverage XML and return per-file coverage percentages (1 decimal)."""
#     tree = ET.parse(xml_path)
#     root = tree.getroot()


#     current: dict[str, float] = {}
#     for cls in root.findall(".//classes/class"):
#         try:
#             pct = round_it(float(cls.get("line-rate")) * 100)
#             key = Path(cls.get("filename")).as_posix()
#         except (ValueError, TypeError):
#             continue
#         current[key] = pct
#     return current


# def get_global_coverage(xml_path: Path | str = COVERAGE_XML, decimals: int = 1) -> float:
#     """Return the overall line coverage percentage from coverage.xml.

#     Reads the top-level metrics from a coverage.py Cobertura XML file and returns
#     the total line coverage as a percentage rounded to the requested precision.

#     Args:
#         xml_path: Path or string to the coverage XML file. Defaults to COVERAGE_XML.
#         decimals: Number of decimal places to round to. Defaults to 1.

#     Returns:
#         The overall line coverage percentage (e.g., 83.2 for 83.2%).

#     Notes:
#         Prefers the root attribute "line-rate" when available. Falls back to
#         computing from "lines-covered" and "lines-valid" if needed.
#     """
#     path = Path(xml_path)
#     tree = ET.parse(path)
#     root = tree.getroot()

#     rate = root.get("line-rate")
#     if rate is not None:
#         try:
#             return round_it(float(rate) * 100.0, decimals)
#         except (TypeError, ValueError):
#             pass

#     # Fallback calculation
#     try:
#         covered = float(root.get("lines-covered") or 0)
#         valid = float(root.get("lines-valid") or 0)
#         pct = (covered / valid * 100.0) if valid else 0.0
#         return round_it(pct, decimals)
#     except (TypeError, ValueError):
#         return round_it(0.0, decimals)


def is_git_tree_clean() -> bool:
    """Check if git working directory is clean (no uncommitted changes)."""
    # Do or do not, there is no try. Git must be there.
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False)
    return result.returncode == 0 and not result.stdout.strip()


def main() -> int:
    """Run coverage guard check."""
    current = load_current_coverage()

    # Load baseline or initialize empty if missing
    # Do or do not, there is no try. Restore from repo if you deleted it by accident.
    baseline = yaml.safe_load(BASELINE_YAML.read_text(encoding="utf-8")) or {}
    # Check for regressions
    errors: list[str] = []
    datapaths = [["overall"]] + [["files", fname] for fname in baseline.get("files", {}) | current.get("files", {})]
    any_change = False
    for datapath in datapaths:
        old_pct = round_it(get_multi(baseline, datapath, None))
        new_pct = round_it(get_multi(current, datapath, None))
        assert old_pct is not None or new_pct is not None, yaml.dump(
            dict(current=current, baseline=baseline, datapath=datapath)
        )
        if old_pct is None:
            set_multi(baseline, datapath, new_pct)
            any_change = True
            print(f"[INFO] added {datapath}")
            continue
        if new_pct is None:
            pop_multi(baseline, datapath)
            any_change = True
            print(f"[INFO] removed {datapath}")
            continue
        # Fail if coverage falls (beyond rounding tolerance)
        if new_pct + 1e-9 < old_pct:
            errors.append(f"  {datapath}: {old_pct}% -> {new_pct}% ({new_pct - old_pct:.1f}%)")
    if errors:
        print("\n".join(["Coverage decreased:"] + errors + [f"See {BASELINE_YAML}"]))
        return 1

    # No regressions: check if baseline changed
    if any_change:
        was_clean = is_git_tree_clean()
        BASELINE_YAML.write_text(yaml.dump(baseline, sort_keys=True), encoding="utf-8")
        print(f"[OK] Coverage baseline updated in {BASELINE_YAML} ({len(current['files'])=})")
        if was_clean:
            print("[WARNING] git tree became dirty with baseline update")
    else:
        print("[OK] Coverage: no changes")

    return 0


if __name__ == "__main__":
    sys.exit(main())
