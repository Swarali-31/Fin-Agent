import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Link } from "react-router-dom";
import ChartCard from "../components/ChartCard.jsx";
import MetricCard from "../components/MetricCard.jsx";
import { Empty, ErrorState, Loading, Warning } from "../components/StateViews.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { listAgents } from "../services/agents.js";
import { listBudgets } from "../services/budgets.js";
import { ApiError } from "../services/api.js";
import {
  createSampleData,
  createProfile,
  listProfiles,
  getProfileSummary,
} from "../services/profiles.js";
import { listWorkflows } from "../services/workflows.js";

const PROFILE_STORAGE_KEY = "finagent.profileId";
const SAMPLE_PROFILE_STORAGE_KEY = "finagent.sampleProfileId";
const CATEGORY_COLORS = ["#072F5F", "#059669", "#b0c68a", "#d2dfb4", "#94a3b8", "#c9aa68"];
const PAGE_LINKS = [
  ["Dashboard", "/dashboard"],
  ["Master Agent", "/master-agent"],
  ["Expense Analysis", "/expense-analysis"],
  ["Budget Planning", "/budget-planning"],
  ["Financial Research", "/financial-research"],
  ["Reports", "/reports"],
];

function readStoredValue(key) {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeStoredValue(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // The current page remains usable without browser storage.
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

function describeApiError(error) {
  if (error instanceof ApiError && error.code === "persistence_not_configured") {
    return "Persistence is not configured on the server. Profile summaries and workflow history are unavailable until DATABASE_URL is set.";
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function workflowTask(workflow) {
  return workflow?.input?.task ?? workflow?.task ?? "Workflow";
}

function workflowRows(data) {
  return Array.isArray(data?.items) ? data.items : [];
}

function agentEntries(registry) {
  if (!registry || typeof registry !== "object" || Array.isArray(registry)) return [];
  return Object.entries(registry);
}

export default function Dashboard() {
  const [profileInput, setProfileInput] = useState(() => readStoredValue(PROFILE_STORAGE_KEY));
  const [profileId, setProfileId] = useState(() => readStoredValue(PROFILE_STORAGE_KEY));
  const [sampleProfileId, setSampleProfileId] = useState(() =>
    readStoredValue(SAMPLE_PROFILE_STORAGE_KEY),
  );
  const [refreshKey, setRefreshKey] = useState(0);
  const [profiles, setProfiles] = useState([]);
  const [newCurrency, setNewCurrency] = useState("INR");
  const [sampleLoading, setSampleLoading] = useState(false);
  const [sampleError, setSampleError] = useState("");
  const [data, setData] = useState({
    agents: null,
    workflows: null,
    summary: null,
    budgets: null,
  });
  const [errors, setErrors] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try { const items = await listProfiles(); if (!cancelled) setProfiles(items ?? []); } catch { /* Existing error panels show persistence failures. */ }
      const [agentsResult, workflowsResult] = await Promise.allSettled([
        listAgents(),
        listWorkflows({ page: 1, page_size: 5 }),
      ]);
      const nextData = {
        agents: agentsResult.status === "fulfilled" ? agentsResult.value : null,
        workflows: workflowsResult.status === "fulfilled" ? workflowsResult.value : null,
        summary: null,
        budgets: null,
      };
      const nextErrors = {};
      if (agentsResult.status === "rejected") nextErrors.agents = agentsResult.reason;
      if (workflowsResult.status === "rejected") nextErrors.workflows = workflowsResult.reason;

      if (profileId) {
        const [summaryResult, budgetsResult] = await Promise.allSettled([
          getProfileSummary(profileId),
          listBudgets({ profile_id: profileId, page: 1, page_size: 1 }),
        ]);
        if (summaryResult.status === "fulfilled") nextData.summary = summaryResult.value;
        else nextErrors.summary = summaryResult.reason;
        if (budgetsResult.status === "fulfilled") nextData.budgets = budgetsResult.value;
        else nextErrors.budgets = budgetsResult.reason;
      }
      if (!cancelled) {
        setData(nextData);
        setErrors(nextErrors);
        setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [profileId, refreshKey]);

  const summary = data.summary;
  const latestBudget = data.budgets?.items?.[0]?.result;
  const currency = summary?.currency ?? latestBudget?.currency ?? "";
  const income = amountOf(summary?.monthly_income);
  const expenses = amountOf(summary?.monthly_expenses);
  const surplus = amountOf(summary?.available_surplus);
  const categories = useMemo(
    () =>
      Object.entries(summary?.category_totals ?? {}).map(([name, value]) => ({
        name: name.replaceAll("_", " "),
        amount: Number(amountOf(value)),
      })),
    [summary],
  );
  const sampleIsActive = Boolean(profiles.find((profile) => profile.profile_id === profileId)?.is_sample ?? (profileId && profileId === sampleProfileId));
  const workflows = workflowRows(data.workflows);
  const agents = agentEntries(data.agents);
  const unavailableAgents = agents.filter(([, agent]) =>
    agent.integration_status?.status &&
    agent.integration_status.status !== "available",
  );

  function handleLoadProfile(event) {
    event.preventDefault();
    const selectedId = profileInput.trim();
    if (!selectedId) return;
    writeStoredValue(PROFILE_STORAGE_KEY, selectedId);
    setProfileId(selectedId);
  }

  async function handleCreateProfile() {
    if (!profileInput.trim()) return;
    setSampleError("");
    try {
      const result = await createProfile(profileInput.trim(), newCurrency);
      writeStoredValue(PROFILE_STORAGE_KEY, result.profile_id);
      setProfileId(result.profile_id);
      setRefreshKey((value) => value + 1);
    } catch (error) { setSampleError(describeApiError(error)); }
  }

  async function handleLoadSample() {
    setSampleLoading(true);
    setSampleError("");
    try {
      const newProfileId = `sample-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
      const result = await createSampleData(newProfileId);
      writeStoredValue(PROFILE_STORAGE_KEY, result.profile_id);
      writeStoredValue(SAMPLE_PROFILE_STORAGE_KEY, result.is_sample ? result.profile_id : "");
      setProfileInput(result.profile_id);
      setProfileId(result.profile_id);
      setSampleProfileId(result.is_sample ? result.profile_id : "");
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setSampleError(describeApiError(error));
    } finally {
      setSampleLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Financial overview</h1>
          <p className="mt-2 text-sm text-slate-600">
            Your spending, plans, and progress — together in one place.
          </p>
        </div>
        {sampleIsActive && <StatusBadge status="info" label="Sample data" />}
      </section>

      <section className="workspace-guide"><h2>Your financial picture starts here.</h2><p>Add your income and expenses first. Then understand your spending, build a budget, and bring it all together in a report. Or ask the Master Agent to connect the steps for you.</p><div className="workspace-steps"><Link to="/expense-analysis"><span>1</span>Add expenses</Link><Link to="/expense-analysis"><span>2</span>Analyze spending</Link><Link to="/budget-planning"><span>3</span>Plan a budget</Link><Link to="/reports"><span>4</span>Create a report</Link></div></section>
      <details className="profile-settings"><summary>Manage financial profiles and currencies</summary>
      <form
        className="surface-card flex flex-wrap items-end gap-3"
        onSubmit={handleLoadProfile}
      >
        <label className="min-w-56 flex-1 text-xs font-semibold text-slate-600">
          Profile ID
          <input
            className="mt-2 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-800 outline-none focus:border-blue-700 focus:ring-2 focus:ring-blue-100"
            value={profileInput}
            onChange={(event) => setProfileInput(event.target.value)}
            placeholder="Enter or create a profile ID"
            list="saved-profiles"
          />
        </label>
        <button className="rounded-md bg-brand-blue px-4 py-2 text-sm font-semibold text-white hover:opacity-90" type="submit">
          Load profile
        </button>
      </form>

      <datalist id="saved-profiles">{profiles.map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{profile.is_sample ? "Sample" : profile.currency}</option>)}</datalist>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">New profile currency <input className="rounded-md border border-slate-300 px-3 py-2 w-24" aria-label="New profile currency" value={newCurrency} onChange={(event) => setNewCurrency(event.target.value.toUpperCase())} maxLength={3} /></label>
        <button className="rounded-md border border-slate-300 px-4 py-2 text-sm" type="button" onClick={handleCreateProfile}>Create profile</button>
      </div>
      </details>
      {sampleError && <ErrorState title="Profile action failed" message={sampleError} />}
      {Object.values(errors).some((error) => error instanceof ApiError && error.code === "persistence_not_configured") && (
        <Warning
          title="Persistence is not configured"
          message="The server returned 503 persistence_not_configured. Configure DATABASE_URL to enable profile summaries, budgets, and workflow history."
        />
      )}
      {unavailableAgents.length > 0 && (
        <Warning
          title="Your agent capabilities"
          message="Expense calculations, budget planning, and reports use your saved data. Live financial research and AI-written interpretation become available when their providers are connected by the workspace owner."
        />
      )}

      {loading ? (
        <Loading label="Loading financial overview" />
      ) : !profileId ? (
        <Empty
          title="No profile selected"
          description="Load an existing profile, or explicitly create a labelled sample profile to see the dashboard."
        />
      ) : errors.summary?.code === "missing_transactions" ? (
        <Empty
          title="No transactions yet"
          description="Add your first income or expense to start building your financial picture."
        />
      ) : errors.summary && !data.summary ? (
        <ErrorState
          title={errors.summary.code === "persistence_not_configured" ? "Profile data unavailable" : "Could not load this profile"}
          message={describeApiError(errors.summary)}
          onRetry={() => setRefreshKey((value) => value + 1)}
        />
      ) : data.summary ? (
        <>
          {summary.status === "partial" && (
            <Warning title="Partial expense analysis" message="Some analysis data may be incomplete." />
          )}
          <section aria-label="Monthly metrics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Monthly income" value={formatMoney(income, currency)} />
            <MetricCard label="Monthly expenses" value={formatMoney(expenses, currency)} />
            <MetricCard label="Available surplus" value={formatMoney(surplus, currency)} tone="positive" />
            <MetricCard
              label="Savings progress"
              value={latestBudget ? formatMoney(amountOf(latestBudget.planned_monthly_savings), currency) : "—"}
              detail={latestBudget ? `Planned target; not realized savings${latestBudget.feasibility?.is_feasible === false ? " · target infeasible" : ""}` : "No budget target available"}
              tone={latestBudget?.feasibility?.is_feasible === false ? "warning" : "positive"}
            />
          </section>

          <section className="grid gap-4 xl:grid-cols-2">
            <ChartCard title="Monthly income vs expenses" description={`Monthly averages from ${summary.months_covered ?? "the latest"} month(s) of analysis.`}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={[
                    { label: "Income", amount: Number(income) },
                    { label: "Expenses", amount: Number(expenses) },
                  ]}
                  margin={{ top: 8, right: 8, left: 8, bottom: 8 }}
                >
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} />
                  <YAxis tickLine={false} axisLine={false} width={72} />
                  <Tooltip formatter={(value) => formatMoney(value, currency)} />
                  <Bar dataKey="amount" fill="#072F5F" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </ChartCard>
            <ChartCard title="Spending by category" description="Monthly category totals from the expense analysis.">
              {categories.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={categories} dataKey="amount" nameKey="name" innerRadius={48} outerRadius={82} paddingAngle={2}>
                      {categories.map((category, index) => (
                        <Cell key={category.name} fill={CATEGORY_COLORS[index % CATEGORY_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value) => formatMoney(value, currency)} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <Empty title="No category spending available" />
              )}
            </ChartCard>
          </section>
          {!latestBudget && errors.budgets && (
            <Warning title="Savings target unavailable" message={describeApiError(errors.budgets)} />
          )}
        </>
      ) : (
        <Empty
          title="No transaction analysis yet"
          description="Add transactions to this profile or explicitly load sample data to create a sample profile."
        />
      )}

      <section className="grid gap-4 xl:grid-cols-2">
        <section className="surface-card">
          <div className="card-heading">
            <div>
              <h2>Recent agent activity</h2>
              <p>Latest workflow runs returned by the API.</p>
            </div>
            <Link className="text-button mt-0" to="/master-agent">Open Master Agent</Link>
          </div>
          <div className="mt-4 space-y-3">
            {errors.workflows ? (
              <ErrorState title="Workflow history unavailable" message={describeApiError(errors.workflows)} onRetry={() => setRefreshKey((value) => value + 1)} />
            ) : loading ? (
              <Loading label="Loading workflow history" />
            ) : workflows.length ? (
              workflows.map((workflow) => (
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 py-3 last:border-0" key={workflow.run_id}>
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-800">{workflowTask(workflow)}</p>
                    <p className="mt-1 text-xs text-slate-500">{workflow.started_at ? new Date(workflow.started_at).toLocaleString() : workflow.run_id}</p>
                  </div>
                  <StatusBadge status={workflow.status ?? "pending"} />
                </div>
              ))
            ) : (
              <Empty title="No agent activity yet" description="Start a workflow in Master Agent to see activity here." />
            )}
          </div>
        </section>

        <section className="surface-card">
          <div className="card-heading">
            <div>
              <h2>Agent registry</h2>
              <p>Capabilities and integration status from the API.</p>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {errors.agents ? (
              <ErrorState title="Agent registry unavailable" message={describeApiError(errors.agents)} onRetry={() => setRefreshKey((value) => value + 1)} />
            ) : loading ? (
              <Loading label="Loading agent registry" />
            ) : agents.length ? (
              agents.map(([name, agent]) => (
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 py-3 last:border-0" key={name}>
                  <div>
                    <p className="font-medium text-slate-800">{name.replaceAll("_", " ")}</p>
                    <p className="mt-1 text-xs text-slate-500">{(agent.capabilities ?? []).join(" · ") || "No capabilities listed"}</p>
                  </div>
                  <StatusBadge status={agent.integration_status?.status ?? "neutral"} />
                </div>
              ))
            ) : (
              <Empty title="No agents are registered" />
            )}
          </div>
        </section>
      </section>

      <section className="surface-card">
        <div className="card-heading">
          <div>
            <h2>Explore FinAgent</h2>
            <p>Navigate to an agent workspace.</p>
          </div>
        </div>
        <nav aria-label="Dashboard page links" className="mt-4 flex flex-wrap gap-2">
          {PAGE_LINKS.map(([label, to]) => (
            <Link className="rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-brand-blue hover:bg-slate-50" key={to} to={to}>
              {label}
            </Link>
          ))}
        </nav>
        <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4">
          <Link className="text-button mt-0" to="/expense-analysis">Add transactions</Link>
          <button
            className="rounded-md border border-brand-blue px-3 py-2 text-sm font-semibold text-brand-blue disabled:opacity-60"
            type="button"
            onClick={handleLoadSample}
            disabled={sampleLoading}
          >
            {sampleLoading ? "Loading sample data…" : "Load sample data"}
          </button>
        </div>
      </section>
    </div>
  );
}
