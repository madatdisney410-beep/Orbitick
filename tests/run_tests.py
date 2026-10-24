"""Run every UI test suite against the source. Test windows appear on screen while they run.

Usage: python tests/run_tests.py
Screenshots and test data go to tests/out (ignored by git).
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
OUT = HERE / "out"
SUITES = ["stage1_test", "reset_test", "e2e3", "v14_test", "v15_test", "v16_test", "v17_test", "v18_test"]


def main():
    OUT.mkdir(exist_ok=True)
    failed = []
    for suite in SUITES:
        # A separate instance name so a running Orbitick is never poked by the tests.
        env = dict(os.environ, ORBITICK_INSTANCE=f"OrbitickTest_{suite}")
        result = subprocess.run([sys.executable, str(HERE / f"{suite}.py"), str(APP), str(OUT)], cwd=APP, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        lines = result.stdout.splitlines()
        summary = next((line for line in reversed(lines) if "checks passed" in line), "no summary")
        bad = [line for line in lines if line.startswith("FAIL")] + (["crashed:\n" + result.stderr[-2000:]]
                                                                     if result.returncode else [])
        print(f"{suite}: {summary}")
        for line in bad:
            print("   ", line)
        passed, _, total = summary.partition(" ")[0].partition("/")
        if bad or not total or passed != total or any(line.startswith("errors:") and line != "errors: 0"
                                                      for line in lines):
            failed.append(suite)
    print("All suites passed." if not failed else f"Failed: {', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
