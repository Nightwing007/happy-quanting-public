"""Run backend tests quietly: failures and one summary line, nothing else.

    python scripts/qtest.py                  # whole suite (in parallel: pytest-xdist, -n auto)
    python scripts/qtest.py engine sim       # groups (see GROUPS)
    python scripts/qtest.py test_fees -k gst # files or any extra pytest args

Keeps agent sessions cheap: a passing run prints one line instead of ~70.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# Keep in sync with the test-group table in docs/ARCHITECTURE.md.
GROUPS = {
    "engine": "test_engine test_costs_engine test_costs_api test_fees test_shorting test_protection "
    "test_payouts test_trading_api test_context",
    "market": "test_market_data test_market_api test_history test_market_hours test_metrics test_indicators",
    "sim": "test_sim test_sim_strategies",
    "algos": "test_algos test_backtest test_validate test_sandbox",
    "auth": "test_auth test_scoping",
    "db": "test_migrations",
    "marketplace": "test_marketplace test_subscriptions test_seed test_listing_versions",
    "health": "test_health",
}


def expand(args: list[str]) -> list[str]:
    out: list[str] = []
    for arg in args:
        names = GROUPS.get(arg, arg).split() if not arg.startswith("-") else [arg]
        for name in names:
            out.append(f"tests/{name}.py" if name.startswith("test_") and not name.endswith(".py") else name)
    return out


def main() -> int:
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:warnings", "--tb=line", "-rfE"]
    if not sys.argv[1:]:
        # Only the full run is parallel: targeted runs stay serial so their output stays simple.
        cmd += ["-n", "auto"]
    proc = subprocess.run(cmd + expand(sys.argv[1:]), cwd=BACKEND, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    lines = proc.stdout.splitlines() + proc.stderr.splitlines()
    # Drop the progress dots ("....F..  [ 42%]") and blank lines; keep failures and the summary.
    noise = set(".FEsxX")
    keep = [
        ln for ln in lines
        if ln.strip() and "bringing up nodes" not in ln and not set(ln.split("[")[0].strip()) <= noise
        # xdist workers print library deprecation warnings on stderr despite -p no:warnings.
        and "DeprecationWarning" not in ln and "from starlette.testclient" not in ln
    ]  # fmt: skip
    print("\n".join(keep[-60:]))
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
