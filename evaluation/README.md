# evaluation/

Everything used to test the auditor: the labeled test dataset, its ground truth, the auditor's saved output, the independent grading, and the eval scripts. All of it is committed so the results are reproducible and reviewable. Reproducing the metrics needs **only Python** (no LLM, no keys) — see the root `README.md`.

Read `../TESTING.md` for the methodology and `../REPORT.md` for the improvement journey.

#### The blind dataset (the robustness measure)
Realistic websites authored by an independent red team that never saw the detector, each paired with a **sealed ground truth** in the author's own words (real problems + what's fine + legitimate traps).

- `blackbox/` — round 1 (8 sites). `blackbox2/` — fresh held-out round 2 (6 new archetypes, created after the fixes).
  - `sites/<name>/` — the actual website files (served locally over `http.server` during a run).
  - `truth/<name>.json` — the sealed ground truth for that site.
  - `findings/<name>.json` — what our auditor produced (regenerate with `run_eval.py`).
  - `adjudication.json` — the independent judges' + debate's verdicts (TP/FP/missed).
- `blackbox/run_eval.py` — re-audits every blind site deterministically → `findings/`.
- `blackbox/fp_diff.py` — before/after false-positive diff against the saved adjudication labels.

#### The white-box regression bench (a guard, not a robustness claim)
- `fixtures/<skill>/<case>-defect|-control/` — seeded single-defect mini-sites + matched clean controls. Their authors *saw* the checks, so this only proves "check X still fires on a page built to trip it."
- `manifest.json` — maps each fixture to the check it should (defect) / shouldn't (control) fire.
- `scorecard.py` — serves each fixture, runs the audit, prints per-check recall + the control false-positive rate.

#### Harnesses
- `run_harness.py` — determinism (byte-identical re-runs), robots politeness (never fetch a `Disallow`ed path; GET/HEAD only), runtime + package-size budget.
- `validate_marketplace.py` — manifest well-formed, exactly one entrypoint, every `SKILL.md`/script valid.

#### Field realism (real sites, via offline snapshots)
- `sites.txt` — ~20 diverse real sites. `capture.py <URL> out.json` freezes a real crawl **outside a sandbox**; `capture.py --replay` runs the audit against the frozen snapshot anywhere, deterministically.

#### Reproduce
```
python3 evaluation/validate_marketplace.py
python3 evaluation/scorecard.py
python3 evaluation/run_harness.py
python3 evaluation/blackbox/run_eval.py && python3 evaluation/blackbox/fp_diff.py
```
Headline results (from the blind eval): precision **0.576 → 0.857** across two fix cycles, measured on sites the auditor had never seen. Details in `../TESTING.md`.
