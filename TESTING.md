# Testing plan

How we prove the marketplace detects real problems, avoids false positives, and generalizes — under a sandbox that blocks external network, and without the circularity of grading ourselves.

#### The bias problem we designed around
If the same author writes the detector, the test fixtures, and the grader, the "tests" just confirm the code does what its author intended — they prove nothing about robustness. So testing is split by a strict **information barrier**, and no single model both creates ground truth and judges against it:

| role | who | knows the detector? | model |
|------|-----|--------------------|-------|
| system under test | the auditor (deterministic Python) | — it *is* the detector | code, not a model |
| test-set author | blind adversary generators | NO (forbidden from reading `skills/`/`common/`) | Sonnet |
| grader | blind adjudicators | NO (judge on merits, not implementation) | Opus |
| tie-breakers | prosecutor / defender / referee | NO | Sonnet / Sonnet / Opus |

The auditor is code with no prompt surface, so there's nothing to "prompt-harden" toward the tests. Fixes only ever come from *generalizable* defects the blind grader surfaces — never by tuning to a specific site.

#### Layer 1 — Blind adversarial evaluation (the robustness measure)
1. **Blind generation.** Adversary agents (Sonnet, walled off from our code) invent diverse sites from first principles — planted-problem sites, clean controls, and *legitimate traps* (dense expert prose, decorative empty `alt`, deliberate training-bot opt-outs) — and seal an independent ground truth in their own words. `evaluation/blackbox/sites/<name>/` + `evaluation/blackbox/truth/<name>.json`.
2. **Deterministic audit.** Our code runs on each site → `evaluation/blackbox/findings/<name>.json`. Objective, no model.
3. **Blind adjudication.** An independent judge (Opus) inspects each site *itself*, then scores every finding true-positive / false-positive / unverifiable against reality (traps must NOT be flagged), rates each fix, and lists what we missed — triangulating its own read + the adversary's truth + our output.
4. **Adversarial debate.** Every contested finding goes to a prosecutor (argue it's valid) vs defender (argue it's a false positive) vs referee (rule on merits), with mixed models, so no single judge's call stands unchallenged.
5. **Aggregate → precision / recall / false-positive-rate**, plus a list of *generalizable* FPs/FNs that feed the next fix cycle. Re-test on a **fresh** blind batch so we never overfit to one set.

#### Results so far (blind eval)
| run | sites | precision | false positives | notes |
|-----|-------|-----------|-----------------|-------|
| Round 1 (pre-fix) | 8 blind | **0.576** | 36 (49 TP) | biased fixtures had reported 0% FP — the blind eval exposed the real number |
| Round 2 (held-out, post-fix) | 6 fresh blind | **0.857** | 5 (30 TP) | sites generated *after* the fixes → generalization, not overfitting |

Two mechanism-framed fix cycles (no site special-casing) removed the systematic FPs the blind judges + debate surfaced: plain-HTTP flagged on an http fetch origin when the site declares HTTPS; render-blocking overclaimed on tiny pages; off-domain canonical (legitimate staging/CDN); `ClaudeBot`/`Meta-ExternalAgent` miscategorized as citation (they are training) bots; `ProfilePage`/`Person` rejected as valid schema; entity checks blind to *nested* publisher `Organization`, subset bylines, and `Person.sameAs`; non-HTML resources (`robots.txt`) being audited; `llms.txt`-absence noise. 28 FPs fixed across the round-1 set with zero real regressions; the held-out round confirms the fixes hold on unseen sites. Remaining FPs are one-per-category and borderline (severity calibration, a planted trap, a no-HTTPS-signal edge) — not systematic. Recall is the next axis (28 misses on the held-out set, mostly low-severity or beyond the current check set).

#### Layer 2 — White-box regression (demoted; not a robustness claim)
`evaluation/fixtures/` holds seeded defect + matched-control mini-sites whose authors *did* see the checks — so this only answers "does check X still fire on a page built to trip it," a regression guard against future edits. `evaluation/manifest.json` + `evaluation/scorecard.py` compute per-check recall and the control false-positive rate. Useful, but it is white-box and self-referential, so it is not evidence of generalization. Checks needing a non-static server (UA-differential WAF probe, custom headers, redirects, timing, HTTPS mixed-content) are documented as snapshot-covered rather than faked.

#### Layer 3 — Field realism via offline snapshots (~20 real sites)
`evaluation/sites.txt` lists ~20 diverse real sites (a few India top sites as FP controls + SMB/varied-stack/SPA sites). `evaluation/capture.py <URL> out.json` freezes the whole crawl (raw + rendered HTML + headers + robots) *outside the sandbox*; `evaluation/capture.py --replay` runs the audit against the frozen crawl anywhere, deterministically. Assertions: completes under budget, schema-valid, no crash on real HTML, plausible — a few hand-verified. Network-only checks report `inconclusive` in replay.

#### Layer 4 — Robustness harnesses (`evaluation/run_harness.py`)
Determinism (byte-identical re-runs), robots politeness (never fetch a `Disallow`ed path; GET/HEAD only), and runtime + zip-size budget, plus `evaluation/validate_marketplace.py` for structure/hygiene.

#### What each layer proves
| rubric line | layer |
|-------------|-------|
| Detection accuracy, few false positives, both halves, generalization | Layer 1 (blind, unbiased) |
| No regressions as we edit checks | Layer 2 (white-box) |
| Doesn't fall over on real-world HTML | Layer 3 (field snapshots) |
| Deterministic; safe; recommend-only; schema | Layer 4 |

#### Run
```
python3 evaluation/validate_marketplace.py                 # structure + hygiene
python3 evaluation/scorecard.py                            # white-box regression
python3 evaluation/run_harness.py                          # determinism + politeness + budget
python3 evaluation/blackbox/run_eval.py                    # deterministic audit of blind sites (metrics after adjudication)
python3 evaluation/capture.py --replay-all evaluation/snapshots # field suite (after capture outside sandbox)
```
