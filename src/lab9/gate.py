"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)
    Also caught here: duplicated (item, seed) rows, a manifest that disagrees with the baseline's
    (items, seeds, eval set), and headline metrics that do not follow from the rows (hand-edited)."""
    problems: list[str] = []
    rows = pr.get("rows") or []
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. every headline number must be a finite number (NaN < min is False: a naive gate passes it)
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, bool) or (v is not None and not isinstance(v, (int, float))):
            problems.append(f"metric {k} is not a number: {v!r}")
        elif isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (NaN/inf)")

    # 2. coverage: one row per (item, seed), the same set the baseline graded
    seeds = man.get("seeds") or []
    want_n = (man.get("items") or 0) * len(seeds)
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest says {man.get('items')} items x {len(seeds)} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    seen: set = set()
    dups = sorted({k for k in keys if k in seen or seen.add(k)}, key=str)
    if dups:
        problems.append(f"duplicated (item, seed) rows: {dups[:5]}")
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != base_keys:
        miss, extra = sorted(base_keys - set(keys), key=str), sorted(set(keys) - base_keys, key=str)
        problems.append(f"(item, seed) set differs from the baseline: missing {miss[:5]}, extra {extra[:5]}")
    for field in ("items", "seeds", "eval_set", "eval_set_sha"):
        if field in bman and man.get(field) != bman.get(field):
            problems.append(f"manifest {field} {man.get(field)!r} != baseline {bman.get(field)!r}")
    if spec.get("seeds") and sorted(seeds) != sorted(spec["seeds"]):
        problems.append(f"manifest seeds {seeds} != spec seeds {spec['seeds']}")

    # 3. graders must have run on every row
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), e.g. {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for m in graded:
        bad = [f"{r.get('item_id')}@{r.get('seed')}" for r in rows if not isinstance(r.get(m), bool)]
        if bad:
            problems.append(f"metric {m}: {len(bad)} row(s) without a True/False grade, e.g. {bad[:3]}")

    # 4. slice tags are part of the eval set, not of the PR
    base_slices = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows") or []}
    moved = sorted({r.get("item_id") for r in rows if r.get("item_id") in base_slices
                    and sorted(r.get("slices") or []) != base_slices[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from the baseline for {moved[:5]}")

    # 5. the headline metrics must be what the rows say (checked once the rows are sound)
    if not problems and rows:
        ids = [m for m in graded if m in rows[0]]
        has_cost = all("cost" in r for r in rows)
        again = aggregate(rows if has_cost else [{**r, "cost": 0.0} for r in rows], ids,
                          k_values=spec.get("pass_k", []))
        if not has_cost:
            again.pop("cost_per_success", None)
        for k, v in (pr.get("metrics") or {}).items():
            if k in again and not _close(v, again[k]):
                problems.append(f"metric {k} = {v} but the rows give {again[k]} (hand-edited report?)")

    # 6. ratchet: on the same eval-set version thresholds may only get stricter
    if base_spec is not None:
        problems += ratchet(spec, base_spec)
    return problems


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= 1e-6


def ratchet(spec: dict, base_spec: dict) -> list[str]:
    """Problems where `spec` is looser than `base_spec` on the same eval-set version."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []   # a new eval-set version starts its own thresholds (and needs a new baseline)
    out: list[str] = []
    for f in ("eval_set", "labels", "seeds", "adversarial_pack"):
        if f in base_spec and spec.get(f) != base_spec.get(f):
            out.append(f"ratchet: {f} changed ({base_spec.get(f)!r} -> {spec.get(f)!r}) on the same eval-set version")
    bb, sb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if sb.get("confidence", 0.95) > bb.get("confidence", 0.95):
        out.append("ratchet: bootstrap confidence raised (a wider CI hides drops)")
    out += _ratchet_entries("metric", {m["id"]: m for m in base_spec.get("metrics") or []},
                            {m["id"]: m for m in spec.get("metrics") or []}, nested=True)
    out += _ratchet_entries("slice", {(x["name"], x.get("metric")): x for x in base_spec.get("slices") or []},
                            {(x["name"], x.get("metric")): x for x in spec.get("slices") or []}, nested=False)
    return out


def _ratchet_entries(kind: str, old: dict, new: dict, *, nested: bool) -> list[str]:
    out = []
    for key, o in old.items():
        n = new.get(key)
        name = key if isinstance(key, str) else "/".join(str(x) for x in key)
        if n is None:
            out.append(f"ratchet: {kind} {name} removed")
            continue
        ot = (o.get("threshold") or {}) if nested else o
        nt = (n.get("threshold") or {}) if nested else n
        if o.get("blocking") and not n.get("blocking"):
            out.append(f"ratchet: {kind} {name} no longer blocking")
        if "min" in ot and ("min" not in nt or nt["min"] < ot["min"]):
            out.append(f"ratchet: {kind} {name} min {ot['min']} -> {nt.get('min')}")
        for bound in ("max", "max_increase", "max_new_failures"):
            if bound in ot and (bound not in nt or nt[bound] > ot[bound]):
                out.append(f"ratchet: {kind} {name} {bound} {ot[bound]} -> {nt.get(bound)}")
        if ot.get("no_significant_drop") and not nt.get("no_significant_drop"):
            out.append(f"ratchet: {kind} {name} dropped no_significant_drop")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"                       # an empty slice cannot vouch for anything
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027), confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict = "missing"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def new_failures(pr: dict, base: dict, metric: str, *, safety: bool = False) -> list[str]:
    """(item, seed) rows that are good in the baseline and bad in the PR for `metric`."""
    bad = (lambda v: v is True) if safety else (lambda v: v is False)
    before = {(r.get("item_id"), r.get("seed")): r.get(metric) for r in base.get("rows") or []}
    return [f"{r.get('item_id')}@{r.get('seed')}" for r in pr.get("rows") or []
            if bad(r.get(metric)) and (r.get("item_id"), r.get("seed")) in before
            and not bad(before[(r.get("item_id"), r.get("seed"))])]


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if "max_new_failures" in th and val is not None:
            # Row-level flips: an (item, seed) the baseline got right and the PR gets wrong. Item means
            # cannot see a bug that moves a failure from one seed to another; on a deterministic agent
            # (A/A delta 0) every flip is real, so the floor comes from the A/A flip count.
            flips = new_failures(pr, base, mid, safety=m.get("kind") == "safety")
            note = (note + " " if note else "") + f"new fails {len(flips)}"
            if len(flips) > th["max_new_failures"]:
                verdict = "fail"
                note += f" e.g. {', '.join(flips[:3])}"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
