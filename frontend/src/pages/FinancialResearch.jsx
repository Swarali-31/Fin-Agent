import { useState } from "react";
import { Empty, ErrorState, Loading, Warning } from "../components/StateViews.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import SourceList from "../components/SourceList.jsx";
import { ApiError } from "../services/api.js";
import { runFinancialResearch } from "../services/agents.js";

function researchError(error) {
  if (
    error instanceof ApiError &&
    ["misconfigured", "search_not_configured"].includes(error.code)
  ) {
    return {
      searchNotConfigured: true,
      message: error.message,
    };
  }
  return {
    searchNotConfigured: false,
    message: error instanceof Error ? error.message : "The research request failed.",
  };
}

function resultEnvelope(value) {
  return value?.result ? value : { status: value?.status ?? "unknown", result: value };
}

function findingKind(finding) {
  const value = finding.kind ?? finding.type;
  if (["fact", "estimate", "conclusion"].includes(value)) return value;
  return "cited finding";
}

export default function FinancialResearch() {
  const [question, setQuestion] = useState("");
  const [jurisdiction, setJurisdiction] = useState("IN");
  const [maxSources, setMaxSources] = useState("5");
  const [result, setResult] = useState(null);
  const [taskStatus, setTaskStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function submitQuestion(event) {
    event.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setTaskStatus("running");
    try {
      const response = resultEnvelope(await runFinancialResearch({
        question: question.trim(),
        jurisdiction: jurisdiction.trim() || "IN",
        max_sources: Number(maxSources),
      }));
      setResult(response.result);
      setTaskStatus(response.status ?? response.result?.status ?? "unknown");
    } catch (requestError) {
      setError(researchError(requestError));
      setTaskStatus("failed");
    } finally {
      setLoading(false);
    }
  }

  const sources = result?.sources ?? [];

  return (
    <div className="space-y-6">
      <section>
        <h1 className="page-title">Financial Research</h1>
        <p className="mt-2 text-sm text-slate-600">
          Ask a financial education question and review source-backed findings.
        </p>
      </section>

      <form className="surface-card space-y-4" onSubmit={submitQuestion}>
        <label className="block text-sm font-semibold text-slate-700" htmlFor="research-question">
          Research question
          <textarea
            id="research-question"
            className="mt-2 min-h-28 w-full rounded-md border border-slate-300 px-3 py-3 text-sm font-normal outline-none focus:border-blue-700 focus:ring-2 focus:ring-blue-100"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="For example: How do central banks use policy rates?"
            required
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold text-slate-600">
            Jurisdiction
            <input
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal"
              value={jurisdiction}
              onChange={(event) => setJurisdiction(event.target.value)}
              maxLength={64}
            />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Maximum sources
            <input
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal"
              type="number"
              min="1"
              max="10"
              value={maxSources}
              onChange={(event) => setMaxSources(event.target.value)}
              required
            />
          </label>
        </div>
        <button
          className="rounded-md bg-brand-blue px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
          type="submit"
          disabled={loading || !question.trim()}
        >
          {loading ? "Researching…" : "Run research"}
        </button>
      </form>

      {taskStatus && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-600">Task status</span>
          <StatusBadge status={taskStatus} label={`Research ${taskStatus}`} />
        </div>
      )}
      {loading && <Loading label="Searching sources and preparing findings" />}
      {error?.searchNotConfigured && (
        <section className="surface-card border-amber-300 bg-amber-50" role="alert">
          <h2 className="text-base font-semibold text-amber-900">Search not configured</h2>
          <p className="mt-2 text-sm text-amber-900">{error.message}</p>
          <p className="mt-2 text-sm text-amber-900">
            Configure <code>SEARCH_PROVIDER=tavily</code> and <code>TAVILY_API_KEY</code> in the backend environment, then restart the API. Do not place the key in frontend environment variables.
          </p>
        </section>
      )}
      {error && !error.searchNotConfigured && (
        <ErrorState
          title="Research request failed"
          message={error.message}
          onRetry={() => {
            if (question.trim()) {
              void submitQuestion({ preventDefault() {} });
            }
          }}
        />
      )}

      {result && taskStatus !== "failed" && (
        <div className="space-y-5">
          {result.status === "partial" && (
            <Warning
              title="Partial research result"
              message="The research agent returned partial results. Review the limitations and citations before relying on these findings."
            />
          )}
          {result.status === "failed" && (
            <ErrorState
              title="Research failed"
              message={result.errors?.map((item) => item.message).join(" ") || "The agent reported failed status."}
            />
          )}
          {result.status !== "failed" && (
            <>
              <section className="surface-card">
                <div className="card-heading">
                  <div>
                    <h2>Findings</h2>
                    <p>Statements and citations returned by the research agent.</p>
                  </div>
                  <StatusBadge status={result.status ?? taskStatus} />
                </div>
                {result.findings?.length ? (
                  <ol className="mt-4 space-y-4">
                    {result.findings.map((finding, index) => {
                      const citedSources = sources.filter((source) =>
                        finding.source_ids?.includes(source.source_id),
                      );
                      const kind = findingKind(finding);
                      return (
                        <li className="rounded-md border border-slate-200 p-4" key={`${finding.statement}-${index}`}>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`rounded-full border px-2 py-1 text-xs capitalize ${
                              kind === "fact" ? "border-blue-200 bg-blue-50 text-blue-800" :
                                kind === "estimate" ? "border-amber-200 bg-amber-50 text-amber-800" :
                                  kind === "conclusion" ? "border-emerald-200 bg-emerald-50 text-emerald-800" :
                                    "border-slate-200 bg-slate-50 text-slate-700"
                            }`}>
                              {kind}
                            </span>
                            <span className="text-xs text-slate-500">Confidence: {finding.confidence ?? "not provided"}</span>
                          </div>
                          <p className="mt-3 text-sm leading-6 text-slate-800">{finding.statement}</p>
                          <p className="mt-3 text-xs font-semibold text-slate-600">Cited sources</p>
                          {citedSources.length ? (
                            <SourceList sources={citedSources} sourceIds={finding.source_ids} />
                          ) : (
                            <p className="mt-2 text-sm text-amber-800">
                              No matching source metadata was returned for citation IDs: {finding.source_ids?.join(", ") || "none"}.
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                ) : (
                  <Empty title="No findings returned" description="The agent returned no supported findings." />
                )}
              </section>

              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Retrieved sources</h2>
                <SourceList sources={sources} />
              </section>
            </>
          )}
          {result.limitations?.length > 0 && (
            <Warning
              title="Limitations"
              message={result.limitations.map((item) => item.message ?? item).join(" · ")}
            />
          )}
          {result.disclaimer && (
            <p className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
              {result.disclaimer}
            </p>
          )}
        </div>
      )}
      {!loading && !error && !result && (
        <Empty title="No research run yet" description="Submit a question to see verified findings and retrieved sources." />
      )}
    </div>
  );
}
