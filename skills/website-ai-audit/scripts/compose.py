#!/usr/bin/env python3
"""Merge deterministic (script) findings + agent-reasoned findings into one report.

Keeps the reliable parts deterministic: dedupe, sort, severity counts, id
assignment, and JSON-Schema validation all happen here regardless of who authored
a finding. The agent contributes judgment findings and site-specific fix text;
this step guarantees the emitted report is well-formed and self-consistent.

    python3 compose.py --site <URL> --signals out/signals.json \
        --agent out/agent_findings.json --scope out/scope.json --out ./out

agent_findings.json is a JSON list of findings in the shared contract shape:
    {"check","title","severity","half","evidence","mechanism",
     "suggested_action":{"summary","priority","effort","confidence"}}
(severity/priority in critical|high|medium|low; half in discoverability|engagement|both)
It may be absent or empty — the report then contains only the deterministic findings.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
from common import report  # noqa: E402
from common.contract import make_finding  # noqa: E402

VALID_SEV = {"critical", "high", "medium", "low"}
VALID_HALF = {"discoverability", "engagement", "both"}


def _load(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _normalize_agent(raw):
    """Coerce agent-authored findings into the contract via make_finding, dropping
    malformed ones rather than emitting a broken report."""
    out = []
    for f in raw or []:
        try:
            sa = f.get("suggested_action", {}) or {}
            fix = sa.get("summary") or f.get("fix") or ""
            if not (f.get("check") and f.get("title") and f.get("evidence") and fix):
                continue
            sev = f.get("severity") if f.get("severity") in VALID_SEV else "medium"
            half = f.get("half") if f.get("half") in VALID_HALF else "discoverability"
            out.append(make_finding(
                f["check"], f["title"], sev, half, f["evidence"], fix,
                mechanism=f.get("mechanism", ""),
                priority=sa.get("priority"),
                confidence=sa.get("confidence", "medium"),
                effort=sa.get("effort", "medium"),
                location=f.get("location", ""),
                evidence_detail=f.get("evidence_detail"),
            ))
        except Exception:
            continue
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True)
    ap.add_argument("--signals", required=True, help="deterministic findings from audit.py --emit-context")
    ap.add_argument("--agent", help="agent-reasoned findings (optional)")
    ap.add_argument("--scope", help="scope.json from audit.py --emit-context")
    ap.add_argument("--audited-at", help="override timestamp")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--format", choices=["json", "md", "both"], default="both")
    a = ap.parse_args(argv)

    signals = _load(a.signals) or []
    agent = _normalize_agent(_load(a.agent))
    scope = _load(a.scope) or {}
    scope["agent_findings_merged"] = len(agent)
    at = a.audited_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rep = report.assemble_report(a.site, signals + agent, at, scope=scope)
    report.validate(rep)

    os.makedirs(a.out, exist_ok=True)
    if a.format in ("json", "both"):
        with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
    if a.format in ("md", "both"):
        with open(os.path.join(a.out, "report.md"), "w", encoding="utf-8") as f:
            f.write(report.to_markdown(rep))
    s = rep["summary"]
    print(f"composed report for {rep['site']} -> {a.out}  "
          f"({s['total_findings']} findings = {len(signals)} script + {len(agent)} agent; "
          f"{s['critical']}C/{s['high']}H/{s['medium']}M/{s['low']}L)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
