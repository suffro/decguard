<!-- Condensed from `decguard test examples/refund/decguard.yaml --all` (real run). -->
<template>
  <figure class="dg-terminal" aria-label="Installing DecGuard and running a contract">
    <div class="dg-terminal-bar" aria-hidden="true">
      <span /><span /><span />
    </div>
    <pre><code><span class="dg-prompt">$</span> pip install decguard
<span class="dg-prompt">$</span> decguard test decguard.yaml --all

<span class="dg-dim">refund_request (choice)</span>
<span class="dg-pass">PASS</span>  min_accuracy   1.000 ≥ 0.9
<span class="dg-pass">PASS</span>  max_ece        0.139 ≤ 0.15
<span class="dg-pass">PASS</span>  min_coverage   0.727 ≥ 0.5
<span class="dg-pass">PASS</span>  option_order   0 / 33 violating
<span class="dg-pass">PASS</span>  whitespace     0 / 22 violating

<span class="dg-pass">PASS</span>: all gates hold</code></pre>
    <figcaption>Condensed output of the refund example</figcaption>
  </figure>
</template>
