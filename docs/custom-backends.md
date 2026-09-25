---
description: Connect a model through Python - wrap a function with CallableBackend, or package a DecisionBackend plugin usable from contracts and the CLI.
---

# Custom backends

When a model is reachable from Python, you can connect it without an HTTP endpoint:

- **[`CallableBackend`](#python-callable)** wraps a plain function. It is for the Python
  API (tests, notebooks, the SDK), not for contracts.
- **[Plugin backends](#plugin-backends)** are `DecisionBackend` subclasses in an installed
  package, registered under the `decguard.backends` entry-point group. Contracts and the
  CLI use them by `provider` name.

Contracts never reference Python import paths. A contract is data and must not be able to
run arbitrary code, so the only way to make Python code available to contracts is an
installed package that registers it.

## The interface

```python
class DecisionBackend:
    provider: ClassVar[str]

    def predict(self, request: DecisionRequest) -> Prediction: ...  # implemented by adapters
    def decide(self, request, *, tolerance) -> DecisionResult: ...  # shared: timing + validation
    def metadata(self) -> BackendMetadata: ...  # provenance for reports
    def healthcheck(self) -> HealthStatus: ...  # ok / unhealthy / unknown
    def close(self) -> None: ...  # release resources
```

Adapters implement **`predict`** and return raw probabilities. The shared `decide`
measures latency, validates the probabilities and builds the
[`DecisionResult`](./decisions.md#the-normalized-decisionresult), so results cannot
diverge between backends.

- **`DecisionRequest`** has `case_id`, `decision` (a spec with `name`, `type` and
  `labels`) and `input` (a string or a dict).
- **`request.decision.labels`** are the labels **in the order and form to present**. While
  fuzzing, [`option_order`](./properties.md#option-order) and
  [`label_format`](./properties.md#label-format) reorder or reformat them. Key your
  probabilities by these labels exactly; DecGuard maps them back to the contract labels.
- **`Prediction`** has `probabilities` (a mapping label → probability) and optional
  `model`, `model_version` and `metadata`.
- Raise `decguard.errors.BackendError` (or `BackendTimeout`, `BackendUnavailable`,
  `InvalidResponse`) for a failure that concerns one request; it becomes a per-case error.
  Any other exception is recorded as an `exception` error for that case.
- `predict` is called from several threads at once, up to `evaluation.max_concurrency`, so
  it must be thread-safe.

## Python callable

Wrap any function that takes a `DecisionRequest` and returns a mapping of label to
probability, or a `Prediction`:

```python
from decguard.backends import CallableBackend
from decguard.engine import run_test


def decide(request):
    # request.decision.labels: the labels to answer for, as presented
    return {"refund": 0.7, "reject": 0.1, "review": 0.2}


report = run_test("decguard.yaml", backend=CallableBackend(decide, model="rules-v2"))
print(report.status, report.metrics.classification.accuracy)
```

`run_test` is the engine behind the CLI. It takes the same inputs as `decguard test` —
`dataset`, `backend` (a name or an instance), `max_concurrency`, `check_health`,
`mode` (`"test"`, `"fuzz"` or `"all"`), `seed`, `properties`, `minimize` — and returns the
`Report`. The same `CallableBackend` works with the runtime
[SDK](./policy.md#python-sdk): `DecGuard.from_contract("decguard.yaml", backend=CallableBackend(decide))`.

## Plugin backends

A plugin is a normal Python package. This one loads a local model lazily and exposes it
as `provider: localmodel`:

```python
# decguard_localmodel/__init__.py
import threading
from typing import Self

from pydantic import BaseModel, ConfigDict

from decguard.backends import DecisionBackend, HealthStatus, validate_settings
from decguard.decisions import DecisionRequest, Prediction


class LocalModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")  # typos in the contract are errors
    checkpoint: str
    device: str = "cpu"


class LocalModelBackend(DecisionBackend):
    provider = "localmodel"

    def __init__(self, settings: LocalModelSettings, *, name: str, model: str | None) -> None:
        super().__init__(name=name, model=model)
        self.settings = settings
        self._model = None
        self._lock = threading.Lock()

    @classmethod
    def from_config(cls, config, *, name, decision) -> Self:
        # Validate settings only. No network or model loading here: `decguard validate`
        # builds every backend and must stay offline.
        settings = validate_settings(LocalModelSettings, config, name=name)
        return cls(settings, name=name, model=config.model)

    def _loaded(self):
        with self._lock:  # predict() is called from several threads
            if self._model is None:
                self._model = load_my_model(self.settings.checkpoint, self.settings.device)
            return self._model

    def predict(self, request: DecisionRequest) -> Prediction:
        options = list(request.decision.labels)  # in the order and form to present
        probabilities = self._loaded().predict(request.input, options)
        return Prediction(probabilities=probabilities, model_version=self.settings.checkpoint)

    def healthcheck(self) -> HealthStatus:
        self._loaded()
        return HealthStatus(status="ok", detail=f"loaded {self.settings.checkpoint}")
```

Register it in the package's `pyproject.toml`:

```toml
[project.entry-points."decguard.backends"]
localmodel = "decguard_localmodel:LocalModelBackend"
```

Once the package is installed in the same environment as DecGuard, any contract can use
it. Keys besides `provider` and `model` are passed to your settings model:

```yaml
backend:
  provider: localmodel
  model: refund-local
  checkpoint: ./checkpoints/refund-v3
  device: cpu
```

`validate_settings` reports errors against the contract path, like the built-in backends:

```text
error: invalid settings for provider 'localmodel':
  backend.devcie: unknown field (check the spelling)
```

Rules for plugins:

- `from_config` must not do network I/O or load models, so `decguard validate` works
  offline. Do that lazily in `predict` or `healthcheck`.
- Built-in provider names (`mock`, `http`, `systemone`) cannot be shadowed.
- An unknown provider name is a configuration error (exit `2`) that lists the available
  providers.
- Override `metadata()` to add provenance (for example a model hash) to reports, and
  `close()` to release resources.

## Paraphrase plugins

The [`paraphrase`](./properties.md#paraphrase) property has its own extension point: a
`decguard.fuzz.paraphrase.Paraphraser` subclass registered under the
`decguard.paraphrasers` entry-point group.
