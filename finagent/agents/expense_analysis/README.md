# Expense Analysis Agent

The Expense Analysis Agent turns a validated `FinancialProfile` into an
`ExpenseAnalysisResult`. It computes monthly income and expense averages,
category totals, recurring expenses, unusual transactions, and data gaps. An
optional structured LLM step adds qualitative spending patterns and clarifying
questions. It does not create budgets, research financial products, or write
reports.

## Input and Output

Input is `ExpenseAnalysisRequest`, containing the shared `FinancialProfile`
(`profile_id`, currency, transactions, and optional savings goal). Output is the
shared `ExpenseAnalysisResult`, including its `FinancialSummary`, recurring and
unusual transactions, spending patterns, data gaps, analysis version, status,
errors, and limitations.

Category averages are rounded to two decimal places before summing into
`monthly_expenses`, so the shared summary invariants hold exactly. Expenses with
no source category are included in the `other` total and also reported as data
gaps. `analysis_version` is derived from the complete profile content.

Outlier detection uses the modified z-score, with a threshold greater than 3.5
and a minimum sample of five non-recurring expenses. Recurring transactions are
excluded. Possible duplicates share a date, normalized merchant, and amount.
Recurring detection honors explicit `is_recurring=True` and also detects a
normalized identity with stable amounts (within 5% of its median) across at
least two distinct months.

## Graph Nodes

1. `validate_input` checks the request against the shared Pydantic schema.
2. `compute_metrics` computes deterministic metrics without an LLM.
3. `interpret` requests structured qualitative patterns and clarifying questions.
4. `verify_interpretation` drops insights that cite categories or transaction IDs
   absent from the profile.
5. `assemble` returns the shared result model.

## Failure Modes

Invalid requests return `status="failed"` with an `AgentError`; they do not
raise to the caller. If the LLM is unavailable or its call fails, deterministic
results are returned with `status="partial"` and a `Limitation`. Invalid
references in otherwise valid LLM insights are dropped.

## Run

Install the project and development dependencies from the repository root:

```bash
pip install -e ".[dev]"
python examples/run_expense_analysis.py --no-llm
```

The example prints JSON with `mode="deterministic_only"` and never initializes
an LLM when `--no-llm` is supplied. To include interpretation, configure
`LLM_PROVIDER`, `LLM_MODEL`, and the matching provider API key as described in
the repository `.env.example`, then run:

```bash
python examples/run_expense_analysis.py
```

Inject a LangChain chat model through `build_expense_analysis_graph(llm=...)`
or `run_expense_analysis(request, llm=...)` for tests; no provider is needed for
the deterministic calculation functions.

Run the repository test suite with `pytest`. The optional live smoke test is
opted into with `FINAGENT_RUN_LIVE_TESTS=1` and requires provider configuration.