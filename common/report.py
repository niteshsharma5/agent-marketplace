"""Assemble, validate, and render the single audit report.

The entrypoint feeds every sub-skill's findings here. This module owns the
output contract: dedupe -> sort -> number -> count -> schema-validate -> render.
All counts are computed from the findings list (never hand-maintained).
"""
import json
import os

from .contract import SEVERITY_RANK, PRIORITY_RANK

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.json")

DEFAULT_LIMITATIONS = [
    "Single-variant fetch: one geography, one device profile, no logged-in state, no cookie consent accepted. Personalization and geo/consent-gated content are not observed.",
    "Lab proxy, not field data: latency and Core Web Vitals appear as risk factors measured once, not real-user metrics.",
    "Network-dependent checks (sameAs resolvability, broken links) reflect what was reachable at audit time and are excluded from the byte-for-byte determinism guarantee.",
]


def _load_schema():
    with open(_SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def assemble_report(site, findings, audited_at, *, limitations=None, scope=None):
    # Dedupe by stable key (first occurrence wins).
    seen, deduped = set(), []
    for f in findings or []:
        key = f.get("_dedup_key") or f"{f.get('check')}::{f.get('evidence')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(f)

    deduped.sort(key=lambda f: (
        SEVERITY_RANK.get(f.get("severity"), 9),
        PRIORITY_RANK.get(f.get("suggested_action", {}).get("priority"), 9),
        f.get("check", ""),
        f.get("_dedup_key", ""),
    ))

    out_findings = []
    for i, f in enumerate(deduped, 1):
        sa = dict(f.get("suggested_action", {}))
        out_findings.append({
            "id": f"F-{i:03d}",
            "title": f.get("title", ""),
            "severity": f.get("severity", "medium"),
            "category": f.get("check", ""),
            "half": f.get("half", "discoverability"),
            "evidence": f.get("evidence", ""),
            "evidence_detail": f.get("evidence_detail", {}) or {},
            "mechanism": f.get("mechanism", ""),
            "suggested_action": {
                "summary": sa.get("summary", ""),
                "priority": sa.get("priority", f.get("severity", "medium")),
                "mechanism": sa.get("mechanism", f.get("mechanism", "")),
                "effort": sa.get("effort", "medium"),
                "confidence": sa.get("confidence", "medium"),
            },
        })

    counts = {k: 0 for k in ("critical", "high", "medium", "low")}
    halves = {"discoverability": 0, "engagement": 0}
    for f in out_findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
        if f["half"] in ("discoverability", "both"):
            halves["discoverability"] += 1
        if f["half"] in ("engagement", "both"):
            halves["engagement"] += 1

    return {
        "site": site,
        "audited_at": audited_at,
        "summary": {
            "total_findings": len(out_findings),
            "critical": counts["critical"],
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "discoverability": halves["discoverability"],
            "engagement": halves["engagement"],
        },
        "scope": scope or {},
        "limitations": limitations if limitations is not None else DEFAULT_LIMITATIONS,
        "findings": out_findings,
    }


def validate(report):
    """Raise jsonschema.ValidationError if the report breaks the contract."""
    import jsonschema
    jsonschema.validate(report, _load_schema())
    # Cross-field invariant the schema can't express: counts must equal tallies.
    s, f = report["summary"], report["findings"]
    assert s["total_findings"] == len(f), "total_findings != len(findings)"
    for sev in ("critical", "high", "medium", "low"):
        actual = sum(1 for x in f if x["severity"] == sev)
        assert s.get(sev, 0) == actual, f"summary.{sev} mismatch"
    return True


def to_markdown(report):
    """Human-readable view. Evidence/fix text is escaped so untrusted site
    content can't inject markup or break table rows."""
    def esc(x):
        return (str(x).replace("|", "\\|").replace("\n", " ").replace("\r", " ")).strip()

    s = report["summary"]
    lines = [
        f"# Brand AI-Readiness Audit — {esc(report['site'])}",
        "",
        f"Audited: {esc(report['audited_at'])}",
        "",
        f"**{s['total_findings']} findings** — "
        f"{s['critical']} critical, {s['high']} high, {s['medium']} medium, {s.get('low', 0)} low "
        f"({s.get('discoverability', 0)} discoverability, {s.get('engagement', 0)} engagement)",
        "",
    ]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for f in report["findings"]:
        sev = f["severity"].upper()
        sa = f["suggested_action"]
        lines += [
            f"#### [{f['id']}] {esc(f['title'])} — `{sev}` · {f['half']} · fix priority `{sa['priority']}` · confidence `{sa.get('confidence','')}`",
            f"**Why it matters:** {esc(f.get('mechanism',''))}",
            f"**Evidence:** {esc(f['evidence'])}",
            f"**Fix:** {esc(sa['summary'])} _(effort: {sa.get('effort','')})_",
            "",
        ]
    if report.get("limitations"):
        lines += ["#### Limitations", ""]
        lines += [f"- {esc(x)}" for x in report["limitations"]]
        lines.append("")
    return "\n".join(lines)
