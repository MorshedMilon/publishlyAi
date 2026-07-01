"""Generic worker: drain the `jobs` queue for one module, run it, write status back.

The Console (browser) enqueues `jobs` rows; a scheduled run invokes this dispatcher to drain
them. It is the control-plane contract from the PublishlyAI Console build (Session 0): poll →
claim → run → write-back, with **zero changes to any pipeline module**. Each target module
exposes `main(argv: list[str]) -> int` (the same entrypoint its `__main__` block calls), and the
job's `params.argv` is passed straight through.

Design notes:
- **Lazy resolve.** Only the one module a job needs is imported, at run time — so draining P26
  never imports WeasyPrint (P08/P09) or the LLM clients of unrelated modules.
- **Safe claim.** The claim is a guarded update (`… where id = ? and status = 'queued'`); if it
  returns no row, another worker won the race and we skip. Two workers can't run the same row.
- **Cancel.** If `cancel_requested` is set before we claim, the row ends `cancelled`, unrun.
- **Honest status.** `succeeded` only on exit code 0; any non-zero or exception → `failed` with
  the error in `result`. The Console never shows "done" until the worker writes it here.
- **Single drain pass**, then exit (schedule-friendly — no infinite loop). `module_map`/`client`
  are injectable so the acceptance test can drive a fake echo module against the real DB.

Run:  python -m pipeline.worker P26            # drain all queued P26 jobs, then exit
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Callable

from pipeline.lib import supabase_client

# module code ('P04'…'P26') -> dotted path of a module exposing main(argv)->int.
# Human-only / UI modules (P12 dashboard, P16 ledger — written on human confirm) are intentionally
# absent: the Console does not enqueue them. Extend as later screens wire up more stages.
MODULE_MAP: dict[str, str] = {
    "P04": "pipeline.ingest.research_ingest",
    "P05": "pipeline.mining.review_miner",
    "P06": "pipeline.validation.validation_gate",
    "P07": "pipeline.blueprint.blueprint",
    "P08": "pipeline.interior.interior_engine",
    "P09": "pipeline.cover.cover_engine",
    "P10": "pipeline.listing.listing_engine",
    "P11": "pipeline.safety.safety_qc",
    "P13": "pipeline.etsy_publisher.publisher",
    "P14": "pipeline.owned_publisher.publisher",
    "P15": "pipeline.kdp_package.packager",
    "P17": "pipeline.tracking.tracker",
    "P23": "pipeline.superiority.superiority_spec",
    "P24": "pipeline.refinement.refinement_engine",
    "P25": "pipeline.quality.quality_gate",
    "P26": "pipeline.portfolio_manager.manager",
}

# A module-map value may be a dotted path (resolved lazily) or a callable (injected in tests).
ModuleTarget = str | Callable[[list[str]], int | None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_main(target: ModuleTarget) -> Callable[[list[str]], int | None]:
    """Return the module's main() callable. Imports a dotted path lazily; passes a callable through."""
    if callable(target):
        return target
    mod = importlib.import_module(target)
    main = getattr(mod, "main", None)
    if not callable(main):
        raise AttributeError(f"module '{target}' has no callable main()")
    return main


def _argv_from_params(params: Any) -> list[str]:
    """Extract the CLI arg list from a job's params.argv (DATA-SCHEMA §6.6). Absent → []."""
    if not isinstance(params, dict):
        return []
    argv = params.get("argv", [])
    if argv is None:
        return []
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise ValueError("params.argv must be a list of strings")
    return argv


def _run_main(main: Callable[[list[str]], int | None], argv: list[str]) -> tuple[int, str]:
    """Call main(argv), capturing stdout as the run summary. None return is treated as exit 0."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(argv))
    return (0 if code is None else int(code)), buf.getvalue().strip()


def process_job(
    job: dict[str, Any],
    *,
    module_map: dict[str, ModuleTarget] = MODULE_MAP,
    client: Any = supabase_client,
) -> dict[str, Any]:
    """Claim and run one queued job row, writing status back. Returns a small outcome dict."""
    job_id = job["id"]

    # Honor a cancel requested before we claim — end the row 'cancelled', unrun.
    if job.get("cancel_requested"):
        client.update(
            "jobs",
            {"id": job_id, "status": "queued"},
            {"status": "cancelled", "finished_at": _now()},
        )
        return {"id": job_id, "status": "cancelled"}

    # Guarded claim: only succeeds if the row is still 'queued'.
    claimed = client.update(
        "jobs",
        {"id": job_id, "status": "queued"},
        {"status": "running", "started_at": _now()},
    )
    if not claimed:
        return {"id": job_id, "status": "skipped"}  # lost the race

    try:
        main = _resolve_main(module_map[job["module"]])
        argv = _argv_from_params(job.get("params"))
        exit_code, summary = _run_main(main, argv)
        status = "succeeded" if exit_code == 0 else "failed"
        result = {"exit_code": exit_code, "summary": summary, "error": None}
    except Exception as exc:  # any failure → 'failed', never a phantom success
        status = "failed"
        result = {"exit_code": None, "summary": None, "error": f"{exc}\n{traceback.format_exc()}"}

    client.update(
        "jobs",
        {"id": job_id},
        {"status": status, "finished_at": _now(), "result": result},
    )
    return {"id": job_id, "status": status, "result": result}


def drain(
    module_code: str,
    *,
    module_map: dict[str, ModuleTarget] = MODULE_MAP,
    client: Any = supabase_client,
) -> list[dict[str, Any]]:
    """Process every currently-queued job for one module (FIFO by requested_at), then return."""
    if module_code not in module_map:
        raise KeyError(f"unknown module '{module_code}' (not in MODULE_MAP)")
    queued = client.select("jobs", {"module": module_code, "status": "queued"})
    queued.sort(key=lambda r: r.get("requested_at") or "")
    return [process_job(job, module_map=module_map, client=client) for job in queued]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PublishlyAI job-queue worker (single drain pass)")
    parser.add_argument("module", help="module code to drain, e.g. P26")
    args = parser.parse_args(argv)

    module_code = args.module.upper()
    if module_code not in MODULE_MAP:
        print(f"unknown module '{module_code}'. known: {', '.join(sorted(MODULE_MAP))}", file=sys.stderr)
        return 2

    outcomes = drain(module_code)
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no queued jobs"
    print(f"{module_code}: {len(outcomes)} job(s) drained — {summary}")
    return 0


if __name__ == "__main__":
    from pathlib import Path

    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT))
    sys.exit(main())
