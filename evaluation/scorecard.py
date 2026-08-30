#!/usr/bin/env python3
"""Accuracy scorecard over the golden fixtures.

Serves each fixture mini-site on an ephemeral localhost port, runs the entrypoint
audit, and compares emitted finding categories to evaluation/manifest.json:
  - defect cases  -> each expected check MUST fire (else a miss / false negative)
  - control cases -> each listed check MUST stay silent (else a false positive)

Prints per-check recall + the overall false-positive rate on controls, and exits
non-zero if recall < RECALL_MIN or fp-rate > FP_BUDGET. Thresholds are never tuned
to the fixtures. Run: python3 evaluation/scorecard.py
"""
import functools
import importlib.util
import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIX = os.path.join(ROOT, "evaluation", "fixtures")
sys.path.insert(0, ROOT)

RECALL_MIN = 0.90
FP_BUDGET = 0.05


def _entry():
    path = os.path.join(ROOT, "skills", "website-ai-audit", "scripts", "audit.py")
    spec = importlib.util.spec_from_file_location("wai_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _serve(directory):
    handler = functools.partial(_Quiet, directory=directory)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _categories(entry, case_dir, start):
    srv, port = _serve(case_dir)
    try:
        rep = entry.run_audit(f"http://127.0.0.1:{port}{start}",
                              max_pages=10, render=False,
                              audited_at="2026-01-01T00:00:00Z")
    finally:
        srv.shutdown()
    return {f["category"] for f in rep["findings"]}, rep


def main():
    entry = _entry()
    manifest = json.load(open(os.path.join(ROOT, "evaluation", "manifest.json"), encoding="utf-8"))
    per = {}  # check -> {tp,fn,fp,tn}

    def bump(check, key):
        per.setdefault(check, {"tp": 0, "fn": 0, "fp": 0, "tn": 0})[key] += 1

    misses, false_pos = [], []
    for case in manifest["cases"]:
        case_dir = os.path.join(FIX, case["dir"])
        if not os.path.isdir(case_dir):
            print(f"MISSING fixture dir: {case['dir']}")
            continue
        found, _ = _categories(entry, case_dir, case.get("start", "/"))
        if case["kind"] == "defect":
            for chk in case.get("expect", []):
                if chk in found:
                    bump(chk, "tp")
                else:
                    bump(chk, "fn"); misses.append((case["dir"], chk))
        else:  # control
            for chk in case.get("expect_absent", []):
                if chk in found:
                    bump(chk, "fp"); false_pos.append((case["dir"], chk))
                else:
                    bump(chk, "tn")

    tp = sum(v["tp"] for v in per.values()); fn = sum(v["fn"] for v in per.values())
    fp = sum(v["fp"] for v in per.values()); tn = sum(v["tn"] for v in per.values())
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0

    print(f"{'check':<40} {'recall':>8} {'TP':>3} {'FN':>3} {'FP':>3} {'TN':>3}")
    for chk in sorted(per):
        v = per[chk]
        r = v["tp"] / (v["tp"] + v["fn"]) if (v["tp"] + v["fn"]) else float("nan")
        print(f"{chk:<40} {r:>8.2f} {v['tp']:>3} {v['fn']:>3} {v['fp']:>3} {v['tn']:>3}")
    print(f"\nOVERALL recall={recall:.3f} (TP={tp} FN={fn})  "
          f"false-positive-rate={fp_rate:.3f} (FP={fp} TN={tn})")
    if misses:
        print("MISSES:", ", ".join(f"{d}:{c}" for d, c in misses))
    if false_pos:
        print("FALSE POSITIVES:", ", ".join(f"{d}:{c}" for d, c in false_pos))

    ok = recall >= RECALL_MIN and fp_rate <= FP_BUDGET
    print("\n" + ("PASS" if ok else "FAIL")
          + f"  (need recall>={RECALL_MIN}, fp-rate<={FP_BUDGET})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
