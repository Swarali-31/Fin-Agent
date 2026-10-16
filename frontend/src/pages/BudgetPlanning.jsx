import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ChartCard from "../components/ChartCard.jsx";
import DataTable from "../components/DataTable.jsx";
import { Empty, ErrorState, Loading, Warning } from "../components/StateViews.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { ApiError } from "../services/api.js";
import { createBudget, reviseBudget } from "../services/agents.js";
import { getBudgetHistory, listBudgets } from "../services/budgets.js";
import { getLatestExpenseAnalysis } from "../services/profiles.js";

const PROFILE_KEY = "finagent.profileId";
const CATEGORIES = [
  "housing", "groceries", "utilities", "transport", "dining", "entertainment",
  "healthcare", "education", "insurance", "debt_payment", "subscriptions",
  "shopping", "travel", "other",
];

function getStoredProfile() {
  try {
    return window.localStorage.getItem(PROFILE_KEY) ?? "";
  } catch {
    return "";
  }
}

function amountOf(value) {
  return value && typeof value === "object" ? value.amount : value;
}

function formatMoney(value, currency) {
  if (value === undefined || value === null || !currency) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(number);
  } catch {
    return `${currency} ${String(value)}`;
  }
}

function errorMessage(error) {
  if (error instanceof ApiError && error.code === "persistence_not_configured") {
    return "Your saved workspace is unavailable. Ask the workspace owner to check the database connection.";
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function unwrapAnalysis(record) {
  if (!record?.result) return record;
  return {
    ...record.result,
    is_current: record.is_current,
    analysis_version: record.analysis_version ?? record.result.analysis_version,
    status: record.status ?? record.result.status,
  };
}

function unwrapBudget(value) {
  if (value?.result) return value.result;
  return value;
}

function unwrapAgentResponse(value) {
  return value?.result ? value : { status: value?.status ?? "unknown", result: value };
}

export default function BudgetPlanning() {
  const [profileId, setProfileId] = useState(getStoredProfile);
  const [profileInput, setProfileInput] = useState(getStoredProfile);
  const [analysis, setAnalysis] = useState(null);
  const [budget, setBudget] = useState(null);
  const [latestBudget, setLatestBudget] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [goalMode, setGoalMode] = useState("amount");
  const [goalValue, setGoalValue] = useState("");
  const [overrideEssentials, setOverrideEssentials] = useState(false);
  const [essentialCategories, setEssentialCategories] = useState([]);

  const load = useCallback(async (selectedProfileId) => {
    if (!selectedProfileId) {
      setAnalysis(null);
      setBudget(null);
      setLatestBudget(null);
      setHistory([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setHistoryError("");
    try {
      const [analysisResponse, budgetResponse] = await Promise.all([
        getLatestExpenseAnalysis(selectedProfileId),
        listBudgets({ profile_id: selectedProfileId, page: 1, page_size: 20 }),
      ]);
      const latestAnalysis = unwrapAnalysis(analysisResponse);
      const budgetItems = budgetResponse?.items ?? [];
      const latestBudgetRecord = budgetItems[0] ?? null;
      const latestBudget = unwrapBudget(latestBudgetRecord);
      setAnalysis(latestAnalysis);
      setBudget(latestBudget);
      setLatestBudget(latestBudget);
      if (latestBudget) {
        setGoalMode("amount");
        setGoalValue(String(latestBudget.feasibility?.requested_monthly_savings?.amount ?? ""));
        setEssentialCategories(latestBudget.essential_categories || []);
      }
      setStatus(latestBudget?.status ?? null);
      if (latestBudget?.budget_id) {
        setHistory(budgetItems);
        try {
          const historyResponse = await getBudgetHistory(latestBudget.budget_id);
          setHistory([...new Map([...budgetItems, ...(Array.isArray(historyResponse) ? historyResponse : [])].map((record) => [unwrapBudget(record).budget_id, record])).values()]);
        } catch { setHistoryError("Older revisions could not be loaded. Recent saved versions are shown."); }
      } else {
        setHistory(budgetItems);
      }
    } catch (loadError) {
      setError(loadError.code === "analysis_not_found" ? null : loadError);
      setAnalysis(null);
      setBudget(null);
      setLatestBudget(null);
      setHistory([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(profileId);
  }, [profileId, refreshKey, load]);

  const analysisVersion = analysis?.analysis_version ?? null;
  const budgetSourceVersion = budget?.source_analysis_version ?? null;
  const analysisStale = analysis?.is_current === false;
  const stale = Boolean(analysisVersion && budgetSourceVersion && analysisVersion !== budgetSourceVersion);
  const viewingHistory = Boolean(budget && latestBudget && budget.budget_id !== latestBudget.budget_id);
  const summary = analysis?.summary;
  const currency = summary?.currency ?? budget?.currency ?? "";
  const income = amountOf(summary?.monthly_income);
  const categoryLimits = budget?.category_limits ?? [];
  const actualRows = useMemo(
    () => categoryLimits.map((item) => ({
      category: item.category,
      classification: item.is_essential ? "Essential" : "Discretionary",
      actual: Number(amountOf(item.current_monthly_spend)),
      limit: Number(amountOf(item.monthly_limit)),
      actualLabel: amountOf(item.current_monthly_spend),
      limitLabel: amountOf(item.monthly_limit),
    })),
    [categoryLimits],
  );
  const availableCategories = useMemo(
    () => [...new Set([
      ...Object.keys(summary?.category_totals ?? {}),
      ...categoryLimits.map((item) => item.category),
      ...CATEGORIES,
    ])],
    [summary, categoryLimits],
  );

  function handleProfileSubmit(event) {
    event.preventDefault();
    const selected = profileInput.trim();
    if (!selected) return;
    try {
      window.localStorage.setItem(PROFILE_KEY, selected);
    } catch {
      // Profile can still be selected for this page session.
    }
    setProfileId(selected);
  }

  function toggleEssential(category) {
    setEssentialCategories((current) =>
      current.includes(category)
        ? current.filter((item) => item !== category)
        : [...current, category],
    );
  }

  function buildGoal() {
    if (!goalValue.trim()) return null;
    if (goalMode === "amount") return Number.isFinite(Number(goalValue)) && Number(goalValue) > 0 ? { monthly_target: { amount: goalValue.trim() } } : null;
    const rate = Number(goalValue);
    if (!Number.isFinite(rate) || rate <= 0 || rate > 100) return null;
    return { target_rate: String(rate / 100) };
  }

  async function handleCreate(event) {
    event.preventDefault();
    if (!analysis || !profileId || analysisStale) return;
    const savingsGoal = buildGoal();
    if (goalValue.trim() && !savingsGoal) {
      setError(new Error("Savings goal must be a positive amount or a rate between 0 and 100 percent."));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = {
        savings_goal: savingsGoal,
        essential_categories: overrideEssentials ? essentialCategories : null,
      };
      const response = unwrapAgentResponse(budget ? await reviseBudget({ previous: budget, new_analysis: analysis, ...payload }, profileId) : await createBudget({
        expense_analysis: analysis,
        savings_goal: savingsGoal,
        essential_categories: overrideEssentials ? essentialCategories : null,
        currency: summary?.currency,
      }, profileId));
      setBudget(response.result);
      setStatus(response.status ?? response.result?.status ?? "unknown");
      if (response.status === "failed") {
        setError(new Error(response.errors?.[0]?.message ?? "The budget agent reported failed status."));
      }
      setRefreshKey((value) => value + 1);
    } catch (createError) {
      setError(createError);
    } finally {
      setSaving(false);
    }
  }

  async function handleRevise() {
    if (!budget || !analysis || !profileId) return;
    setSaving(true);
    setError(null);
    try {
      const response = unwrapAgentResponse(await reviseBudget({
        previous: budget,
        new_analysis: analysis,
      }, profileId));
      setBudget(response.result);
      setStatus(response.status ?? response.result?.status ?? "unknown");
      if (response.status === "failed") {
        setError(new Error(response.errors?.[0]?.message ?? "The budget agent reported failed status."));
      }
      setRefreshKey((value) => value + 1);
    } catch (revisionError) {
      setError(revisionError);
    } finally {
      setSaving(false);
    }
  }

  const columns = [
    { key: "category", header: "Category", render: (row) => row.category.replaceAll("_", " ") },
    { key: "is_essential", header: "Allocation", render: (row) => row.is_essential ? "Essential" : "Flexible" },
    { key: "current_monthly_spend", header: "Actual", numeric: true, render: (row) => formatMoney(row.current_monthly_spend?.amount, currency) },
    { key: "monthly_limit", header: "Monthly limit", numeric: true, render: (row) => formatMoney(row.monthly_limit?.amount, currency) },
    { key: "rationale", header: "Rationale" },
  ];

  return (
    <div className="space-y-6">
      <section>
        <h1 className="page-title">Budget Planning</h1>
        <p className="mt-2 text-sm text-slate-600">Create a plan based on your latest spending. Add your income and expenses first so the budget reflects what you can actually afford.</p>
      </section>

      <div className="flex flex-wrap gap-4 text-xs text-slate-500"><a className="text-brand-blue" href="/expense-analysis">1. Add and analyze expenses →</a><a className="text-brand-blue" href="/budget-planning">2. Create your budget →</a><a className="text-brand-blue" href="/reports">3. Generate a report</a></div>
      <details className="profile-settings"><summary>Change financial profile</summary>
      <form className="surface-card flex flex-wrap items-end gap-3" onSubmit={handleProfileSubmit}>
        <label className="min-w-56 flex-1 text-xs font-semibold text-slate-600">
          Profile ID
          <input className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal" value={profileInput} onChange={(event) => setProfileInput(event.target.value)} placeholder="Select a profile with an expense analysis" />
        </label>
        <button className="rounded-md bg-brand-blue px-4 py-2 text-sm font-semibold text-white" type="submit">Load profile</button>
      </form>
      </details>

      {error && (
        <ErrorState
          title={error.code === "persistence_not_configured" ? "Persistence is not configured" : "Budget request failed"}
          message={errorMessage(error)}
          onRetry={() => setRefreshKey((value) => value + 1)}
        />
      )}
      {status && <StatusBadge status={status} label={`Budget ${status}`} />}
      {status === "partial" && <Warning title="Partial budget result" message="The budget agent returned partial output. Review feasibility, assumptions, and trade-offs." />}
      {analysis?.status === "partial" && <Warning title="Expense analysis is partial" message="Your saved transactions were used, but some analysis features or details were unavailable. Review the assumptions below." />}
      {loading && <Loading label="Loading latest analysis and budget" />}
      {!loading && !profileId && <Empty title="Select a profile" description="Choose a profile ID with a saved expense analysis to begin budget planning." />}
      {!loading && profileId && !analysis && !error && (
        <section className="surface-card"><h2 className="font-semibold">First, understand your spending</h2><p className="mt-2 text-sm">First upload your transactions and analyze your spending. We will use those results to create your budget.</p><a className="mt-3 inline-block rounded-md bg-brand-blue px-4 py-2 text-white" href="/expense-analysis">Upload and analyze transactions</a></section>
      )}
      {analysisStale && <Warning title="Your transactions changed" message="Analyze your spending again before creating or revising this budget." />}
      {analysis?.status === "failed" && (
        <ErrorState title="Expense analysis failed" message="A failed upstream analysis cannot be used to create or revise a budget." />
      )}
      {analysis && analysis.status !== "failed" && (
        <>
          <section className="surface-card">
            <div className="card-heading">
              <div>
                <h2>1. Start with your spending</h2>
                <p>These figures come from every saved transaction in the selected profile, including any sample files you imported. They are calculated amounts, not AI estimates.</p>
              </div>
              <StatusBadge status={analysis.status ?? "unknown"} label={`Analysis ${analysis.status ?? "unknown"}`} />
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <div><p className="text-xs font-semibold text-slate-500">Monthly money received</p><p className="mt-1 text-lg font-semibold tabular-nums">{formatMoney(income, currency)}</p></div>
              <div><p className="text-xs font-semibold text-slate-500">Monthly spending</p><p className="mt-1 text-lg font-semibold">{formatMoney(amountOf(summary?.monthly_expenses),currency)}</p></div><div><p className="text-xs font-semibold text-slate-500">Money left over each month</p><p className="mt-1 text-lg font-semibold">{formatMoney(amountOf(summary?.available_surplus),currency)}</p></div>
              <div><p className="text-xs font-semibold text-slate-500">Currency</p><p className="mt-1 text-lg font-semibold">{currency || "Not provided"}</p></div>
            </div>
          </section>

          <p className="text-sm text-slate-600">Reporting period: {summary?.period_start} to {summary?.period_end}. Monthly money received may include refunds or irregular income. <a href="/expense-analysis" className="underline text-brand-blue">Correct income or expenses</a>, then analyze again.</p>
          <form className="surface-card space-y-4" id="budget-preferences" onSubmit={handleCreate}>
            <h2 className="text-base font-semibold text-slate-800">2. Choose your savings goal</h2><p className="text-sm text-slate-600">How much would you like to put aside each month? {budget ? "Leave this blank to keep your previous savings target." : "Leave this blank to try a goal of 20% of money received."} Choose which costs are essential; the remaining categories are flexible.</p>
            <fieldset>
              <legend className="text-xs font-semibold text-slate-600">Savings goal (optional)</legend>
              <div className="mt-2 flex flex-wrap gap-4">
                <label className="flex items-center gap-2 text-sm"><input type="radio" name="goal-mode" value="amount" checked={goalMode === "amount"} onChange={() => setGoalMode("amount")} /> Monthly amount</label>
                <label className="flex items-center gap-2 text-sm"><input type="radio" name="goal-mode" value="rate" checked={goalMode === "rate"} onChange={() => setGoalMode("rate")} /> Rate of income (%)</label>
              </div>
              <input className="mt-3 w-full max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label={goalMode === "amount" ? "Monthly savings goal" : "Savings goal rate"} inputMode="decimal" placeholder={goalMode === "amount" ? "Monthly amount" : "Percent from 0 to 100"} value={goalValue} onChange={(event) => setGoalValue(event.target.value)} />
            </fieldset>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={overrideEssentials} onChange={(event) => setOverrideEssentials(event.target.checked)} />
              Choose which expenses are essential
            </label>
            {overrideEssentials && (
              <fieldset className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <legend className="mb-2 text-xs font-semibold text-slate-600">Select essential categories</legend>
                {availableCategories.map((category) => (
                  <label className="flex items-center gap-2 text-sm capitalize text-slate-700" key={category}>
                    <input type="checkbox" checked={essentialCategories.includes(category)} onChange={() => toggleEssential(category)} />
                    {category.replaceAll("_", " ")}
                  </label>
                ))}
              </fieldset>
            )}
            <button className="rounded-md bg-brand-blue px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60" type="submit" disabled={saving || loading || analysisStale || viewingHistory}>
              {saving ? "Calculating your budget…" : budget ? "Recalculate budget" : "Create my budget"}
            </button>
          </form>

          {budget && (
            <>
              {stale && (
                <Warning title="Budget is stale" message={`This budget uses analysis ${budgetSourceVersion}; the latest analysis is ${analysisVersion}. Revise the budget to use the latest analysis.`} />
              )}
              {viewingHistory && <div className="surface-card flex items-center justify-between"><p className="text-sm">Viewing a saved version. Return to the latest budget before making changes.</p><button className="text-brand-blue underline" type="button" onClick={() => {setBudget(latestBudget); setStatus(latestBudget.status); setGoalValue(String(latestBudget.feasibility?.requested_monthly_savings?.amount ?? ""));}}>Return to latest budget</button></div>}
              <section className="surface-card">
                <div className="card-heading">
                  <div>
                    <h2>3. Your monthly budget</h2>
                    <p>Revision {budget.revision ?? "—"} · Budget ID {budget.budget_id ?? "not provided"}</p>
                  </div>
                  <StatusBadge status={budget.feasibility?.is_feasible ? "success" : "warning"} label={budget.feasibility?.is_feasible ? "Feasible" : "Infeasible"} />
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-3">
                  <div><p className="text-xs font-semibold text-slate-500">Planned monthly savings</p><p className="mt-1 text-lg font-semibold tabular-nums">{formatMoney(budget.planned_monthly_savings?.amount, currency)}</p></div>
                  <div><p className="text-xs font-semibold text-slate-500">Feasibility</p><p className="mt-1 text-lg font-semibold">{budget.feasibility?.is_feasible ? "Feasible" : budget.feasibility ? "Not feasible" : "Not provided"}</p></div>
                  <div><p className="text-xs font-semibold text-slate-500">Shortfall</p><p className="mt-1 text-lg font-semibold tabular-nums">{formatMoney(budget.feasibility?.shortfall?.amount, currency)}</p></div>
                </div>
                {budget.feasibility?.suggestions?.length > 0 && (
                  <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3">
                    <h3 className="font-semibold text-amber-900">Agent suggestions</h3>
                    <ul className="mt-2 list-inside list-disc text-sm text-amber-900">{budget.feasibility.suggestions.map((suggestion, index) => <li key={`${suggestion}-${index}`}>{suggestion}</li>)}</ul>
                  </div>
                )}
              </section>

              <section className="surface-card"><h2 className="font-semibold">What can I do next?</h2><a href="#budget-preferences" className="mt-2 inline-block text-brand-blue underline">Edit my budget or change my savings goal</a><p className="mt-2 text-sm">Unallocated money after category limits and planned savings: {formatMoney(Number(income) - categoryLimits.reduce((sum,item) => sum+Number(item.monthly_limit?.amount || 0),0) - Number(budget.planned_monthly_savings?.amount || 0), currency)}. Savings are a plan, not money already saved.</p></section>
              <section className="grid gap-4 xl:grid-cols-2">
                <ChartCard title="Budget vs actual" description="Compare what you spent with the limits suggested by your budget.">
                  {actualRows.length ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={actualRows} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                        <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="category" tickLine={false} axisLine={false} />
                        <YAxis tickLine={false} axisLine={false} width={72} />
                        <Tooltip formatter={(value) => formatMoney(value, currency)} /><Legend />
                        <Bar dataKey="actual" name="Actual monthly spend" fill="#94a3b8" />
                        <Bar dataKey="limit" name="Monthly limit" fill="#059669" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <Empty title="No category limits returned" />}
                </ChartCard>
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Monthly category limits</h2>
                  <div className="mt-4"><DataTable columns={columns} rows={categoryLimits} getRowKey={(row) => row.category} emptyTitle="No category limits returned" /></div>
                </section>
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Essential allocation</h2>
                  {categoryLimits.filter((item) => item.is_essential).length ? <ul className="mt-3 divide-y divide-slate-100">{categoryLimits.filter((item) => item.is_essential).map((item) => <li className="flex justify-between gap-3 py-2" key={item.category}><span className="capitalize">{item.category.replaceAll("_", " ")}</span><strong>{formatMoney(item.monthly_limit?.amount, currency)}</strong></li>)}</ul> : <Empty title="No essential allocations returned" />}
                </section>
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Discretionary allocation</h2>
                  {categoryLimits.filter((item) => !item.is_essential).length ? <ul className="mt-3 divide-y divide-slate-100">{categoryLimits.filter((item) => !item.is_essential).map((item) => <li className="flex justify-between gap-3 py-2" key={item.category}><span className="capitalize">{item.category.replaceAll("_", " ")}</span><strong>{formatMoney(item.monthly_limit?.amount, currency)}</strong></li>)}</ul> : <Empty title="No discretionary allocations returned" />}
                </section>
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Assumptions</h2>
                  {budget.assumptions?.length ? <ul className="mt-3 list-inside list-disc space-y-2 text-sm text-slate-700">{budget.assumptions.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <Empty title="No assumptions returned" />}
                </section>
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Trade-offs</h2>
                  {budget.trade_offs?.length ? <ul className="mt-3 list-inside list-disc space-y-2 text-sm text-slate-700">{budget.trade_offs.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul> : <Empty title="No trade-offs returned" />}
                </section>
              </section>

              <section className="surface-card flex flex-wrap items-center justify-between gap-3">
                <div><h2 className="text-sm font-semibold text-slate-800">Source analysis version</h2><p className="mt-1 break-all font-mono text-xs text-slate-500">{budgetSourceVersion ?? "Not provided"}</p></div>
                <button className="rounded-md border border-brand-blue px-4 py-2 text-sm font-semibold text-brand-blue disabled:opacity-60" type="button" onClick={handleRevise} disabled={saving || !stale || viewingHistory}>
                  {saving ? "Revising…" : "Revise to latest analysis"}
                </button>
              </section>

              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Revision history</h2>{historyError && <p role="alert" className="mt-2 text-sm text-amber-800">{historyError}</p>}
                {history.length ? (
                  <div className="mt-3 space-y-3">{history.map((record, index) => {
                    const item = unwrapBudget(record);
                    return (
                      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 py-3 last:border-0" key={item?.budget_id ?? item?.id ?? index}>
                        <div><button type="button" className="font-medium text-brand-blue underline" onClick={() => { setBudget(item); setStatus(item.status); setGoalMode("amount"); setGoalValue(String(item.feasibility?.requested_monthly_savings?.amount ?? "")); }}>View revision {item?.revision ?? "—"}</button><p className="mt-1 text-xs text-slate-600">Goal: {formatMoney(item?.feasibility?.requested_monthly_savings?.amount, item.currency || currency)}{record.created_at ? ` · ${new Date(record.created_at).toLocaleString()}` : ""}</p><p className="mt-1 break-all font-mono text-xs text-slate-500">{item?.budget_id ?? item?.id ?? "Budget ID not provided"}</p><p className="mt-1 text-xs text-slate-500">Source: {item?.source_analysis_version ?? "Not provided"}</p></div>
                        <StatusBadge status={item?.status ?? "unknown"} />
                      </div>
                    );
                  })}</div>
                ) : <Empty title="No revision history returned" description="Create a budget to start its history." />}
              </section>
            </>
          )}
        </>
      )}
      {!loading && analysis?.status !== "failed" && analysis && !budget && (
        <section className="surface-card">
          <h2 className="text-base font-semibold text-slate-800">No budget exists yet</h2>
          <p className="mt-2 text-sm text-slate-600">Enter an optional savings goal and create a plan from the current analysis.</p>
        </section>
      )}
    </div>
  );
}
