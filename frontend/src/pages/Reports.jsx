import { useCallback, useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Empty, ErrorState, Loading, Warning } from "../components/StateViews.jsx";
import SourceList from "../components/SourceList.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { ApiError } from "../services/api.js";
import { runFinancialReport } from "../services/agents.js";
import { getLatestExpenseAnalysis } from "../services/profiles.js";
import { listBudgets } from "../services/budgets.js";
import { listResearch } from "../services/research.js";
import { downloadReport, listReports } from "../services/reports.js";

const PROFILE_KEY = "finagent.profileId";
const REPORT_FORMATS = ["pdf", "json", "markdown"];

function storedProfile() {
  try {
    return window.localStorage.getItem(PROFILE_KEY) ?? "";
  } catch {
    return "";
  }
}

function unwrapAnalysis(record) {
  if (!record?.result) return record;
  return {
    ...record.result,
    analysis_version: record.analysis_version ?? record.result.analysis_version,
    status: record.status ?? record.result.status,
  };
}

function unwrapResult(value) {
  if (value?.result) return value.result;
  return value;
}

function unwrapEnvelope(value) {
  return value?.result ? value : { status: value?.status ?? "unknown", result: value };
}

function errorText(error) {
  if (error instanceof ApiError && error.code === "persistence_not_configured") {
    return "The server returned 503 persistence_not_configured. Report history and downloads require DATABASE_URL.";
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function reportRecordValue(record) {
  return record?.result ?? record;
}

function downloadFile(data, format) {
  if (format === "pdf") {
    const url = URL.createObjectURL(data);
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = "FinAgent-Report.pdf"; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); return;
  }
  const content = format === "json" ? JSON.stringify(data.content, null, 2) : data.content;
  const mimeType = format === "json" ? "application/json" : "text/markdown";
  const url = URL.createObjectURL(new Blob([content], { type: `${mimeType};charset=utf-8` }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = data.filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function TextList({ title, items }) {
  return (
    <section className="surface-card">
      <h2 className="text-base font-semibold text-slate-800">{title}</h2>
      {items?.length ? (
        <ul className="mt-3 list-inside list-disc space-y-2 text-sm text-slate-700">
          {items.map((item, index) => (
            <li key={`${typeof item === "string" ? item : JSON.stringify(item)}-${index}`}>
              {typeof item === "string" ? item : item.statement ?? JSON.stringify(item)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-slate-500">No items returned.</p>
      )}
    </section>
  );
}

export default function Reports() {
  const [profileId, setProfileId] = useState(storedProfile);
  const [profileInput, setProfileInput] = useState(storedProfile);
  const [analysis, setAnalysis] = useState(null);
  const [budget, setBudget] = useState(null);
  const [research, setResearch] = useState(null);
  const [reports, setReports] = useState([]);
  const [report, setReport] = useState(null);
  const [reportId, setReportId] = useState(null);
  const [reportStatus, setReportStatus] = useState(null);
  const [loadingInputs, setLoadingInputs] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [format, setFormat] = useState("pdf");
  const [error, setError] = useState(null);
  const [historyError, setHistoryError] = useState(null);
  const [inputNotice, setInputNotice] = useState("");

  const loadProfileData = useCallback(async (selectedProfileId) => {
    if (!selectedProfileId) {
      setAnalysis(null);
      setBudget(null);
      setResearch(null);
      setReports([]);
      return;
    }
    setLoadingInputs(true);
    setError(null);
    setInputNotice("");
    let notice = "";
    const [analysisResult, budgetResult, researchResult, reportResult] = await Promise.allSettled([
      getLatestExpenseAnalysis(selectedProfileId),
      listBudgets({ profile_id: selectedProfileId, page: 1, page_size: 1 }),
      listResearch({ profile_id: selectedProfileId, page: 1, page_size: 1 }),
      listReports({ profile_id: selectedProfileId, page: 1, page_size: 20 }),
    ]);
    if (analysisResult.status === "fulfilled") {
      setAnalysis(unwrapAnalysis(analysisResult.value));
    } else {
      setAnalysis(null);
      if (analysisResult.reason?.status !== 404 && analysisResult.reason?.code !== "analysis_not_found") {
        setError(analysisResult.reason);
      }
    }
    const budgetItems = budgetResult.status === "fulfilled" ? budgetResult.value?.items ?? [] : [];
    setBudget(budgetItems[0] ? unwrapResult(budgetItems[0]) : null);
    if (researchResult.status === "fulfilled") {
      const researchItems = researchResult.value?.items ?? [];
      setResearch(researchItems[0] ? unwrapResult(researchItems[0]) : null);
    } else {
      setResearch(null);
    }
    if (reportResult.status === "fulfilled") {
      setReports(reportResult.value?.items ?? []);
      setHistoryError(null);
    } else {
      setReports([]);
      setHistoryError(reportResult.reason);
    }
    if (budgetResult.status === "rejected" && budgetResult.reason?.status !== 404) {
      notice = `Could not load a budget: ${errorText(budgetResult.reason)}`;
    }
    if (analysisResult.status === "fulfilled" && budgetItems.length === 0 && !notice) {
      notice = "No budget was found for this profile. Create one in Budget Planning before generating a report.";
    }
    setInputNotice(notice);
    setLoadingInputs(false);
  }, []);

  useEffect(() => {
    void loadProfileData(profileId);
  }, [profileId, loadProfileData]);

  function selectProfile(event) {
    event.preventDefault();
    const selected = profileInput.trim();
    if (!selected) return;
    try {
      window.localStorage.setItem(PROFILE_KEY, selected);
    } catch {
      // The selected profile remains available for the current page session.
    }
    setReport(null);
    setReportId(null);
    setProfileId(selected);
  }

  async function generateReport(event) {
    event.preventDefault();
    setError(null);
    if (!analysis || !budget) return;
    setGenerating(true);
    setReport(null);
    setReportId(null);
    try {
      const response = unwrapEnvelope(await runFinancialReport({
        expense_analysis: analysis,
        budget,
        research,
        expected_analysis_version: analysis.analysis_version,
      }, profileId));
      setReport(response.result);
      setReportStatus(response.status ?? response.result?.status ?? "unknown");
      const refreshed = await listReports({ profile_id: profileId, page: 1, page_size: 20 });
      const records = refreshed.items ?? [];
      setReports(records);
      const match = records.find((item) =>
        reportRecordValue(item)?.report_version === response.result?.report_version,
      );
      if (match) setReportId(match.id);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.code === "report_inputs_rejected") {
        setReport({
          validation_status: "rejected",
          validation_summary: requestError.message,
          validation_issues: requestError.details?.validation_issues ?? [],
          sections: null,
          source_versions: null,
        });
        setReportStatus("failed");
      } else {
        setError(requestError);
      }
    } finally {
      setGenerating(false);
    }
  }

  async function handleDownload(id) {
    if (!id) return;
    setDownloading(true);
    setError(null);
    try {
      const data = await downloadReport(id, format);
      downloadFile(data, format);
    } catch (downloadError) {
      setError(downloadError);
    } finally {
      setDownloading(false);
    }
  }

  function showHistoryReport(record) {
    setReport(reportRecordValue(record));
    setReportId(record.id ?? null);
    setReportStatus(record.status ?? reportRecordValue(record)?.status ?? "unknown");
    setError(null);
  }

  const validationStatus = report?.validation_status;
  const sections = report?.sections;
  const sourceVersions = report?.source_versions;

  return (
    <div className="space-y-6">
      <section>
        <h1 className="page-title">Reports</h1>
        <p className="mt-2 text-sm text-slate-600">
          Bring your spending analysis and budget together in a report. Your saved results are checked before the report is generated.
        </p>
      </section>

      <div className="flex flex-wrap gap-4 text-xs text-slate-500"><a className="text-brand-blue" href="/expense-analysis">1. Add and analyze expenses →</a><a className="text-brand-blue" href="/budget-planning">2. Create your budget →</a><a className="text-brand-blue" href="/reports">3. Generate a report</a></div>
      <details className="profile-settings"><summary>Change financial profile</summary>
      <form className="surface-card flex flex-wrap items-end gap-3" onSubmit={selectProfile}>
        <label className="min-w-56 flex-1 text-xs font-semibold text-slate-600">
          Profile ID
          <input
            className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal"
            value={profileInput}
            onChange={(event) => setProfileInput(event.target.value)}
            placeholder="Select a profile with analysis and budget"
          />
        </label>
        <button className="rounded-md bg-brand-blue px-4 py-2 text-sm font-semibold text-white" type="submit">
          Load profile
        </button>
      </form>
      </details>

      {loadingInputs && <Loading label="Loading latest analysis, budget, and report history" />}
      {error && <ErrorState title="Report request failed" message={errorText(error)} />}
      {historyError && (
        <Warning title="Report history unavailable" message={errorText(historyError)} />
      )}
      {inputNotice && <Warning title="Report inputs" message={inputNotice} />}
      {!profileId && (
        <Empty title="Select a profile" description="A report requires a profile with a latest expense analysis and budget." />
      )}

      {profileId && !loadingInputs && (
        <section className="surface-card">
          <h2 className="text-base font-semibold text-slate-800">Report inputs</h2>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold text-slate-500">Latest analysis</dt>
              <dd className="mt-1 text-sm text-slate-800">
                {analysis?.analysis_version ?? (error ? "Unavailable" : "Not found")}
                {analysis?.status && <span className="ml-2"><StatusBadge status={analysis.status} /></span>}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold text-slate-500">Latest budget</dt>
              <dd className="mt-1 text-sm text-slate-800">
                {budget?.budget_id ?? (budget ? "Available" : "Not found")}
                {budget?.revision && <span> · Revision {budget.revision}</span>}
              </dd>
            </div>
          </dl>
          <button
            className="mt-4 rounded-md bg-brand-blue px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            type="button"
            onClick={generateReport}
            disabled={generating || loadingInputs || !analysis || !budget || analysis.status === "failed" || budget.status === "failed"}
          >
            {generating ? "Generating report…" : "Generate report"}
          </button>
        </section>
      )}

      {generating && <Loading label="Validating inputs and generating report" />}
      {report && (
        <div className="space-y-5">
          {validationStatus && (
            <section className={`surface-card ${
              validationStatus === "rejected" ? "border-red-300 bg-red-50" :
                validationStatus === "flagged" ? "border-amber-300 bg-amber-50" :
                  "border-emerald-200"
            }`}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-base font-semibold text-slate-800">Input validation</h2>
                <StatusBadge
                  status={validationStatus === "valid" ? "success" : validationStatus === "flagged" ? "warning" : "failed"}
                  label={validationStatus}
                />
              </div>
              {report.validation_summary && (
                <p className="mt-3 text-sm text-slate-700">{validationStatus === "valid" ? "Inputs checked." : validationStatus === "rejected" ? report.validation_summary : `${report.validation_issues?.length || 0} items need review.`}</p>
              )}
              {report.validation_issues?.length ? (
                <details className="mt-3"><summary className="cursor-pointer text-sm">Review issues ({report.validation_issues.length})</summary><ul className="mt-3 space-y-2">
                  {report.validation_issues.map((issue, index) => (
                    <li className="rounded border border-current/10 p-3 text-sm" key={`${issue.code}-${index}`}>
                      <div className="flex flex-wrap gap-2">
                        <strong>{issue.code}</strong>
                        {issue.severity && <StatusBadge status={issue.severity === "error" ? "failed" : issue.severity === "warning" ? "warning" : "neutral"} label={issue.severity} />}
                      </div>
                      <p className="mt-1">{issue.message}</p>
                    </li>
                  ))}
                </ul></details>
              ) : validationStatus !== "valid" ? (
                <p className="mt-3 text-sm text-slate-600">No issue details were included in the response.</p>
              ) : null}
            </section>
          )}
          {reportStatus === "partial" && (
            <Warning title="Partial report" message="The report agent returned partial status. Some content may be incomplete." />
          )}
          {validationStatus === "rejected" ? (
            <ErrorState
              title="Report rejected"
              message={report.validation_summary || "The inputs were inconsistent. No report sections are available."}
            />
          ) : sections ? (
            <>
              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Summary</h2>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{sections.summary?.length > 360 ? `${sections.summary.slice(0,360)}…` : sections.summary}</p>

              </section>
<details className="space-y-5"><summary className="surface-card cursor-pointer font-semibold">View full report</summary>{sections.summary?.length > 360 && <section className="surface-card"><h2 className="font-semibold">Full summary</h2><p className="mt-3 whitespace-pre-wrap text-sm leading-6">{sections.summary}</p></section>}
              <TextList title="Spending insights" items={sections.spending_insights} />
              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Budget overview</h2>
                {sections.budget_overview?.length ? (
                  <div className="mt-3 overflow-x-auto">
                    <table className="data-table">
                      <thead><tr><th>Category</th><th>Monthly limit</th><th>Current spend</th><th>Type</th><th>Rationale</th></tr></thead>
                      <tbody>
                        {sections.budget_overview.map((item, index) => (
                          <tr key={`${item.category}-${index}`}>
                            <td className="capitalize">{item.category?.replaceAll("_", " ")}</td>
                            <td className="tabular-nums">{item.monthly_limit?.amount ?? "—"}</td>
                            <td className="tabular-nums">{item.current_monthly_spend?.amount ?? "—"}</td>
                            <td>{item.is_essential ? "Essential" : "Discretionary"}</td>
                            <td>{item.rationale}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="mt-3 text-sm text-slate-500">No budget overview returned.</p>}
              </section>
              <TextList title="Savings opportunities" items={sections.savings_opportunities} />
              <section className="surface-card">
                <h2 className="text-base font-semibold text-slate-800">Research findings</h2>
                {sections.research_findings?.length ? (
                  <ol className="mt-3 space-y-4">
                    {sections.research_findings.map((finding, index) => (
                      <li className="border-b border-slate-100 pb-4 last:border-0" key={`${finding.statement}-${index}`}>
                        <p className="text-sm text-slate-800">{finding.statement}</p>
                        <p className="mt-1 text-xs text-slate-500">Confidence: {finding.confidence ?? "not provided"}</p>
                        <SourceList sources={sections.sources ?? []} sourceIds={finding.source_ids} />
                      </li>
                    ))}
                  </ol>
                ) : <p className="mt-3 text-sm text-slate-500">No research findings were included.</p>}
                <h3 className="mt-5 text-sm font-semibold text-slate-700">Sources</h3>
                <SourceList sources={sections.sources ?? []} />
              </section>
              <TextList title="Assumptions" items={sections.assumptions} />
              <TextList title="Risk considerations" items={sections.risk_considerations} />
              {sourceVersions && (
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Source versions</h2>
                  <dl className="mt-3 grid gap-3 sm:grid-cols-3">
                    <div><dt className="text-xs font-semibold text-slate-500">Analysis version</dt><dd className="mt-1 break-all font-mono text-xs">{sourceVersions.analysis_version}</dd></div>
                    <div><dt className="text-xs font-semibold text-slate-500">Budget ID</dt><dd className="mt-1 break-all font-mono text-xs">{sourceVersions.budget_id}</dd></div>
                    <div><dt className="text-xs font-semibold text-slate-500">Budget revision</dt><dd className="mt-1 font-mono text-xs">{sourceVersions.budget_revision}</dd></div>
                  </dl>
                </section>
              )}
            </details></>
          ) : validationStatus !== "rejected" && (
            <Warning title="Report sections unavailable" message="The report result did not include sections; none have been inferred." />
          )}
          <section className="surface-card flex flex-wrap items-center gap-3">
            <label className="text-xs font-semibold text-slate-600">
              Download format
              <select
                className="ml-2 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-normal"
                value={format}
                onChange={(event) => setFormat(event.target.value)}
              >
                {REPORT_FORMATS.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}
              </select>
            </label>
            <button
              className="inline-flex items-center gap-2 rounded-md border border-brand-blue px-3 py-2 text-sm font-semibold text-brand-blue disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              disabled={!reportId || downloading}
              onClick={() => void handleDownload(reportId)}
              title={!reportId ? "This report is not yet available in persisted report history." : undefined}
            >
              <Download size={16} aria-hidden="true" />
              {downloading ? "Preparing…" : `Download ${format.toUpperCase()}`}
            </button>
            {!reportId && <span className="text-xs text-slate-500">Downloads require a persisted report record.</span>}
          </section>
        </div>
      )}

      {profileId && (
        <section className="surface-card">
          <div className="card-heading">
            <div>
              <h2>Report history</h2>
              <p>Previously saved reports for this profile.</p>
            </div>
            {reports.length > 0 && <span className="text-xs text-slate-500">{reports.length} shown</span>}
          </div>
          {reports.length ? (
            <ul className="mt-3 divide-y divide-slate-100">
              {reports.map((record, index) => {
                const item = reportRecordValue(record);
                return (
                  <li className="flex flex-wrap items-center justify-between gap-3 py-3" key={record.id ?? item.report_version ?? index}>
                    <button className="text-left" type="button" onClick={() => showHistoryReport(record)}>
                      <span className="block font-medium text-brand-blue">
                        {item.report_version ?? record.report_version ?? record.id}
                      </span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {record.created_at ? new Date(record.created_at).toLocaleString() : "Saved report"}
                        {item.source_versions?.analysis_version ? ` · ${item.source_versions.analysis_version}` : ""}
                      </span>
                    </button>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={item.validation_status ?? record.status ?? "neutral"} />
                      <button className="rounded-md border border-slate-300 px-3 py-1.5 text-xs text-slate-700" type="button" onClick={() => void handleDownload(record.id)}>
                        Download
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <Empty title="No saved reports" description="Generated reports appear here when report persistence is configured." />
          )}
        </section>
      )}
    </div>
  );
}
