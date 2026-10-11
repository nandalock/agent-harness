"""Compare the real ToolScheduler at one worker and its default parallelism.

The tools simulate I/O with asyncio.sleep; this is not an LLM, network, Docker,
database, or production benchmark. Reuses the existing scheduler test fixtures.

Run from the repository root with Python 3.12 and backend import dependencies
installed in an isolated virtual environment. The measured environment used:
    python -m pip install mcp==1.30.0 aiohttp==3.14.5 psycopg2-binary==2.9.13
Then run:
    python docs/benchmarks/tool_scheduler_benchmark.py
"""
import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.tool_system.runtime.scheduler import (  # noqa: E402
    DEFAULT_MAX_PARALLEL_TOOLS,
    ToolScheduler,
)
from backend.tool_system.runtime.test_scheduler import (  # noqa: E402
    _ControlledRuntime,
    _FakeRecorder,
    _context_factory,
    _mode_resolver,
    _plan,
)


async def measure(calls: int, delay: float, parallel: bool) -> dict:
    plans = [_plan(f"io_{i}", f"call_{i}") for i in range(calls)]
    runtime = _ControlledRuntime({plan.tool_name: delay for plan in plans})
    recorder = _FakeRecorder()
    # Omit max_parallel_tools to exercise the actual production default.
    options = {} if parallel else {"max_parallel_tools": 1}
    scheduler = ToolScheduler(
        recorder=recorder, runtime=runtime, context_factory=_context_factory,
        mode_resolver=_mode_resolver(), **options,
    )
    started = time.perf_counter()
    outcomes = await scheduler.execute_tool_calls(plans)
    elapsed = time.perf_counter() - started
    expected = [plan.tool_call_id for plan in plans]
    assert [outcome.tool_call_id for outcome in outcomes] == expected
    assert [event[2] for event in recorder.events if event[0] == "result"] == expected
    assert all(outcome.result == {"ok": outcome.tool_name} for outcome in outcomes)
    limit = DEFAULT_MAX_PARALLEL_TOOLS if parallel else 1
    assert runtime.max_active == min(calls, limit)
    return {"seconds": round(elapsed, 6), "peak_active": runtime.max_active}


async def benchmark(args: argparse.Namespace) -> dict:
    samples = {"serial": [], "default_parallel": []}
    for _ in range(args.warmup):
        await measure(args.calls, args.delay, False)
        await measure(args.calls, args.delay, True)
    for round_number in range(args.rounds):
        # Alternate order to reduce systematic first/second-run bias.
        order = (False, True) if round_number % 2 == 0 else (True, False)
        for parallel in order:
            label = "default_parallel" if parallel else "serial"
            samples[label].append(await measure(args.calls, args.delay, parallel))
    serial = statistics.median(row["seconds"] for row in samples["serial"])
    parallel = statistics.median(row["seconds"] for row in samples["default_parallel"])
    scheduler_file = ROOT / "backend/tool_system/runtime/scheduler.py"
    return {
        "scope": "simulated I/O; real ToolScheduler; no LLM/network/DB/Docker work",
        "measured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "packages": {name: version(name) for name in ("mcp", "aiohttp", "psycopg2-binary")},
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            ).strip(),
            "scheduler_sha256": hashlib.sha256(scheduler_file.read_bytes()).hexdigest(),
        },
        "workload": {
            "calls_per_batch": args.calls, "simulated_io_seconds_per_call": args.delay,
            "measured_rounds_per_mode": args.rounds, "warmup_rounds_per_mode": args.warmup,
            "serial_workers": 1, "default_parallel_workers": DEFAULT_MAX_PARALLEL_TOOLS,
            "exclusive_tools": 0, "timer_excludes_fixture_setup": True,
        },
        "samples": samples,
        "summary": {
            "serial_median_seconds": round(serial, 6),
            "default_parallel_median_seconds": round(parallel, 6),
            "duration_reduction_percent": round((1 - parallel / serial) * 100, 3),
            "speedup": round(serial / parallel, 3),
            "result_order_and_concurrency_checks_passed": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=12)
    parser.add_argument("--delay", type=float, default=0.1)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_suffix(".json"))
    args = parser.parse_args()
    if args.calls < 1 or args.delay <= 0 or args.rounds < 1 or args.warmup < 0:
        parser.error("calls/rounds must be positive, delay > 0, warmup >= 0")
    result = asyncio.run(benchmark(args))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
