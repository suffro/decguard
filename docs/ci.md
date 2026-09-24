# DecGuard in CI (GitHub Actions)

Exit codes are the interface: **0** pass (or warn), **1** a reliability gate or property
failed, **2** the run could not be evaluated. A job therefore fails whenever the model
breaks the contract, and fails differently (2) when the configuration is broken.

```yaml
name: decision-model
on: [pull_request]

jobs:
  decguard:
    runs-on: ubuntu-latest
    env:
      DECISIONS_TOKEN: ${{ secrets.DECISIONS_TOKEN }}   # referenced by bearer_token_env
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv tool install git+https://github.com/suffro/decguard

      - name: Validate the contract (offline)
        run: decguard validate decguard.yaml

      - name: Golden gates and metamorphic properties
        run: decguard test decguard.yaml --all --backend candidate --output candidate.json

      - name: Regression against the production model
        if: always()
        run: |
          decguard test decguard.yaml --backend production --output baseline.json
          decguard diff baseline.json candidate.json --contract decguard.yaml --output diff.json

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: decguard
          path: |
            candidate.json
            baseline.json
            diff.json
```

- Pin a `fuzz.seed` in the contract (or pass `--seed`) so every CI run checks the same
  transformations; change it deliberately to explore new ones.
- Keep the JSON reports as artifacts. A failure can then be reproduced locally with
  `decguard replay candidate.json`.
- `--fail-on-warn` turns warning gates into failures, for a stricter main branch.
