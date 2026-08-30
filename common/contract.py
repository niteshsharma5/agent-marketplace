"""Shared finding contract for every audit skill.

Every sub-skill's `run(ctx)` returns a list of finding dicts built via `make_finding`.
The entrypoint dedupes, sorts, numbers, and validates them into the final report.
Keeping this shape in one place is what lets five independently-authored skills
compose into one schema-valid report without drift.
"""

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
VALID_SEVERITY = set(SEVERITY_RANK)
VALID_HALF = {"discoverability", "engagement", "both"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_EFFORT = {"low", "medium", "high"}


def make_finding(check, title, severity, half, evidence, fix, *,
                 mechanism="", priority=None, confidence="medium", effort="medium",
                 location="", evidence_detail=None):
    """Build one normalized finding.

    check     stable slug for the check, e.g. "js-render-gap" (also the report category)
    half      "discoverability" | "engagement" | "both"
    evidence  a concrete, human-readable string with numbers/locations (required by schema)
    fix       the suggested action summary
    location  a stable discriminator (url + selector/header) used for dedup + id derivation;
              defaults to evidence when omitted
    priority  fix-first order (impact x ease); defaults to severity when omitted
    """
    severity = severity if severity in VALID_SEVERITY else "medium"
    half = half if half in VALID_HALF else "discoverability"
    confidence = confidence if confidence in VALID_CONFIDENCE else "medium"
    effort = effort if effort in VALID_EFFORT else "medium"
    priority = priority if priority in VALID_SEVERITY else severity
    return {
        "check": check,
        "half": half,
        "title": title,
        "severity": severity,
        "evidence": str(evidence),
        "evidence_detail": evidence_detail or {},
        "mechanism": mechanism,
        "_dedup_key": f"{check}::{location or evidence}",
        "suggested_action": {
            "summary": fix,
            "priority": priority,
            "mechanism": mechanism,
            "effort": effort,
            "confidence": confidence,
        },
    }
