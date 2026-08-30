# Report schema

The machine-checkable JSON Schema (draft 2020-12) lives at `common/schema.json`
and is enforced on every emitted report by `common/report.py`. This note explains it.

## Required floor (the contest minimum)
```
{
  "site": "example.com",
  "audited_at": "2026-09-20T14:32:00Z",
  "summary": { "total_findings": 6, "critical": 1, "high": 2, "medium": 3 },
  "findings": [
    {
      "id": "F-001",
      "title": "No JSON-LD structured data on product pages",
      "severity": "high",
      "evidence": "Crawled 12 product pages; 0/12 contain schema.org markup.",
      "suggested_action": { "summary": "Add Product/Offer JSON-LD to every product page.", "priority": "high" }
    }
  ]
}
```

## Our additions (all optional supersets — the floor above still validates)
- `summary.low` and `summary.discoverability` / `summary.engagement` counts.
- `severity` and `priority` enum extended to include `low`.
- Per finding: `category` (the check slug), `half` (`discoverability`|`engagement`|`both`),
  `mechanism` (the Round-2 mechanism this addresses), and `evidence_detail` (structured).
- `suggested_action.mechanism`, `.effort` (`low`|`medium`|`high`), `.confidence` (`high`|`medium`|`low`).
- Top-level `scope` (pages sampled, render availability, robots found, per-skill errors)
  and `limitations` (single-variant fetch, lab-vs-field, network-dependent checks).

## Invariants (checked in code beyond JSON Schema)
- `summary.total_findings == len(findings)`.
- Each `summary.<severity>` equals the tally of findings at that severity.
- Findings are sorted by (severity, fix priority, category, dedup-key) and then
  numbered `F-001…`, so ordering and ids are deterministic across runs.
