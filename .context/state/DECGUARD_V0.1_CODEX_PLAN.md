# DecGuard v0.1 — Development Plan for Codex

## Mission

Build **DecGuard v0.1** as an open-source, production-ready developer tool for **testing, verifying, and safely operating probabilistic AI decision models** before and after deployment.

DecGuard is **not** another Jev-like model, another generic LLM eval framework, or a SaaS observability platform.

Its role is to sit **above existing decision-model backends and OSS tooling** and provide one coherent workflow for:

- decision contracts;
- backend-neutral execution;
- metamorphic / robustness testing;
- regression and model-version comparison;
- calibration and reliability checks;
- CI-friendly PASS / WARN / FAIL gates;
- post-deployment checks on collected production datasets;
- explicit runtime fallback / cascade policies.

The initial target ecosystem includes Jev/System-One-style models, Open-Jev, Kev, and compatible probabilistic decision endpoints.

The main design principle is:

> **Reuse mature open-source tools where they already solve the problem. Implement only the missing decision-specific reliability layer.**

Do not build a hosted service, dashboard, database server, alerting platform, model-training system, or generic LLM orchestration framework in v0.1.

---

# Rule zero

Start simple.

Before implementing anything substantial:

1. inspect the repository and `AGENTS.md`;
2. identify reusable OSS components and their licenses;
3. avoid reimplementing functionality already provided by existing projects;
4. keep the DecGuard-owned core small, explicit, typed, deterministic where possible, and backend-neutral;
5. keep each major component independently testable;
6. optimize for a fast first release without compromising correctness or reproducibility.

If a dependency is immature, abandoned, poorly licensed, or too tightly coupled, prefer a thin internal implementation over introducing fragile dependency risk.

---

# Product definition

A user should eventually be able to write something conceptually like:

```yaml
decision:
  name: refund_request
  type: choice
  options:
    - refund
    - reject
    - review

backend:
  provider: openjev
  model: open-jev-2b

reliability:
  min_accuracy: 0.95
  max_ece: 0.05

properties:
  option_order_invariant: true
  irrelevant_context_tolerance: 0.03
  paraphrase_tolerance: 0.05

policy:
  accept_above: 0.95
  review_below: 0.80
  fallback:
    backend: stronger-model
```

and then run commands equivalent to:

```bash
decguard test
decguard diff --baseline previous.json
decguard check --dataset production.jsonl
decguard run
```

The exact CLI syntax may evolve during implementation, but the workflow must stay this simple.

---

# Architecture constraints

## DecGuard-owned concepts

DecGuard should own these abstractions:

### 1. Decision Contract

A versionable YAML/JSON specification defining:

- decision name and description;
- typed output semantics;
- allowed labels / score levels;
- backend configuration;
- reliability requirements;
- metamorphic properties;
- thresholds;
- cascade / fallback policy;
- optional references to external test packs or datasets.

Support at minimum:

- `choice`
- `noul` / boolean
- `score` / ordered categorical

The internal representation must be normalized and independent of any one provider.

### 2. Unified Decision Result

Every backend must normalize into one schema containing at least:

```text
decision id
labels
probabilities
selected label
confidence
backend
model/version
latency
metadata
```

Probabilities must be validated:

- finite;
- non-negative;
- normalized within tolerance;
- deterministic label ordering.

Never silently repair malformed backend responses without surfacing the issue.

### 3. Backend Adapter Interface

Keep adapters thin.

Support an extensible interface for:

- remote System-One / Jev-like HTTP endpoints;
- local/custom Python decision providers;
- at least one open/local backend used by integration tests.

Do not hard-code DecGuard around one model family.

### 4. Reliability Report

All testing modes should feed one canonical report format, containing:

- passed / warned / failed checks;
- metrics;
- regressions;
- fuzz failures;
- calibration;
- per-type results;
- per-backend/model provenance;
- reproducible failure examples;
- machine-readable exit status.

JSON is mandatory. A concise human-readable terminal report is also mandatory.

---

# Reuse existing OSS instead of competing with it

Investigate and integrate where useful rather than duplicating:

- `jev-packs` or equivalent reusable decision/evaluation packs;
- `jevcheck`-style regression workflows;
- Promptfoo / garak / Giskard-style generic adversarial tooling where applicable;
- calibration / metrics utilities from reliable OSS libraries;
- existing runtime decision/circuit tools where they already solve generic threshold/fallback mechanics.

Do **not** couple DecGuard so tightly to one external project that its absence breaks the core.

Prefer:

```text
DecGuard core
    +
optional integrations/plugins
```

over:

```text
DecGuard = wrapper that cannot function without five external CLIs
```

External tools should be orchestrated when they add clear value, while DecGuard owns the common contract, result schema, decision-specific tests, unified report, and CI semantics.

---

# STEP 1 — Core, contracts, backends, CLI

## Goal

Create a minimal but production-quality foundation that can execute typed decision contracts against multiple backends and generate reproducible reliability reports.

## Deliverables

### Repository foundation

Set up:

- package structure;
- CLI;
- typed configuration models;
- tests;
- linting / formatting;
- CI;
- semantic versioning;
- changelog;
- OSS license;
- contribution guide;
- minimal documentation.

Prefer a modern Python stack unless the existing repository already dictates another language.

A reasonable default is:

- Python 3.11+;
- `uv`;
- `pydantic` or equivalent for schemas;
- `typer` or equivalent for CLI;
- `pytest`;
- `ruff`;
- `mypy` or equivalent type checking where practical.

Do not add dependencies merely for convenience.

### Decision Contract v0.1

Implement a stable schema for:

- Choice
- Noul
- Score

Include schema versioning from day one:

```yaml
schema_version: "0.1"
```

Add validation and helpful errors.

### Backend abstraction

Implement:

```text
DecisionBackend
    decide(...)
    metadata(...)
    healthcheck(...)
```

with normalized `DecisionResult`.

Provide at least:

1. generic HTTP/System-One-compatible backend;
2. local/mock backend for deterministic tests;
3. one real open backend integration if practical without making CI depend on GPU/model downloads.

Real heavy integrations should be opt-in integration tests.

### CLI baseline

Implement at minimum:

```bash
decguard validate <contract>
decguard test <contract>
decguard report <results>
```

`test` at this stage may run static/golden cases only.

### Golden datasets

Support JSONL/JSON test cases with:

```text
input
expected answer (optional)
metadata
```

Labels must remain optional because some reliability tests operate without gold answers.

### Metrics

Implement or reuse robust implementations of:

- accuracy;
- macro F1 where applicable;
- NLL;
- Brier score;
- ECE;
- coverage;
- abstention/fallback rate;
- latency statistics.

Report calibration separately from raw accuracy.

### CI semantics

Define exit codes:

```text
0 = PASS
1 = reliability gate failed
2 = configuration/runtime error
```

A contract must be able to define hard gates such as:

```yaml
requirements:
  min_accuracy: 0.95
  max_ece: 0.05
```

### Step-1 acceptance criteria

Step 1 is complete only when:

- a contract validates;
- at least two backend implementations satisfy the same interface;
- the same dataset can run against either backend;
- results normalize identically;
- metrics are reproducible;
- PASS/FAIL works correctly;
- CI is green;
- the CLI has useful `--help`;
- no GPU or external paid service is required for the default test suite.

Commit Step 1 independently before moving on.

---

# STEP 2 — Decision-specific fuzzing, metamorphic testing, regression, CI

## Goal

Implement the main DecGuard differentiator:

> **automatically search for semantically irrelevant or controlled input transformations that make a probabilistic decision model behave inconsistently.**

Do not build a generic jailbreak framework.

Focus on **typed probabilistic decisions**.

## Metamorphic testing engine

Represent a test as:

```text
original decision
    ↓
controlled transformation
    ↓
new decision
    ↓
property comparison
```

Each transformation must record:

- original input;
- transformed input;
- transformation type;
- seed;
- backend result before/after;
- probability delta;
- selected-label change;
- whether the declared property passed.

### Initial transformations

Implement deterministic transformations first.

#### Choice

- option permutation;
- option-label formatting changes where semantics are preserved;
- irrelevant context insertion;
- whitespace / harmless formatting;
- controlled paraphrase hook;
- duplication of irrelevant information.

For option permutation, probabilities must be remapped to the semantic labels before comparison.

#### Noul

- affirmative/negative surface variation;
- irrelevant context insertion;
- paraphrase;
- controlled logical inversion tests where expected semantics can be derived.

Do not confuse invariance tests with inversion tests.

#### Score

- harmless paraphrase;
- irrelevant context;
- formatting changes;
- monotonicity tests when the contract explicitly declares a monotonic variable.

### Distribution-aware comparisons

Do not only test answer flips.

Measure at least:

- max absolute probability delta;
- total variation distance;
- Jensen-Shannon divergence or another stable symmetric distribution metric;
- confidence delta;
- answer flip;
- rank change where applicable.

Contracts should be able to specify tolerances:

```yaml
properties:
  option_order:
    enabled: true
    max_tv_distance: 0.03

  paraphrase:
    enabled: true
    max_tv_distance: 0.05
    max_flip_rate: 0.01
```

### Failure minimization

For generated failures, implement a simple reduction mechanism where practical:

- remove irrelevant inserted fragments;
- minimize perturbation sequence;
- preserve a failure while reducing the transformed example.

Do not overengineer a general delta-debugger in v0.1; support only transformations for which reduction is reliable.

### Paraphrase provider interface

Do not make a paid LLM mandatory.

Provide:

- deterministic/no-op testing implementation;
- provider interface;
- optional LLM-backed paraphrase integration.

Record model/provider/version for generated transformations.

### Regression / diff

Support:

```bash
decguard diff \
  --baseline baseline-results.json \
  --candidate candidate-results.json
```

Compare:

- answer flips;
- confidence shifts;
- probability distribution shifts;
- calibration changes;
- latency;
- failure counts;
- per-segment changes.

Allow contracts to fail CI when regression limits are exceeded.

Example:

```yaml
regression:
  max_answer_flip_rate: 0.005
  max_accuracy_drop: 0.01
  max_ece_increase: 0.02
```

### OSS integration

Where tools such as Promptfoo or existing Jev regression utilities are useful:

- add optional integration adapters;
- do not duplicate their generic red-team attacks;
- translate their outputs into the unified DecGuard report.

The native DecGuard metamorphic engine remains independent.

### Reproducibility

Every generated fuzz run must persist:

- random seed;
- contract version/hash;
- backend metadata;
- transformation parameters;
- source dataset hash;
- results.

A reported failure must be replayable.

### Step-2 CLI

Target commands:

```bash
decguard fuzz <contract>
decguard diff <baseline> <candidate>
decguard test <contract> --all
decguard replay <failure-id-or-file>
```

Exact naming may be adjusted if a cleaner CLI emerges.

### Step-2 acceptance criteria

Step 2 is complete only when:

- option permutation catches an intentionally order-sensitive mock backend;
- a stable mock backend passes the same test;
- probability-distribution drift is measured correctly;
- regression comparison catches controlled degradations;
- a stored failure is reproducible;
- fuzzing is deterministic under a fixed seed;
- reports are machine-readable;
- CI can fail on declared property violations;
- integration tests cover Choice, Noul, and Score.

Commit Step 2 independently before moving on.

---

# STEP 3 — Post-deployment checks and explicit cascade policies

## Goal

Make the same DecGuard reliability model usable **after deployment** without building a SaaS platform.

Users should be able to collect decision records themselves and periodically run DecGuard in:

- CI;
- cron;
- scheduled GitHub Actions;
- manual post-deploy checks;
- release gates.

## Production record format

Define a simple backend-neutral JSONL schema such as:

```json
{
  "timestamp": "...",
  "decision": "refund_request",
  "input": "...",
  "probabilities": {
    "refund": 0.96,
    "reject": 0.02,
    "review": 0.02
  },
  "selected": "refund",
  "backend": "openjev",
  "model": "...",
  "outcome": "refund",
  "outcome_correct": true,
  "metadata": {
    "locale": "it"
  }
}
```

Not every field must be mandatory.

In particular, real outcomes may be unavailable.

### Post-deployment checks

Implement:

```bash
decguard check <contract> --dataset production.jsonl
```

Support:

- calibration on records with observed outcomes;
- accuracy / error rate;
- threshold coverage;
- abstention/fallback rate;
- confidence distribution shift;
- per-segment metrics;
- drift against a baseline dataset or previous report;
- contract PASS/WARN/FAIL.

Keep this batch-oriented.

Do not implement a daemon or hosted ingestion service in v0.1.

### Segmentation

Allow simple metadata-based segmentation:

```yaml
segments:
  - locale
  - customer_tier
```

Surface reliability failures that only occur in specific segments.

Avoid building a generic analytics query language.

### Runtime policy / cascade

Implement an explicit, deterministic policy engine.

Example contract:

```yaml
policy:
  routes:
    - when:
        confidence_gte: 0.95
      action: accept

    - when:
        confidence_gte: 0.75
      action: fallback
      backend: strong_model

    - action: human_review
```

Support at minimum:

- accept;
- abstain;
- fallback backend;
- human/review outcome marker.

The policy engine must be:

- deterministic;
- separately testable;
- easy to embed as a Python library;
- usable without any server.

### Important boundary

Do **not** implement automatic cascade optimization in v0.1.

However, design the report schema so a later optimizer can use:

```text
confidence
correctness
latency
cost
fallback
```

without changing the public record format.

### SDK

Expose a minimal Python API similar to:

```python
guard = DecGuard.from_contract("decguard.yaml")

result = guard.decide(input_data)

if result.action == "accept":
    ...
elif result.action == "fallback":
    ...
```

The CLI and SDK must share the same underlying engine.

### Step-3 acceptance criteria

Step 3 is complete only when:

- production JSONL can be analyzed offline;
- calibration drift can fail a contract;
- segmentation can expose a localized failure;
- the policy engine routes accept/fallback/review correctly;
- the same policy works through CLI tests and Python SDK;
- no central service is required;
- CI examples demonstrate both pre-deploy and post-deploy checks.

Commit Step 3 independently.

---

# Production-readiness requirements

The project may call itself `v0.1` only after all of the following are true.

## Correctness

- strict config validation;
- deterministic seeded tests;
- malformed probability handling;
- graceful backend failures;
- timeouts;
- retry policy only where safe;
- no silently dropped test cases;
- explicit counts for failures/refusals/timeouts.

## Security

- never print secrets;
- environment-variable based credentials;
- sanitize subprocess invocation;
- do not execute arbitrary code from contracts;
- treat external datasets/contracts as untrusted input;
- dependency pinning / lockfile.

## Reproducibility

Every report records:

- DecGuard version;
- contract hash;
- dataset hash where practical;
- backend/model/version;
- transformation seed;
- dependency/integration provenance where relevant.

## Performance

- support concurrent backend calls with configurable limits;
- no uncontrolled concurrency;
- stream datasets where practical;
- avoid loading entire large production datasets unnecessarily.

Do not optimize prematurely.

## UX

A first-time user should be able to:

```bash
pip install decguard
decguard init
decguard test
```

and understand the result without reading source code.

If the final package name is not yet available on PyPI, keep packaging ready without publishing automatically.

## Documentation

Ship:

- README with 5-minute quickstart;
- Decision Contract reference;
- backend adapter guide;
- fuzzing/property reference;
- CI example for GitHub Actions;
- post-deploy dataset example;
- cascade policy example;
- architecture overview;
- integration philosophy explaining which external OSS tools DecGuard reuses instead of replacing.

---

# Recommended repository shape

Use this only as a guide; adapt if a better structure emerges.

```text
decguard/
├── src/decguard/
│   ├── cli/
│   ├── contracts/
│   ├── backends/
│   ├── decisions/
│   ├── metrics/
│   ├── fuzz/
│   ├── regression/
│   ├── reports/
│   ├── policy/
│   ├── production/
│   └── integrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── examples/
├── docs/
├── .github/workflows/
├── pyproject.toml
├── README.md
├── LICENSE
├── CHANGELOG.md
└── AGENTS.md
```

Keep modules small and avoid premature plugin-framework complexity.

---

# Explicit non-goals for v0.1

Do not build:

- a hosted SaaS;
- a web dashboard;
- a centralized database;
- a telemetry ingestion server;
- account/auth/team management;
- automatic alerts;
- automatic threshold/cascade optimization;
- a model-training framework;
- a new Jev-like model;
- a new general-purpose LLM eval framework;
- a new package registry competing with `jev-packs`;
- a generic agent framework.

These may be revisited later only if actual users create the need.

---

# Final validation before release

Before tagging v0.1:

1. run the full test suite;
2. run static typing/linting;
3. test installation in a clean environment;
4. test Linux and macOS at minimum;
5. test offline/mock workflow;
6. test one real external decision backend;
7. run an intentionally broken backend and verify DecGuard catches:
   - option-order instability;
   - probability drift;
   - calibration failure;
   - regression;
8. verify CI exit codes;
9. verify post-deploy analysis;
10. verify cascade routing;
11. audit dependency licenses;
12. inspect security-sensitive code paths;
13. produce a reproducible demo.

The demo should make the value obvious in less than five minutes.

Example:

```text
1. stable model → PASS
2. swap model/version → DecGuard detects hidden option-order regression
3. show minimal failing example
4. show CI failure
5. show post-deployment dataset revealing calibration drift
6. show fallback policy preventing low-confidence automatic action
```

---

# What Codex should return after each step

At the end of each step, return:

1. what was implemented;
2. exact commands to test it;
3. test/CI status;
4. external OSS dependencies/integrations added and why;
5. known limitations;
6. files/architecture added;
7. the next step only.

Do not start the next major step until the current one is internally complete and committed.

---

# Definition of success for DecGuard v0.1

DecGuard v0.1 succeeds if an engineer can use one small configuration to:

> **define a probabilistic AI decision, test its reliability, fuzz its invariants, detect regressions, gate changes in CI, re-check real post-deployment records, and apply deterministic fallback policies — across interchangeable decision-model backends.**

Everything else is secondary.
