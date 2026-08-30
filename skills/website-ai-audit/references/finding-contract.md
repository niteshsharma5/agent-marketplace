# Finding contract

Both layers of the hybrid audit speak this one shape. Deterministic checks build
findings with `common.contract.make_finding` (written to `signals.json`); the
agent hand-writes findings in the same shape to `agent_findings.json` (see
`hybrid-procedure.md`). `compose.py` merges, dedupes, sorts, numbers, and
validates them. Keeping one shape here is what lets the script and agent layers
compose into one report without drift.

## make_finding signature
```
make_finding(check, title, severity, half, evidence, fix, *,
             mechanism="", priority=None, confidence="medium", effort="medium",
             location="", evidence_detail=None)
```

| field | meaning |
|-------|---------|
| `check` | stable slug, also the report `category` (e.g. `js-render-gap`) |
| `title` | short human title |
| `severity` | `critical` \| `high` \| `medium` \| `low` — how broken it is |
| `half` | `discoverability` \| `engagement` \| `both` |
| `evidence` | concrete string with numbers, location, and `N/M pages` prevalence |
| `fix` | the suggested-action summary |
| `mechanism` | WHY this matters (the Round-2 mechanism) — always set it |
| `priority` | fix-first order (impact × ease); defaults to severity |
| `confidence` | `high` \| `medium` \| `low` — how sure the signal is |
| `effort` | `low` \| `medium` \| `high` — cost of the fix |
| `location` | stable discriminator (url + selector/header) used for dedup |

## Severity guidance
- `critical` — the brand is effectively invisible/uncitable (bot blocked, content JS-only and unrendered).
- `high` — a strong barrier to citation or a major engagement leak.
- `medium` — a real but partial issue, or one affecting some pages.
- `low` — advisory / proactive nudge; conservative signals live here.

## Rules every check obeys
- Never emit a content finding from a page whose `fetch_class != "ok"`.
- Aggregate across pages: one finding per issue-type with prevalence, not one per page.
- Obey the false-positive guards in each skill's `references/`. When unsure, lower
  severity/confidence or skip — few false positives beats broad coverage.
