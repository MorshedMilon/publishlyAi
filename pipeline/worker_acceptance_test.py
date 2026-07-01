"""Job-queue worker — acceptance test (Console Session 0).

Proves the control-plane loop the whole Console depends on:
  hand-insert a `queued` job  →  the worker claims it  →  runs the module  →  flips it to
  `succeeded` (or `failed`), writing started_at / finished_at / result back.

Structure (house pattern, P17/P26):
  PART 1 — pure logic (no DB, no network): params.argv mapping, main() resolution, MODULE_MAP
           integrity, and the claim / cancel / success / failure state machine driven against a
           tiny in-memory fake client (so no real module is imported).
  PART 2 — the real loop against live Supabase, with an INJECTED echo module (module_map is
           injectable) so the queue round-trip is proven without running a heavy pipeline stage.

Run:  python -m pipeline.worker_acceptance_test
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import worker  # noqa: E402
from pipeline.lib import supabase_client  # noqa: E402

JOBS = "jobs"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _FakeClient:
    """In-memory stand-in for supabase_client with the same (table, match, values) semantics."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows: list[dict] = [dict(r) for r in (rows or [])]

    @staticmethod
    def _match(row: dict, match: dict) -> bool:
        return all(row.get(k) == v for k, v in match.items())

    def select(self, table, match=None):
        return [dict(r) for r in self.rows if not match or self._match(r, match)]

    def update(self, table, match, values):
        hit = [r for r in self.rows if self._match(r, match)]
        for r in hit:
            r.update(values)
        return [dict(r) for r in hit]

    def insert(self, table, row):
        self.rows.append(dict(row))
        return [dict(row)]

    def delete(self, table, match):
        removed = [dict(r) for r in self.rows if self._match(r, match)]
        self.rows[:] = [r for r in self.rows if not self._match(r, match)]
        return removed


def _echo_main_factory(calls: list, *, exit_code: int = 0, raises: bool = False):
    def _echo_main(argv):
        calls.append(list(argv))
        if raises:
            raise RuntimeError("boom")
        print(f"echo ran with argv={argv}")
        return exit_code
    return _echo_main


# ---------------------------------------------------------------------------
# PART 1 — pure logic
# ---------------------------------------------------------------------------

def part1_pure() -> None:
    # --- params.argv mapping (DATA-SCHEMA §6.6) ---
    assert worker._argv_from_params({}) == []
    assert worker._argv_from_params(None) == []
    assert worker._argv_from_params({"argv": ["--limit", "5"]}) == ["--limit", "5"]
    assert worker._argv_from_params({"argv": None}) == []
    for bad in ({"argv": "not-a-list"}, {"argv": [1, 2]}):
        try:
            worker._argv_from_params(bad)
            assert False, f"expected ValueError for {bad}"
        except ValueError:
            pass
    print("[P1.1] params.argv -> argv: {} -> []; list passes through; bad shapes rejected.")

    # --- main() resolution: callable passthrough + import branch error ---
    sentinel = lambda argv: 0  # noqa: E731
    assert worker._resolve_main(sentinel) is sentinel
    try:
        worker._resolve_main("json")  # importable, but has no main() -> AttributeError
        assert False, "expected AttributeError for a module without main()"
    except AttributeError:
        pass
    print("[P1.2] _resolve_main: passes a callable through; raises when a module lacks main().")

    # --- MODULE_MAP integrity (no imports — just shape) ---
    for code, dotted in worker.MODULE_MAP.items():
        assert re.fullmatch(r"P\d\d", code), f"bad module code {code!r}"
        assert isinstance(dotted, str) and dotted.startswith("pipeline.") and dotted.count(".") >= 2, dotted
    assert {"P17", "P26"} <= worker.MODULE_MAP.keys(), "scheduled modules P17/P26 must be mapped"
    # Human-only / UI modules are never enqueued by the Console.
    assert "P12" not in worker.MODULE_MAP and "P16" not in worker.MODULE_MAP, \
        "P12 (dashboard) and P16 (ledger, human-confirm) must not be worker-dispatchable"
    print("[P1.3] MODULE_MAP: all keys P##, values dotted pipeline paths; P17/P26 in, P12/P16 out.")

    # --- state machine on a fake client: success / failure / exception / cancel / race ---
    calls: list = []
    ok = _FakeClient([{"id": "j-ok", "module": "PTEST", "status": "queued",
                       "cancel_requested": False, "params": {"argv": ["--limit", "2"]}}])
    out = worker.process_job(ok.rows[0], module_map={"PTEST": _echo_main_factory(calls)}, client=ok)
    row = ok.select(JOBS, {"id": "j-ok"})[0]
    assert out["status"] == "succeeded" and row["status"] == "succeeded", row
    assert row["started_at"] and row["finished_at"], "started_at/finished_at must be written"
    assert row["result"]["exit_code"] == 0 and "echo ran" in row["result"]["summary"], row["result"]
    assert calls == [["--limit", "2"]], "module must receive params.argv verbatim"
    print("[P1.4] queued -> running -> succeeded; started/finished/result written; argv forwarded.")

    fail = _FakeClient([{"id": "j-fail", "module": "PTEST", "status": "queued", "cancel_requested": False, "params": {}}])
    worker.process_job(fail.rows[0], module_map={"PTEST": _echo_main_factory([], exit_code=1)}, client=fail)
    r = fail.select(JOBS, {"id": "j-fail"})[0]
    assert r["status"] == "failed" and r["result"]["exit_code"] == 1, r

    exc = _FakeClient([{"id": "j-exc", "module": "PTEST", "status": "queued", "cancel_requested": False, "params": {}}])
    worker.process_job(exc.rows[0], module_map={"PTEST": _echo_main_factory([], raises=True)}, client=exc)
    r = exc.select(JOBS, {"id": "j-exc"})[0]
    assert r["status"] == "failed" and "boom" in (r["result"]["error"] or ""), r
    print("[P1.5] non-zero exit -> failed; an exception -> failed with the error in result (no phantom success).")

    cancelled_calls: list = []
    canc = _FakeClient([{"id": "j-cancel", "module": "PTEST", "status": "queued", "cancel_requested": True, "params": {}}])
    out = worker.process_job(canc.rows[0], module_map={"PTEST": _echo_main_factory(cancelled_calls)}, client=canc)
    r = canc.select(JOBS, {"id": "j-cancel"})[0]
    assert out["status"] == "cancelled" and r["status"] == "cancelled", r
    assert cancelled_calls == [], "a cancel_requested job must NOT run the module"
    print("[P1.6] cancel_requested before claim -> cancelled, module never invoked.")

    race_calls: list = []
    race = _FakeClient([{"id": "j-race", "module": "PTEST", "status": "running", "cancel_requested": False, "params": {}}])
    out = worker.process_job(race.rows[0], module_map={"PTEST": _echo_main_factory(race_calls)}, client=race)
    assert out["status"] == "skipped" and race_calls == [], "a row already claimed must be skipped, not re-run"
    print("[P1.7] guarded claim: a row not still 'queued' is skipped (no double-run).")


# ---------------------------------------------------------------------------
# PART 2 — the real loop against live Supabase (injected echo module)
# ---------------------------------------------------------------------------

def part2_live() -> None:
    calls: list = []
    module_map = {"PTEST": _echo_main_factory(calls)}
    ids: list[str] = []
    try:
        job = supabase_client.insert(JOBS, {
            "module": "PTEST", "status": "queued", "requested_by": "acceptance-test",
            "params": {"argv": ["--dry-run"]},
        })[0]
        ids.append(job["id"])
        assert job["status"] == "queued" and job["started_at"] is None, job

        outcomes = worker.drain("PTEST", module_map=module_map, client=supabase_client)
        assert any(o["id"] == job["id"] and o["status"] == "succeeded" for o in outcomes), outcomes

        row = supabase_client.select(JOBS, {"id": job["id"]})[0]
        assert row["status"] == "succeeded", row
        assert row["started_at"] and row["finished_at"], "worker must write started_at + finished_at"
        assert row["result"]["exit_code"] == 0 and "echo ran" in row["result"]["summary"], row["result"]
        assert calls == [["--dry-run"]], "the module must have received params.argv"
        print("[P2.1] real jobs row queued -> worker drained it -> succeeded, result written back.")

        # cancel path, live
        cancelled = supabase_client.insert(JOBS, {
            "module": "PTEST", "status": "queued", "cancel_requested": True,
            "requested_by": "acceptance-test", "params": {},
        })[0]
        ids.append(cancelled["id"])
        before = len(calls)
        worker.drain("PTEST", module_map=module_map, client=supabase_client)
        crow = supabase_client.select(JOBS, {"id": cancelled["id"]})[0]
        assert crow["status"] == "cancelled", crow
        assert len(calls) == before, "cancelled job must not have invoked the module"
        print("[P2.2] a cancel_requested row drains to 'cancelled', module never invoked.")

        print("\nWORKER ACCEPTANCE TEST PASSED.")
    finally:
        for jid in ids:
            supabase_client.delete(JOBS, {"id": jid})
        print("[teardown] removed test jobs rows.")


def main() -> int:
    print("=== PART 1: pure logic (no DB / no network) ===")
    part1_pure()
    print("\n=== PART 2: the real loop against live Supabase (injected echo module) ===")
    part2_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
