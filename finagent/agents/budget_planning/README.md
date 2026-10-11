# Budget Planning Agent

The Budget Planning Agent consumes a validated `BudgetRequest` and an existing
`ExpenseAnalysisResult`. It never recomputes expense analysis, performs research,
or generates reports. It returns a shared `BudgetPlan`, including revision
metadata when replanning against a newer analysis.

## Interface

```python
from finagent.agents.budget_planning import run_budget_planning, revise_budget

plan = run_budget_planning(request, llm=my_chat_model)
updated = revise_budget(plan, newer_expense_analysis, llm=my_chat_model)
```

`BudgetRequest` supports an optional `savings_goal`, an optional override for
`essential_categories`, and an optional currency that is validated against the
source analysis. Without a goal, the planner assumes savings of 20% of income
and records that assumption. The deterministic baseline is also available
through `baseline_allocation`; it uses Decimal arithmetic and a default
discretionary floor of 40% of current average category spend. The floor rate
can be changed when calling that function.

## Graph

`build_budget_graph(llm=None)` builds these nodes:

1. `validate_request` rejects malformed, failed, incomplete, versionless, or
   currency-mismatched source analyses.
2. `baseline` calculates a deterministic allocation and feasibility.
3. `propose` optionally asks a structured LLM for per-category discretionary
   limits, rationales, assumptions, and trade-offs.
4. `verify` checks the proposal bounds and all budget invariants; any invalid
   proposal falls back to the deterministic baseline with a `Limitation`.
5. `assemble` returns the shared `BudgetPlan`.

Pass `llm=False` to `build_budget_graph` or `run_budget_planning` for
deterministic baseline-only operation. With the default `llm=None`, the
configured provider is initialized lazily. LLM configuration failures preserve
the deterministic plan and are reported as a limitation.

## Invariants and feasibility

- Essentials default to housing, utilities, groceries, healthcare, insurance,
  debt payments, transport, and education; their current average spend is
  preserved.
- Discretionary categories are reduced proportionally toward the savings goal,
  but not below the configured floor.
- Category limits are non-negative, cover every category in the analysis, and
  category limits plus planned savings cannot exceed monthly income.
- The feasibility result reports the maximum savings possible without cutting
  essentials or crossing discretionary floors. An infeasible target is never
  silently lowered; the plan includes the shortfall and suggestions.
- If essential obligations and required floors themselves exceed income, no
  valid plan can satisfy both preservation and the shared plan invariants. The
  agent returns a structured failed result rather than cutting essentials.

The `budget_id` is a deterministic `bp-...` version of source analysis
version, target, effective preferences, and revision number.

## Revisions

`revise_budget(previous, new_analysis, llm=None)` keeps the previous savings
target and essential-category preferences. A new analysis version produces a
revision number increment, sets `parent_budget_id`, updates the source
analysis version, and lists deterministic per-category limit deltas. An
unchanged analysis version retains the plan and adds an informational
`revision_not_needed` limitation instead of creating a new revision.

## Run

From the repository root:

```bash
python examples/run_budget_planning.py --no-llm
python examples/run_budget_planning.py
pytest tests/agents/test_budget_allocation.py tests/agents/test_budget_graph.py
```

The example builds source analyses from deterministic expense calculations;
it does not run or duplicate the Expense Analysis Agent. Provider-assisted mode
requires the usual `LLM_PROVIDER`, `LLM_MODEL`, and provider API key settings.
