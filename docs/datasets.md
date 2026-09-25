---
description: The golden dataset format, labeled and unlabeled cases, metadata for segments, and how to build a dataset that catches real regressions.
---

# Golden datasets

A **golden dataset** is a fixed set of inputs, most with a known correct answer, that a
model version is tested against. It is the input of `decguard test`, `decguard fuzz` and
`decguard test --all`. The same file, run against two model versions, is what
[`decguard diff`](./regression.md) compares.

Golden datasets are for testing **before** deployment. Decisions collected **after**
deployment use a different, richer record format: see
[production checks](./production.md#record-schema).

## Format

A dataset is either:

- **`.jsonl`** — one JSON object per line; blank lines are ignored (recommended);
- **`.json`** — a JSON list of objects.

```json
{"id": "r1", "input": "The blender arrived damaged and won't turn on.", "expected": "refund", "metadata": {"locale": "en"}}
{"id": "r5", "input": "The invoice shows a different price than the website did.", "expected": "review", "metadata": {"locale": "en"}}
{"id": "r11", "input": "Can someone call me about my order?", "metadata": {"locale": "en"}}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `input` | yes | what the model sees: a string or a JSON object |
| `expected` | no | the correct label; must be one of the contract's labels (score levels may be numbers) |
| `id` | no | unique case id; defaults to `case-<n>` by position (1-based) |
| `metadata` | no | a JSON object of attributes such as `locale` or `customer_tier` |

The contract points to the dataset with `dataset:`, relative to the contract file.
`decguard validate --dataset` and `decguard test --dataset` override it for one run.

## Strict loading

Nothing is skipped silently. Loading stops with exit code `2`, naming the line or
position, when a case:

- is not valid JSON, or has an unknown field;
- has no `input`;
- has an `expected` label that is not in the contract;
- repeats an `id` already used.

An empty dataset is also an error. The report stores the file's `sha256:` hash, so you can
tell exactly which dataset produced a result.

## Labeled and unlabeled cases

Cases without `expected` still run. They count toward coverage, abstention, latency and
error rate, and they are transformed by [metamorphic properties](./properties.md), which
compare the model with itself and need no gold answer. Accuracy, macro-F1, calibration
(ECE, Brier, NLL) and selective accuracy use **labeled** cases only.

A gated metric that cannot be computed fails its gate: `min_accuracy` on a dataset with no
labeled cases is a failure, not a pass.

## Object inputs

When the model needs structured input, pass a JSON object:

```json
{"id": "s2", "input": {"text": "Checkout latency degraded by 40% in eu-west.", "affected_users": 8000}, "expected": 3}
```

Text properties then need `fuzz.text_field` to know which key to edit, and the
[`monotonic`](./properties.md#monotonic-score) property changes a numeric field. The
[severity example](https://github.com/suffro/decguard/tree/main/examples/severity) uses
both.

## Metadata and segments

`metadata` is carried through to every report. Its keys become **segments** in
regression diffs (`regression.segment_by`, `decguard diff --segment-by`), which report
accuracy and flip rate per value, and can gate on the worst segment. Use scalar values
(strings, numbers, booleans) for keys you want to segment by.

## Building a useful dataset

- **Stable ids.** Diffs match cases by `id` across runs. Set ids explicitly and never
  reuse one for a different input.
- **Real distribution first, then edge cases.** Sample inputs the model will actually see,
  then add the ambiguous and adversarial cases you care about. Label edge cases carefully:
  one wrong label moves both accuracy and calibration.
- **Cover every label.** Macro-F1 and per-label precision/recall are only meaningful when
  each label has support.
- **Enough cases for calibration.** ECE bins cases by confidence; with a handful of cases,
  single decisions dominate it. Set gates with the dataset size in mind.
- **Version it with the contract.** Commit the dataset next to `decguard.yaml` so a change
  to either is reviewed together.
