"""Build fresh research context from the caller's scoped repository."""
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.schemas.financial import FinancialProfile
from finagent.schemas.research import ResearchFinancialContext


def build_research_context(repository, profile_id: str) -> dict:
    record = repository.get_profile(profile_id)
    if record is None:
        raise ValueError("Profile was not found.")
    profile = dict(record["profile"])
    profile["transactions"] = [row["transaction"] for row in repository.get_transactions(profile_id)]
    context = ResearchFinancialContext(
        savings_goal=profile.get("savings_goal"), is_sample=record.get("is_sample", False),
        data_notes=["Balances, debts, dependants and risk tolerance are unknown unless you provide them. "
                    "Transaction averages describe the recorded period, not guaranteed future income."],
    )
    if not profile["transactions"]:
        context.data_notes.append("No saved transactions: ask for income and spending before estimating affordability.")
        return context.model_dump(mode="json")
    metrics = compute_expense_metrics(FinancialProfile.model_validate(profile))
    context.summary = metrics.summary
    if metrics.data_gaps:
        context.data_notes.append(f"{len(metrics.data_gaps)} transaction details need review; categories may be incomplete.")
    if metrics.unusual_transactions:
        context.data_notes.append("Possible duplicate or unusual transactions need review; totals include all saved entries.")
    budgets, _ = repository.list_budgets(profile_id=profile_id, limit=1, offset=0)
    if budgets:
        budget = budgets[0]["result"]
        if budget.get("status") != "failed" and budget.get("source_analysis_version") == metrics.analysis_version:
            context.budget = budget
        else:
            context.data_notes.append("Previous budget is stale and was excluded. Recreate it using current transactions.")
    return context.model_dump(mode="json")
