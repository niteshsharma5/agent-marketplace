#!/usr/bin/env python3
"""Before/after false-positive diff for a fix cycle.

Uses the prior blind-adjudication verdicts (evaluation/blackbox/adjudication.json) as
labels, and compares them to the CURRENT auditor output (evaluation/blackbox/findings/,
regenerate first with run_eval.py). Matching is per (site, category):
  - a category previously judged false_positive that no longer appears  -> FP FIXED
  - a category previously judged false_positive that still appears      -> FP remaining
  - a category previously judged true_positive that no longer appears   -> REGRESSION
  - a category not seen before that now appears                         -> NEW (review)

Run: python3 evaluation/blackbox/run_eval.py && python3 evaluation/blackbox/fp_diff.py
"""
import json
import os
import sys

BB = os.path.dirname(os.path.abspath(__file__))


def _norm(site):
    # adjudication 'site' fields are sometimes descriptive; match on the folder token.
    return site.split(" ")[0].split("/")[-1].strip().lower()


def main():
    adj_path = os.path.join(BB, "adjudication.json")
    if not os.path.isfile(adj_path):
        print("no adjudication.json — run the adjudication workflow first"); return 1
    adj = json.load(open(adj_path, encoding="utf-8"))

    site_files = {f[:-5]: os.path.join(BB, "findings", f)
                  for f in os.listdir(os.path.join(BB, "findings")) if f.endswith(".json")}

    fixed = remaining = regress = new = 0
    for r in adj:
        key = _norm(r.get("site", ""))
        match = next((n for n in site_files if _norm(n) == key or n.lower().startswith(key)), None)
        if not match:
            continue
        cur = {f["category"] for f in json.load(open(site_files[match], encoding="utf-8"))["findings"]}
        old_fp = {v["category"] for v in r.get("verdicts", []) if v.get("verdict") == "false_positive"}
        old_tp = {v["category"] for v in r.get("verdicts", []) if v.get("verdict") == "true_positive"}
        old_all = {v["category"] for v in r.get("verdicts", [])}
        f_fixed = old_fp - cur
        f_remain = old_fp & cur
        f_regress = old_tp - cur
        f_new = cur - old_all
        fixed += len(f_fixed); remaining += len(f_remain); regress += len(f_regress); new += len(f_new)
        line = f"{match:<24} fixed={len(f_fixed)} remaining={len(f_remain)} regressions={len(f_regress)} new={len(f_new)}"
        print(line)
        if f_regress:
            print(f"    !! REGRESSED (was TP, now gone): {sorted(f_regress)}")
        if f_new:
            print(f"    ~  NEW categories (review): {sorted(f_new)}")
        if f_remain:
            print(f"    .. FP still present: {sorted(f_remain)}")

    print(f"\nFP fixed={fixed}  FP remaining={remaining}  TP regressions={regress}  new-to-review={new}")
    print("Regressions must be 0. Remaining/new FPs are the next cycle's targets.")
    return 0 if regress == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
