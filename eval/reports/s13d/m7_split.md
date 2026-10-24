# Pilot addendum (dev): M7 citation validity, split by claim type

> **pilot (dev), addendum.** 96 dev questions; not a test-set result. This file adds columns to
> `eval/reports/s13/pilot_table.md`. That table is **not** edited, and no number in it changes.

**Why (S13d decision 1 (a), owner, 24 Oct 2026).**
- The validator's R3 chunk rule and metrics M7 disagree on `c_` / `s_` citations of claims that
  name no dotted `model.column` (`eval/reports/s13c_session.md`, diagnosis;
  `docs/plans/s13d-design.md` §1).
- M7 stays the reported number (metrics-design v1.2, `metrics.py` 1.3.0, unchanged).
- The split is reported next to it, here for the pilot and in the v1.0 results.

**How it is computed (report-side only; `metrics.py` is not changed).**
- Script: `scripts/s13d_measure.py --part m7` (read-only).
  - It uses `metrics.py`'s own adapters, the M3 extractor and `check_citation`.
  - It asserts that its unsplit number equals `score_run`'s `citation_valid_answer`, per question
    and on the mean.
- Per-answer validity, over answered answers (n), with M7's rules (zero citations invalid, the
  v1.1 "no" verdict exception):
  - **dotted-claim citations only:** the answer's citations first cited by a claim that names a
    dotted column;
  - **no-column-claim citations only:** those first cited by a claim that names none.

  An answer can count in both.
- An answered answer with zero citations is in neither split column. It stays invalid in the
  M7 column.
- Micro = valid / checked `c_` and `s_` citations by claim type. Edge citations are not shown
  (they always name a column).

**Records** (sha256, first 12 hex):

| records | file | sha256 |
|---|---|---|
| S1 qwen pilot | `eval/runs/s1/pilot/s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl` | 2d917fdae1d7 |
| S1 Gemini pilot | `eval/runs/s1/pilot/s1-gemini-3-5-flash-lite-dev.jsonl` | 1d71a84ab020 |
| S4 qwen pilot | `eval/runs/s4/s4-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl` | 8060f936e718 |
| S4 Gemini pilot | `eval/runs/s4/s4-gemini-3-5-flash-lite-dev.jsonl` | 1e0a1a87bae8 |
| S4 qwen post-S13c (diagnostic, not a pilot row) | `eval/runs/s4/diagnostic/s13c-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl` | 4fb1873ba293 |

## Split

| records | view | M7 per answer (as scored) | dotted-claim citations only | no-column-claim citations only | micro, dotted claims | micro, no-column claims |
|---|---|---|---|---|---|---|
| S1 qwen pilot | validated | 0.533 (90) | 0.886 (70) | 0.000 (34) | c_ 168/178, s_ 0/0 | c_ 1/84, s_ 0/0 |
| S1 Gemini pilot | validated | 0.885 (78) | 0.921 (76) | 0.000 (3) | c_ 223/229, s_ 0/0 | c_ 0/4, s_ 0/0 |
| S4 qwen pilot | raw | 0.616 (73) | 0.723 (65) | 0.375 (16) | c_ 4/4, s_ 1/1 | c_ 1/11, s_ 0/2 |
| S4 qwen pilot | validated | 0.899 (69) | 1.000 (61) | 0.500 (12) | c_ 6/6, s_ 1/1 | c_ 1/7, s_ 0/2 |
| S4 qwen pilot | augmented | 0.914 (70) | 1.000 (63) | 0.500 (12) | c_ 6/6, s_ 1/1 | c_ 1/7, s_ 0/2 |
| S4 Gemini pilot | raw | 0.890 (82) | 0.949 (78) | 0.500 (4) | c_ 16/18, s_ 28/30 | c_ 0/1, s_ 0/1 |
| S4 Gemini pilot | validated | 0.938 (80) | 1.000 (76) | 0.400 (5) | c_ 16/16, s_ 24/24 | c_ 0/0, s_ 0/5 |
| S4 Gemini pilot | augmented | 0.951 (81) | 1.000 (78) | 0.400 (5) | c_ 16/16, s_ 24/24 | c_ 0/0, s_ 0/5 |
| S4 qwen post-S13c (diagnostic) | raw | 0.613 (80) | 0.725 (69) | 0.400 (20) | c_ 8/8, s_ 1/1 | c_ 1/18, s_ 0/2 |
| S4 qwen post-S13c (diagnostic) | validated | 0.885 (78) | 1.000 (68) | 0.529 (17) | c_ 12/12, s_ 1/1 | c_ 1/10, s_ 0/2 |
| S4 qwen post-S13c (diagnostic) | augmented | 0.899 (79) | 1.000 (70) | 0.529 (17) | c_ 12/12, s_ 1/1 | c_ 1/10, s_ 0/2 |

## Reading

- **S1 qwen:** 34 of its 90 answered answers fail M7 on claims that name no column (micro 1 / 84).
  On dotted-claim citations alone it is 0.886.
- **S4-validated:** 1.000 on dotted-claim citations in every record set. Its M7 losses come from
  no-column claims, or from answered answers with zero citations (invalid under M7 and in
  neither split column). Example: S4 qwen pilot, 7 failing answers = 6 of the 12 with
  no-column-claim citations + 1 other.
- **The gap is in claim phrasing as much as in citation quality.** It hits S1 qwen hardest. The
  M7 number is still the definition; the split is how it is read.
- There is no post-S13c S1 run (S1 is frozen) and no post-S13c Gemini run. The post-S13c qwen row
  is a diagnostic, shown for comparison only.
