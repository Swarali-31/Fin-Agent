import { useCallback, useEffect, useState } from "react";
import { createWorkflow, getWorkflow, getWorkflowTrace } from "../services/workflows.js";
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
    return "The server returned 503 persistence_not_configured. Workflow runs and polling require DATABASE_URL.";
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
  const [task, setTask] = useState("");
  const [contextText, setContextText] = useState("");
  const [runId, setRunId] = useState("");
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
  const contextParseError = contextText.trim()
    ? (() => {
        try {
          const parsed = JSON.parse(contextText);
          return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? null
            : "Context must be a JSON object.";
        } catch {
          return "Context must be valid JSON.";
        }
      })()
    : null;

  const submitTask = useCallback(async (event) => {
    event.preventDefault();
    setSubmitError(null);
    if (!task.trim()) return;
    let context = {};
    if (contextText.trim()) {
      try {
        context = JSON.parse(contextText);
      } catch {
        setSubmitError(new Error("Context must be valid JSON."));
        return;
      }
      if (!context || typeof context !== "object" || Array.isArray(context)) {
        setSubmitError(new Error("Context must be a JSON object."));
        return;
      }
    }
    setSubmitting(true);
    try {
      const response = await createWorkflow({ task: task.trim(), context });
      setRunId(response.run_id);
    } catch (error) {
      setSubmitError(error);
    } finally {
      setSubmitting(false);
    }
  }, [contextText, task]);

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
          Describe a task. The workflow planner selects specialist agents and reports their actual outputs.
        </p>
      </section>

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
        <details>
          <summary className="cursor-pointer text-sm font-semibold text-brand-blue">
            Optional workflow context (JSON)
          </summary>
          <label className="mt-3 block text-sm text-slate-600" htmlFor="workflow-context">
            Financial workflows require <code>context.profile</code> with profile_id, currency, and transactions.
            <textarea
              id="workflow-context"
              className="mt-2 min-h-36 w-full rounded-md border border-slate-300 bg-white px-3 py-3 font-mono text-xs outline-none focus:border-blue-700 focus:ring-2 focus:ring-blue-100"
              value={contextText}
              onChange={(event) => setContextText(event.target.value)}
              placeholder={'{"profile":{"profile_id":"...","currency":"INR","transactions":[...]}}'}
              spellCheck={false}
            />
          </label>
          {contextParseError && <p className="mt-2 text-sm text-red-700">{contextParseError}</p>}
          {storedValue(SAMPLE_PROFILE_STORAGE_KEY) && (
            <p className="mt-2 text-xs text-slate-500">
              A sample profile is selected in this browser, but its transactions cannot be fetched through the current API. Supply a complete <code>context.profile</code> object to run financial tasks.
            </p>
          )}
        </details>
        {submitError && (
          <ErrorState title="Workflow could not be started" message={errorMessage(submitError)} />
        )}
        <button
          className="rounded-md bg-brand-blue px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          type="submit"
          disabled={submitting || !task.trim() || Boolean(contextParseError)}
        >
          {submitting ? "Starting workflow…" : "Run"}
        </button>
      </form>

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

          {fallbackSelected && (
            <Warning title="Deterministic fallback planner" message="The workflow used deterministic_fallback rather than an LLM-generated plan." />
          )}
          {workflow.status === "partial" && (
            <Warning title="Workflow completed partially" message="Some requested agent work did not complete. Review the plan, trace, and errors before relying on the result." />
          )}
          {reachedLimit && (
            <Warning title="Workflow limit reached" message="The workflow stopped at a configured step or replan limit. See the errors below for the exact limit and details." />
          )}
          {workflow.status === "failed" && (
            <ErrorState title="Workflow failed" message={result?.final_answer ?? "No specialist result was produced."} />
          )}

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

          {result?.final_answer && (
            <section className="surface-card">
              <h2 className="text-base font-semibold text-slate-800">Consolidated answer</h2>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{result.final_answer}</p>
            </section>
          )}

          {(claims.length > 0 || sources.length > 0) && (
            <section className="grid gap-4 xl:grid-cols-2">
              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Provenance</h2>
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
              </section>
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
