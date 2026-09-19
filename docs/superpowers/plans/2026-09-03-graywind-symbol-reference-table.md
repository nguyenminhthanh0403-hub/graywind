# Symbol Reference Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standing, static symbol-reference table to the Graywind dashboard (`index.html`) so the owner can read what each candidate symbol is, its sector/tier, and what to watch — every time they check the site, without digging through docs.

**Architecture:** Pure static content, no live data. A new JS data array (`SYMBOL_REFERENCE_DATA`) feeds a new `buildSymbolReference()` render function, following the exact pattern of the existing `buildPositions`/`buildTradeLog`/`buildPerformanceReport` functions in `index.html`. Rendered once into a new top-level `<section>`, above the per-account `accounts-grid`, since the same symbol universe applies to both the $100k and $2k accounts — not duplicated inside `renderAccount()`.

**Tech Stack:** Vanilla JS, inline in `index.html` (no build step, no frontend test framework in this repo — verification is via headless Chrome rendering, not pytest).

**Spec:** `docs/superpowers/graywind-tactical-diversification-handoff.md` (section "Dashboard symbol-reference table — content, ready to implement") — the table content and implementation sketch below are copied verbatim from there; this plan only adds the step-by-step execution path.

## Global Constraints

- Content is **static reference copy**, not live/fetched data — no new CSV/JSON source, no `fetch()` call.
- Must not touch any of the existing per-account render paths (`buildPositions`, `buildTradeLog`, `buildPerformanceReport`, `renderAccount`, `loadAccount`, `main`'s two `loadAccount()` calls) — this is strictly additive.
- Must render identically for both accounts (once, not per-account) — do not place it inside `renderAccount()` or `#account-100k`/`#account-small`.
- Reuse existing table CSS (`.table-wrap`, `table`, `th`, `td`, `.symbol-tag`) — no new CSS classes needed unless a real gap shows up during verification.
- The 13-row table content (symbol/sector/tier/what-it-is/what-to-watch) is fixed by the spec — do not paraphrase or drop rows.

---

### Task 1: Add the symbol-reference data, render function, and static container

**Files:**
- Modify: `index.html:275-278` (static HTML — insert a new `<section>` before `<main id="app">`)
- Modify: `index.html` (JS section, after `buildPerformanceReport`, i.e. after line 548's closing of that function — add `SYMBOL_REFERENCE_DATA` and `buildSymbolReference()`)
- Modify: `index.html:682-687` (`main()` — call the new render function)

**Interfaces:**
- Produces: `SYMBOL_REFERENCE_DATA` (array of 13 row objects: `{symbol, sector, tier, what, watch}`) and `buildSymbolReference()` (no args, returns an HTML string for the table `<section>`) — both consumed only within this task, no other task depends on them.

- [ ] **Step 1: Add the static container to the HTML**

In `index.html`, immediately before the existing `<main id="app" ...>` block (currently `index.html:275`), add a new sibling section:

```html
  <section id="symbol-reference" aria-labelledby="symbol-reference-head"></section>

  <main id="app" aria-busy="true" class="accounts-grid">
```

(Leave the existing `<main id="app">...</main>` block exactly as-is below it.)

- [ ] **Step 2: Add the data array and render function**

In the `<script>` block, immediately after the closing `}` of `buildPerformanceReport` (currently `index.html:548`, the line reading `}` right before `function renderEquityChart`), insert:

```javascript
const SYMBOL_REFERENCE_DATA = [
  { symbol: "AAPL", sector: "tech", tier: "2", what: "iPhone/hardware ecosystem + services", watch: "Single-product concentration (iPhone still >50% of revenue); China exposure cuts both ways (manufacturing + sales market)" },
  { symbol: "NVDA", sector: "tech", tier: "2", what: "AI/datacenter GPU supplier, dominant position", watch: "Priced for perfection — any AI-capex slowdown from hyperscaler customers hits it disproportionately; export-control risk on China sales" },
  { symbol: "MSFT", sector: "tech", tier: "2", what: "Cloud (Azure) + enterprise software + OpenAI stake", watch: "Azure capex is a bet on AI demand materializing; EU/US antitrust scrutiny" },
  { symbol: "XOM", sector: "energy", tier: "2", what: "Integrated oil major", watch: "Tracks crude price directly — no oil-specific gate exists in Graywind yet, so this trades blind to OPEC+ decisions" },
  { symbol: "CVX", sector: "energy", tier: "2", what: "Integrated oil major", watch: "Highly correlated with XOM — holding both isn't much more diversification than one twice" },
  { symbol: "JNJ", sector: "health", tier: "2", what: "Diversified pharma + medtech", watch: "Litigation overhang (talc lawsuits recurring headline risk); patent-cliff risk on individual drugs" },
  { symbol: "UNH", sector: "health", tier: "2", what: "Largest US health insurer", watch: "Sensitive to US healthcare policy/regulation headlines (Medicare Advantage rates, DOJ scrutiny); real earnings-day volatility" },
  { symbol: "CEG", sector: "nuclear", tier: "2", what: "Largest US nuclear power generator", watch: "Increasingly an AI-capex proxy via datacenter power-purchase-agreement headlines (Microsoft, Meta); regulatory approval risk on those deals" },
  { symbol: "CCJ", sector: "nuclear", tier: "2", what: "Largest western uranium miner/fuel supplier", watch: "Tracks uranium spot price, not electricity price — different driver than CEG; geopolitical supply risk (Kazakhstan/Russia)" },
  { symbol: "RGTI", sector: "quantum", tier: "2", what: "Rigetti Computing, superconducting-qubit hardware", watch: "Narrative/hype stock — moves on quantum-computing headlines unrelated to its own fundamentals; heavy retail-trader gap risk" },
  { symbol: "SERV", sector: "robotics", tier: "3", what: "Serve Robotics, AI sidewalk delivery", watch: "Small-cap, single-customer-concentrated (Uber Eats), pre-profitability — the deliberate \"gamble\" slot" },
  { symbol: "QUBT", sector: "quantum", tier: "3", what: "Quantum Computing Inc., photonic/quantum-inspired", watch: "Extreme volatility (52-week range $6.18–$25.84); dilution risk — small quantum names frequently raise capital via share offerings" },
  { symbol: "SPY", sector: "—", tier: "1", what: "S&P 500 index ETF, buy-and-hold core", watch: "70% of every account's capital; deliberately ungated (two tested VIX/macro exposure-scaling variants both washed on Calmar ratio, see graywind-edge-thesis.md)" },
];

function buildSymbolReference() {
  const rows = SYMBOL_REFERENCE_DATA.map(r => `<tr>
      <td class="symbol-tag">${r.symbol}</td>
      <td>${r.sector}</td>
      <td class="num">${r.tier}</td>
      <td style="white-space:normal">${r.what}</td>
      <td style="color:var(--txt-2);white-space:normal">${r.watch}</td>
    </tr>`).join("");

  return `
    <div class="section-head"><h2 id="symbol-reference-head">Symbol Reference</h2></div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Symbol</th><th>Sector</th><th class="num">Tier</th>
          <th>What it is</th><th>What to watch</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}
```

Note: `what`/`watch` cells override the table CSS's default `white-space: nowrap` (see `index.html:197`) with inline `white-space:normal`, since these are prose sentences, not short data values like the other tables' cells — without this override the row would force horizontal scroll instead of wrapping.

- [ ] **Step 3: Wire the render call into `main()`**

Modify `main()` (currently `index.html:682-685`) from:

```javascript
function main() {
  loadAccount("100k", "$100k Account", "dashboard-data", document.getElementById("account-100k"));
  loadAccount("small", "$2k Account", "dashboard-data/small", document.getElementById("account-small"));
}
```

to:

```javascript
function main() {
  document.getElementById("symbol-reference").innerHTML = buildSymbolReference();
  loadAccount("100k", "$100k Account", "dashboard-data", document.getElementById("account-100k"));
  loadAccount("small", "$2k Account", "dashboard-data/small", document.getElementById("account-small"));
}
```

- [ ] **Step 4: Verify via headless Chrome rendering**

This repo has no JS test framework, so verification is a real render check, not a unit test. Use the `headless-chrome-verification` skill (or a plain local server + headless Chrome) to:

```bash
python3 -m http.server 8000
```

Then load `http://localhost:8000/index.html` in headless Chrome and confirm via the DOM:
- `#symbol-reference` exists and contains a `<table>` with exactly 13 `<tbody>` rows.
- The first row's `.symbol-tag` cell reads `AAPL` and the last row's reads `SPY`.
- Both `#account-100k` and `#account-small` still render their normal content (positions/trades/performance) unchanged — confirming this addition didn't break existing account loading.
- Take a screenshot to visually confirm the table sits above the two-column accounts grid, not inside it, and that `what`/`watch` text wraps instead of forcing horizontal scroll.

Expected: all four checks pass. If the table cells force horizontal scroll instead of wrapping, double check the inline `white-space:normal` override from Step 2 made it into both the `what` and `watch` `<td>` elements.

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "$(cat <<'EOF'
Add static symbol-reference table to dashboard

Owner-requested standing panel listing every candidate symbol (current
+ diversification-decision candidates) with sector/tier/what-to-watch,
so it's readable on the site itself instead of buried in a handoff doc.
Static content only — no live data, no trading-logic changes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014zxa4aam7zKTRUR3GCUGkr
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** The spec section ("Dashboard symbol-reference table — content, ready to implement") specifies exactly one deliverable — the table — with content, placement (top-level, not per-account), and implementation sketch (new build function alongside the existing three, static JS array, no fetch). Task 1 covers all of it in one pass; there is no second subsystem to split out.
- **Placeholder scan:** No TBD/TODO; all 13 rows and both functions are written out in full, not summarized.
- **Type consistency:** `SYMBOL_REFERENCE_DATA` fields (`symbol`, `sector`, `tier`, `what`, `watch`) are used identically in the one place that consumes them (`buildSymbolReference`) — single task, no cross-task drift possible.

## Explicitly out of scope for this plan

Per the handoff, everything else is gated or needs a separate decision and does **not** belong in this plan:
- Symbol promotion into `tier_config.py`/`sector_config.py`/`live_loop.py`'s `WATCHLIST` — blocked on burn-in (8/20 trades logged as of the handoff; won't clear by 2026-09-14 on trade-count alone per `graywind-real-capital-done-criteria.md`) and on a live `validate_symbol_addition()` re-run, not this table's content.
- Bullion↔Graywind sector-signal integration — explicitly flagged as needing its own `superpowers:brainstorming` session.
- The stray uncommitted diff in `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` — a doc-hygiene cleanup, unrelated to this feature.
