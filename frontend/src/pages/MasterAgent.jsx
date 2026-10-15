import { useCallback, useEffect, useState } from "react";
import { createWorkflow, getWorkflow, getWorkflowTrace, listWorkflows } from "../services/workflows.js";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../services/api.js";
import { Empty, ErrorState, Loading, Warning } from "../components/StateViews.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

const TERMINAL_STATUSES = new Set(["success", "partial", "failed"]);
const SAMPLE_PROFILE_STORAGE_KEY = "finagent.sampleProfileId";

function storedValue(key) {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function isTerminal(workflow) {
  return TERMINAL_STATUSES.has(workflow?.status) ||
    TERMINAL_STATUSES.has(workflow?.result?.status);
}

function errorMessage(error) {
  if (error instanceof ApiError && error.code === "persistence_not_configured") {
    return "Your saved workspace is unavailable. Ask the workspace owner to check the database connection.";
  }
  return error instanceof Error ? error.message : "The workflow request failed.";
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function usePolling(runId, intervalMs = 1500) {
  const [state, setState] = useState({
    workflow: null,
    trace: [],
    loading: Boolean(runId),
    error: null,
  });

  useEffect(() => {
    if (!runId) {
      setState({ workflow: null, trace: [], loading: false, error: null });
      return undefined;
    }
    let stopped = false;
    let timer;
    setState({ workflow: null, trace: [], loading: true, error: null });

    const poll = async () => {
      const [workflowResult, traceResult] = await Promise.allSettled([
        getWorkflow(runId),
        getWorkflowTrace(runId),
      ]);
      if (stopped) return;
      if (workflowResult.status === "rejected") {
        setState((previous) => ({
          ...previous,
          loading: false,
          error: workflowResult.reason,
        }));
        return;
      }
      const workflow = workflowResult.value;
      const trace = traceResult.status === "fulfilled" && Array.isArray(traceResult.value)
        ? traceResult.value.map((event) => event.payload ?? event)
        : [];
      setState({
        workflow,
        trace,
        loading: !isTerminal(workflow),
        error: traceResult.status === "rejected" ? traceResult.reason : null,
      });
      if (!isTerminal(workflow)) timer = window.setTimeout(poll, intervalMs);
    };

    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [runId, intervalMs]);

  return state;
}

function workflowResult(workflow) {
  return workflow?.result ?? null;
}

function sourceList(result) {
  if (Array.isArray(result?.sources)) return result.sources;
  return Object.values(result?.results ?? {}).flatMap((envelope) =>
    Array.isArray(envelope?.result?.sources) ? envelope.result.sources : [],
  );
}

function timelineLabel(event) {
  const labels = {
    plan: "Plan",
    route: "Routing",
    agent_call: "Agent call",
    agent_result: "Agent result",
    validation: "Validation",
    retry: "Retry",
    replan: "Replan",
    skip: "Skipped step",
    error: "Error",
    final: "Final",
  };
  return labels[event.type] ?? event.type;
}

export default function MasterAgent() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [recentRuns, setRecentRuns] = useState([]);
  const [task, setTask] = useState("");
  const [profileId, setProfileId] = useState(() => storedValue("finagent.profileId"));
  const [savingsTarget, setSavingsTarget] = useState("");
  const [runId, setRunId] = useState(() => searchParams.get("run") || "");
  useEffect(() => {
    let active = true;
    listWorkflows({page:1,page_size:10}).then((data) => { if (active) setRecentRuns(data?.items || []); }).catch(() => {});
    return () => { active = false; };
  }, []);
  function viewRun(id) { setRunId(id); setSearchParams(id ? {run:id} : {}, {replace:true}); }

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const polling = usePolling(runId);
  const workflow = polling.workflow;
  const result = workflowResult(workflow);
  const plan = result?.plan;
  const steps = plan?.steps ?? [];
  const intermediateResults = result?.results ?? {};
  const errors = result?.errors ?? [];
  const sources = sourceList(result);
  const submitTask = useCallback(async (event) => {
    event.preventDefault();
    setSubmitError(null);
    if (!task.trim()) return;
    const context = profileId.trim() ? { profile_id: profileId.trim() } : {};
    if (savingsTarget.trim()) context.savings_goal = { monthly_target: { amount: savingsTarget } };
    setSubmitting(true);
    try {
      const response = await createWorkflow({ task: task.trim(), context });
      viewRun(response.run_id);
    } catch (error) {
      setSubmitError(error);
    } finally {
      setSubmitting(false);
    }
  }, [profileId, task, savingsTarget]);

  const claims = result?.claims ?? [];
  const fallbackSelected = plan?.source === "deterministic_fallback" ||
    polling.trace.some((event) => event.details?.planner === "deterministic_fallback");
  const reachedLimit = errors.some((error) =>
    String(error.code ?? "").includes("limit") ||
    String(error.code ?? "").includes("max_steps") ||
    String(error.code ?? "").includes("max_replans"),
  );

  return (
    <div className="space-y-6">
      <section>
        <h1 className="page-title">Master Agent</h1>
        <p className="mt-2 text-sm text-slate-600">
          Tell FinAgent what you need. It reads your selected profile, chooses the required agents, and shows their results.
        </p>
      </section>

      <section className="surface-card space-y-2"><h2 className="font-semibold">How it works</h2><ol className="list-decimal list-inside text-sm space-y-2"><li>Expense Analysis reads your saved transactions and adds up income and spending.</li><li>Budget Planning uses that analysis and your savings target to suggest spending limits.</li><li>Financial Research searches the web and includes links to its sources. It can run without a profile.</li><li>Financial Report checks the available results and combines them into a downloadable report.</li></ol><p className="text-sm">Only the agents needed for your request run. The execution trace shows what completed, what failed, and why. Changed transactions require a fresh analysis and budget.</p></section>
      {recentRuns.length > 0 && <label className="block text-sm">Previous requests<select aria-label="Previous requests" value={runId} onChange={(event) => viewRun(event.target.value)} className="mt-2 block w-full rounded-md border border-slate-300 p-3"><option value="">Choose a previous request</option>{recentRuns.map((run) => <option value={run.run_id} key={run.run_id}>{run.input?.task || "Saved request"} · {new Date(run.started_at).toLocaleString()}</option>)}</select></label>}
      <form className="surface-card space-y-4" onSubmit={submitTask}>
        <label className="block text-sm font-semibold text-slate-700" htmlFor="workflow-task">
          What would you like FinAgent to do?
          <textarea
            id="workflow-task"
            className="mt-2 min-h-28 w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-3 text-sm font-normal outline-none focus:border-blue-700 focus:ring-2 focus:ring-blue-100"
            value={task}
            onChange={(event) => setTask(event.target.value)}
            placeholder="For example: Research how emergency funds work."
            required
          />
        </label>
        <p className="text-sm text-slate-500">Your saved income and expenses are included automatically. Research questions can run independently.</p>
        <label className="block text-sm font-semibold">Monthly savings target (optional)<input type="number" min="0.01" step="0.01" value={savingsTarget} onChange={(event) => setSavingsTarget(event.target.value)} className="mt-2 block rounded-md border border-slate-300 px-3 py-2" /></label>
        <p className="text-sm text-slate-500">Enter a target here when asking for a budget. If blank, the budget agent uses its default target and shows its assumptions.</p>
        <div className="flex flex-wrap gap-2">{["Analyze my spending and create a budget", "Generate a financial report", "Research how emergency funds work"].map((goal) => <button type="button" key={goal} className="rounded-full border border-slate-200 px-3 py-2 text-xs text-slate-600" onClick={() => setTask(goal)}>{goal}</button>)}</div>
        <details className="profile-settings"><summary>Change financial profile</summary><input aria-label="Financial profile" value={profileId} onChange={(event) => setProfileId(event.target.value)} className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" /></details>
        {profileId && storedValue(SAMPLE_PROFILE_STORAGE_KEY) === profileId && <StatusBadge status="info" label="Sample data" />}
        {submitError && (
          <ErrorState title="Workflow could not be started" message={errorMessage(submitError)} />
        )}
        <button
          className="rounded-md bg-brand-blue px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          type="submit"
          disabled={submitting || !task.trim()}
        >
          {submitting ? "Starting workflow…" : "Run"}
        </button>
      </form>

      {runId && <section className="surface-card"><h2 className="font-semibold">Your request, step by step</h2><ol className="mt-3 space-y-2 text-sm"><li>1. Understanding your request {workflow ? "✓" : "…"}</li><li>2. Preparing your financial data {profileId ? (polling.trace.some((event) => event.type === "agent_call" || event.type === "validation") ? "✓" : "…") : "— research does not need a financial profile"}</li><li>3. Running the required agents {polling.loading ? "…" : workflow?.status === "failed" ? "— needs attention" : result ? "✓" : "…"}</li><li>4. Preparing your results {result?.final_answer ? "✓" : "…"}</li><li>5. {workflow?.status === "success" ? "Completed" : workflow?.status === "partial" || workflow?.status === "failed" ? "Needs attention — read the notes below" : "Working on it"}</li></ol></section>}

      {polling.error && (
        <ErrorState title="Workflow status unavailable" message={errorMessage(polling.error)} />
      )}
      {runId && polling.loading && <Loading label="Workflow is running; refreshing status and trace…" />}
      {runId && !workflow && !polling.loading && !polling.error && (
        <Loading label="Loading workflow result" />
      )}

      {workflow && (
        <div className="space-y-5">
          <section className="surface-card flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-slate-800">Workflow run</h2>
              <p className="mt-1 break-all text-xs text-slate-500">{runId}</p>
            </div>
            <StatusBadge status={workflow.status ?? "running"} />
          </section>

          {result?.final_answer && (
            <section className="surface-card">
              <h2 className="text-base font-semibold text-slate-800">Your results</h2>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{result.final_answer}</p>
            </section>
          )}

          {fallbackSelected && (
            <Warning title="Standard workflow" message="FinAgent used its standard workflow rules for this request. The selected agents still processed your actual data." />
          )}
          {workflow.status === "partial" && (
            <Warning title="Workflow completed partially" message="Some requested agent work did not complete. Review the plan, trace, and errors before relying on the result." />
          )}
          {reachedLimit && (
            <Warning title="Workflow limit reached" message="The workflow stopped at a configured step or replan limit. See the errors below for the exact limit and details." />
          )}
          {workflow.status === "failed" && (
            <ErrorState title="Workflow failed" message={result?.final_answer ?? "No result could be completed. Check the note below and try again."} />
          )}

          <details className="surface-card"><summary className="cursor-pointer font-semibold">Detailed workflow and execution trace</summary><div className="mt-4 space-y-4">
          <section className="surface-card">
            <div className="card-heading">
              <div>
                <h2>Selected agents and plan</h2>
                <p>{plan ? `Planner: ${plan.source}` : "The plan is not available yet."}</p>
              </div>
            </div>
            {steps.length ? (
              <div className="mt-4 space-y-3">
                {steps.map((step) => (
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 py-3 last:border-0" key={step.id}>
                    <div>
                      <p className="font-medium text-slate-800">{step.agent.replaceAll("_", " ")}</p>
                      <p className="mt-1 text-xs text-slate-500">
                        Step {step.id}{step.depends_on?.length ? ` · depends on ${step.depends_on.join(", ")}` : ""}
                        {Number.isInteger(step.attempts) ? ` · attempts ${step.attempts}` : ""}
                      </p>
                    </div>
                    <StatusBadge status={step.status ?? "pending"} />
                  </div>
                ))}
              </div>
            ) : <Empty title="No plan available" />}
          </section>

          <section className="surface-card">
            <div className="card-heading">
              <div>
                <h2>Execution trace</h2>
                <p>Append-only routing and execution events.</p>
              </div>
            </div>
            {polling.trace.length ? (
              <ol className="mt-4 space-y-0">
                {polling.trace.map((event) => (
                  <li className="relative border-l border-slate-200 pb-5 pl-5 last:border-l-transparent last:pb-0" key={`${event.seq}-${event.type}`}>
                    <span className={`absolute -left-1 top-1 h-2 w-2 rounded-full ${event.type === "error" ? "bg-red-600" : event.type === "retry" || event.type === "replan" || event.type === "skip" ? "bg-amber-500" : "bg-brand-green"}`} />
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-800">{timelineLabel(event)}</span>
                      {event.details?.planner === "deterministic_fallback" && (
                        <StatusBadge status="warning" label="deterministic_fallback" />
                      )}
                      {event.agent && <span className="text-xs text-slate-500">{event.agent}</span>}
                    </div>
                    <p className="mt-1 text-sm text-slate-600">{event.summary}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      {event.timestamp ? new Date(event.timestamp).toLocaleString() : `Event ${event.seq}`}
                      {event.duration_ms != null ? ` · ${event.duration_ms} ms` : ""}
                      {event.step_id ? ` · ${event.step_id}` : ""}
                    </p>
                    {event.details && Object.keys(event.details).length > 0 && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-xs text-brand-blue">Event details</summary>
                        <pre className="mt-2 overflow-auto rounded bg-slate-50 p-3 text-xs">{pretty(event.details)}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <Empty title="No trace events yet" description="Trace events will appear as the workflow progresses." />
            )}
          </section>

          {errors.length > 0 && (
            <section className="surface-card" aria-labelledby="workflow-errors-heading">
              <h2 id="workflow-errors-heading" className="text-base font-semibold text-red-800">Workflow errors and limits</h2>
              <div className="mt-3 space-y-3">
                {errors.map((error, index) => (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3" key={`${error.code ?? "error"}-${index}`}>
                    <p className="font-semibold text-red-800">{error.code ?? "Workflow error"}</p>
                    <p className="mt-1 text-sm text-red-700">{error.message}</p>
                    {error.details && <pre className="mt-2 overflow-auto text-xs text-red-700">{pretty(error.details)}</pre>}
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="surface-card">
            <div className="card-heading">
              <div>
                <h2>Intermediate results</h2>
                <p>Specialist envelopes are displayed without altering their payloads.</p>
              </div>
            </div>
            {Object.keys(intermediateResults).length ? (
              <div className="mt-4 space-y-3">
                {Object.entries(intermediateResults).map(([stepId, envelope]) => (
                  <details className="rounded-md border border-slate-200 p-3" key={stepId}>
                    <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3">
                      <span className="font-medium text-slate-800">{stepId.replaceAll("_", " ")}</span>
                      <StatusBadge status={envelope.status ?? "neutral"} />
                    </summary>
                    <pre className="mt-3 max-h-96 overflow-auto rounded bg-slate-50 p-3 text-xs">{pretty(envelope.result ?? envelope)}</pre>
                  </details>
                ))}
              </div>
            ) : (
              <Empty title="No intermediate results yet" />
            )}
          </section>



          </div></details>

          {(claims.length > 0 || sources.length > 0) && (
            <section className="grid gap-4 xl:grid-cols-2">
              <details className="surface-card">
                <summary className="cursor-pointer text-base font-semibold text-slate-800">How these results were checked</summary>
                {claims.length ? (
                  <div className="mt-3 space-y-3">
                    {claims.map((claim, index) => (
                      <div className="border-b border-slate-100 pb-3 last:border-0" key={`${claim.step_id}-${claim.field_path}-${index}`}>
                        <p className="text-sm text-slate-800">{claim.field_path}</p>
                        <p className="mt-1 break-words text-xs text-slate-500">
                          {claim.agent} · {claim.step_id}{claim.version ? ` · ${claim.version}` : ""}
                        </p>
                        {claim.value !== undefined && <pre className="mt-2 overflow-auto text-xs text-slate-600">{pretty(claim.value)}</pre>}
                      </div>
                    ))}
                  </div>
                ) : <Empty title="No provenance claims available" />}
              </details>
              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Sources</h2>
                {sources.length ? (
                  <ul className="mt-3 space-y-3">
                    {sources.map((source, index) => (
                      <li className="border-b border-slate-100 pb-3 last:border-0" key={source.source_id ?? source.url ?? index}>
                        <p className="text-sm font-medium text-slate-800">{source.title ?? source.source_id ?? "Source"}</p>
                        {source.url && (
                          <a className="mt-1 block break-all text-xs text-blue-700 underline" href={source.url} target="_blank" rel="noreferrer">
                            {source.url}
                          </a>
                        )}
                        {source.source_id && <p className="mt-1 text-xs text-slate-500">Source ID: {source.source_id}</p>}
                      </li>
                    ))}
                  </ul>
                ) : <Empty title="No source references available" />}
              </section>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
