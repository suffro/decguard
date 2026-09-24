# Architecture and integration philosophy

DecGuard is a local Python library and CLI around a small provider-neutral core:

```text
Decision Contract
      |
      +--> backend adapter --> normalized DecisionResult --> golden/property report
      |
production JSONL -----------------------------------------> production report
      |
DecisionResult + explicit policy ------------------------> route directive
```

- Contracts own typed decision semantics, reliability gates, metamorphic properties,
  post-deployment checks and deterministic policies.
- Thin adapters normalize local functions, HTTP/System-One-compatible endpoints and
  third-party `decguard.backends` entry points into `DecisionResult`.
- Golden testing, fuzzing, diff/replay and production checks emit versioned JSON plus a
  concise terminal view with consistent PASS/WARN/FAIL exit semantics.
- The CLI and Python SDK call the same engines. No server, database, telemetry collector,
  GPU, paid model or hosted account is required.

DecGuard deliberately does not recreate model servers, generic red-team frameworks,
training systems or observability platforms. External projects can plug in at the backend
or paraphrase-provider boundaries; DecGuard retains the decision-specific contract,
normalization, comparison, gating and reproducibility layer. The default core remains
usable when no optional integration is installed.
