# Financial Report Agent

The Financial Report Agent takes a shared `ReportRequest`, validates consistency
across the existing expense analysis, budget plan, and optional financial
research result, then composes a report. It never recalculates upstream
financial numbers, performs research, or silently accepts stale or inconsistent
inputs.

## Interface

```python
from finagent.agents.financial_report import run_financial_report

report = run_financial_report(request, llm=my_chat_model)
```

`build_report_graph(llm=None)` builds a LangGraph `StateGraph`. The LLM
contributes only qualitative summary, spending insights, savings opportunities,
and risk considerations. Budget overview, findings, sources, and assumptions
are copied directly from upstream models. If no LLM is injected, the configured
FinAgent provider is created lazily. Pass `llm=False` to deliberately use the
deterministic qualitative template without initializing a provider.

## Validation codes

| Code | Severity | Meaning |
| --- | --- | --- |
| `STALE_BUDGET` | Error | Budget source analysis version differs from expense analysis. |
| `STALE_ANALYSIS` | Error | Analysis version differs from `expected_analysis_version`. |
| `CURRENCY_MISMATCH` | Error | Budget and analysis currencies differ. |
| `PERIOD_MISMATCH` | Error | Budget category current-spending averages differ from analysis category totals. |
| `ANALYSIS_FAILED` / `BUDGET_FAILED` | Error | An upstream financial calculation failed. |
| `MISSING_ANALYSIS_VERSION` / `MISSING_BUDGET_VERSION` | Error | A required upstream version is absent. |
| `MISSING_ANALYSIS_SUMMARY` | Error | Expense analysis has no summary. |
| `SURPLUS_INCONSISTENT` / `EXPENSE_TOTAL_INCONSISTENT` | Error | Analysis totals do not reconcile. |
| `BUDGET_OVER_INCOME` | Error | Category limits and savings exceed budget income. |
| `RESEARCH_MISSING` / `RESEARCH_FAILED` / `RESEARCH_PARTIAL` | Warning | Evidence is absent or incomplete. |
| `ANALYSIS_PARTIAL` / `BUDGET_PARTIAL` | Warning | An upstream financial result is partial. |
| `UNRESOLVED_DATA_GAPS` | Warning | The analysis has open data gaps. |
| `INFEASIBLE_SAVINGS` | Warning | The requested savings goal is infeasible. |
| `SOURCE_URL_MISSING` | Warning | A finding's cited source has no usable URL. |

The shared budget schema does not carry an explicit period field. The report
agent checks period consistency through the budget's deterministic
`current_monthly_spend` category values against the analysis period averages,
in addition to requiring the budget to reference the exact analysis version.

## Status semantics

- Validation errors produce `validation_status="rejected"`,
  `status="failed"`, `sections=None`, and `report_version=None`. Composition is
  skipped.
- Validation warnings produce `validation_status="flagged"` and a produced
  report with `status="partial"`; warning issues are retained.
- No validation issues yields `validation_status="valid"` and normally
  `status="success"`.
- LLM failure uses a deterministic, qualitative template and a
  `llm_composition_unavailable` limitation. Any narrative number emitted by
  the LLM causes the narrative to use the template instead.
- Deliberate `llm=False` mode uses the same template without a failure
  limitation.
- Unknown URLs and source IDs in generated narrative text are stripped. The
  structured budget and research sections remain direct copies of upstream
  outputs.

`report_version` is computed from the analysis version, budget ID/revision,
and normalized research content, excluding retrieval timestamps.

## Run

```bash
python examples/run_financial_report.py --no-llm
pytest tests/agents/test_report_validation.py tests/agents/test_report_graph.py
```

The example demonstrates consistent financial inputs and a stale-budget
rejection using local deterministic upstream calculations. Since it does not
perform research, the first report is flagged with `RESEARCH_MISSING`, as
required by validation semantics. For provider-assisted qualitative
composition, configure `LLM_PROVIDER`, `LLM_MODEL`, and the matching provider
API key.
