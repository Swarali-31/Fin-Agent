import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import ChartCard from "../components/ChartCard.jsx";
import DataTable from "../components/DataTable.jsx";
import MetricCard from "../components/MetricCard.jsx";
import { Empty, ErrorState, Loading, Warning } from "../components/StateViews.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { ApiError } from "../services/api.js";
import { runExpenseAnalysis } from "../services/agents.js";
import {
  addTransactions,
  getLatestExpenseAnalysis,
  getProfileSummary,
  uploadTransactionsCsv,
} from "../services/profiles.js";

const PROFILE_KEY = "finagent.profileId";
const CURRENCY_KEY = "finagent.currency";
const CATEGORIES = [
  "housing", "groceries", "utilities", "transport", "dining", "entertainment",
  "healthcare", "education", "insurance", "debt_payment", "subscriptions",
  "shopping", "travel", "other",
];

function getStored(key, fallback = "") {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function setStored(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // The page remains usable if browser storage is disabled.
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

function newId() {
  return globalThis.crypto?.randomUUID?.() ??
    `txn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function validateTransactions(value, existingIds = []) {
  const transactions = Array.isArray(value)
    ? value
    : Array.isArray(value?.transactions)
      ? value.transactions
      : null;
  if (!transactions) return { transactions: [], errors: ["Expected a JSON array or an object with a transactions array."] };
  const errors = [];
  const ids = new Set(existingIds);
  const valid = transactions.filter((transaction, index) => {
    const row = index + 1;
    if (!transaction || typeof transaction !== "object" || Array.isArray(transaction)) {
      errors.push(`Row ${row}: transaction must be an object.`);
      return false;
    }
    const id = transaction.id ?? transaction.transaction_id;
    const date = transaction.date;
    const amount = amountOf(transaction.amount);
    const type = transaction.type ?? transaction.transaction_type;
    if (!id || typeof id !== "string") errors.push(`Row ${row}: id is required.`);
    else if (ids.has(id)) errors.push(`Row ${row}: duplicate id "${id}".`);
    else ids.add(id);
    if (!date || Number.isNaN(Date.parse(date))) errors.push(`Row ${row}: date must be valid.`);
    if (!String(transaction.description ?? "").trim()) errors.push(`Row ${row}: description is required.`);
    if (amount === undefined || amount === null || amount === "" || !Number.isFinite(Number(amount)) || Number(amount) <= 0) {
      errors.push(`Row ${row}: amount must be a positive number.`);
    }
    if (!["income", "expense"].includes(type)) errors.push(`Row ${row}: type must be income or expense.`);
    if (transaction.category && !CATEGORIES.includes(transaction.category)) {
      errors.push(`Row ${row}: category is not supported.`);
    }
    return Boolean(
      id && !errors.some((message) => message.startsWith(`Row ${row}:`)) &&
      date && !Number.isNaN(Date.parse(date)) &&
      String(transaction.description ?? "").trim() &&
      Number.isFinite(Number(amount)) && Number(amount) > 0 &&
      ["income", "expense"].includes(type) &&
      (!transaction.category || CATEGORIES.includes(transaction.category)),
    );
  });
  return {
    transactions: valid.map((transaction) => ({
      ...transaction,
      id: transaction.id ?? transaction.transaction_id,
      type: transaction.type ?? transaction.transaction_type,
      amount: { amount: String(amountOf(transaction.amount)) },
    })),
    errors,
  };
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted && character === '"' && text[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (!quoted && character === ",") {
      row.push(cell);
      cell = "";
    } else if (!quoted && (character === "\n" || character === "\r")) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      if (row.some((part) => part.trim())) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += character;
    }
  }
  row.push(cell);
  if (row.some((part) => part.trim())) rows.push(row);
  if (quoted) throw new Error("CSV contains an unclosed quoted field.");
  const headers = (rows.shift() ?? []).map((header) => header.trim());
  const required = ["id", "date", "description", "amount", "type"];
  const missing = required.filter((field) => !headers.includes(field));
  if (missing.length) throw new Error(`CSV is missing required columns: ${missing.join(", ")}.`);
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

function errorText(error) {
  if (error instanceof ApiError && error.code === "persistence_not_configured") {
    return "The server returned 503 persistence_not_configured. Configure DATABASE_URL to save transactions and analyses.";
  }
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function serverRowErrors(error) {
  return error?.details?.row_errors ?? error?.details?.errors ?? [];
}

function analysisPayload(data) {
  if (!data?.result) return data;
  return {
    ...data.result,
    analysis_version: data.analysis_version ?? data.result.analysis_version,
    status: data.status ?? data.result.status,
  };
}

function resultEnvelope(value) {
  return value?.result ? value : { status: value?.status ?? "unknown", result: value };
}

export default function ExpenseAnalysis() {
  const [profileId, setProfileId] = useState(() => getStored(PROFILE_KEY));
  const [profileInput, setProfileInput] = useState(() => getStored(PROFILE_KEY));
  const [currency, setCurrency] = useState(() => getStored(CURRENCY_KEY, "INR"));
  const [transactions, setTransactions] = useState([]);
  const [manual, setManual] = useState({
    id: "",
    date: new Date().toISOString().slice(0, 10),
    description: "",
    amount: "",
    type: "expense",
    category: "other",
  });
  const [analysis, setAnalysis] = useState(null);
  const [analysisStatus, setAnalysisStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [rowErrors, setRowErrors] = useState([]);
  const [validationErrors, setValidationErrors] = useState([]);
  const [notice, setNotice] = useState("");
  const [runKey, setRunKey] = useState(0);
  const skipNextLoadRef = useRef(false);

  useEffect(() => {
    if (!profileId) return undefined;
    if (skipNextLoadRef.current) {
      skipNextLoadRef.current = false;
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setAnalysis(null);
    setAnalysisStatus(null);
    Promise.allSettled([getLatestExpenseAnalysis(profileId)])
      .then(([result]) => {
        if (cancelled) return;
        if (result.status === "fulfilled") {
          const payload = analysisPayload(result.value);
          setAnalysis(payload);
          setAnalysisStatus(payload?.status ?? result.value?.status ?? "unknown");
          setStored(PROFILE_KEY, profileId);
        } else if (result.reason?.status !== 404 && result.reason?.code !== "analysis_not_found") {
          setError(result.reason);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [profileId, runKey]);

  const summary = analysis?.summary;
  const categoryRows = useMemo(
    () => Object.entries(summary?.category_totals ?? {}).map(([category, total]) => ({
      category: category.replaceAll("_", " "),
      amount: amountOf(total),
      chartAmount: Number(amountOf(total)),
    })),
    [summary],
  );
  const duplicates = (analysis?.unusual_transactions ?? []).filter((item) => item.kind === "possible_duplicate");
  const outliers = (analysis?.unusual_transactions ?? []).filter((item) => item.kind === "outlier");

  function updateManual(field, value) {
    setManual((previous) => ({ ...previous, [field]: value }));
  }

  function addManualTransaction(event) {
    event.preventDefault();
    const prepared = {
      ...manual,
      id: manual.id.trim() || newId(),
      amount: manual.amount.trim(),
      description: manual.description.trim(),
    };
    const checked = validateTransactions([prepared], transactions.map((item) => item.id));
    if (checked.errors.length) {
      setValidationErrors(checked.errors);
      return;
    }
    setValidationErrors([]);
    setTransactions((previous) => [...previous, ...checked.transactions]);
    setManual({
      id: "",
      date: new Date().toISOString().slice(0, 10),
      description: "",
      amount: "",
      type: "expense",
      category: "other",
    });
  }

  async function refreshAfterTransactionUpload() {
    await getProfileSummary(profileId);
    const latest = await getLatestExpenseAnalysis(profileId);
    const payload = analysisPayload(latest);
    setAnalysis(payload);
    setAnalysisStatus(payload?.status ?? latest?.status ?? "unknown");
    setRunKey((value) => value + 1);
    setNotice("Transactions were saved and the latest analysis refreshed.");
  }

  async function persistStagedTransactions(batch) {
    await addTransactions(profileId, batch);
    await getProfileSummary(profileId);
    const latest = await getLatestExpenseAnalysis(profileId);
    const payload = analysisPayload(latest);
    setAnalysis(payload);
    setAnalysisStatus(payload?.status ?? latest?.status ?? "unknown");
    setTransactions([]);
    setRunKey((value) => value + 1);
    setNotice("Transactions were saved and the latest analysis refreshed.");
  }

  async function uploadToExistingProfile(file, checkedTransactions) {
    setUploading(true);
    setError(null);
    setRowErrors([]);
    try {
      if (file.name.toLowerCase().endsWith(".csv")) {
        await uploadTransactionsCsv(profileId, file);
        await refreshAfterTransactionUpload();
      } else {
        await persistStagedTransactions(checkedTransactions);
      }
    } catch (uploadError) {
      setError(uploadError);
      setRowErrors(serverRowErrors(uploadError));
    } finally {
      setUploading(false);
    }
  }

  async function onUploadFile(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setError(null);
    setRowErrors([]);
    setValidationErrors([]);
    setNotice("");
    try {
      if (file.name.toLowerCase().endsWith(".csv")) {
        const parsed = parseCsv(await file.text());
        const checked = validateTransactions(parsed, transactions.map((item) => item.id));
        setValidationErrors(checked.errors);
        if (!checked.transactions.length) return;
        if (profileId && transactions.length === 0) {
          await uploadToExistingProfile(file, checked.transactions);
        } else {
          setTransactions((previous) => [...previous, ...checked.transactions]);
          setNotice(`${checked.transactions.length} CSV row(s) validated and staged.`);
        }
      } else if (file.name.toLowerCase().endsWith(".json")) {
        const checked = validateTransactions(
          JSON.parse(await file.text()),
          transactions.map((item) => item.id),
        );
        setValidationErrors(checked.errors);
        if (!checked.transactions.length) return;
        if (profileId && transactions.length === 0) {
          await uploadToExistingProfile(file, checked.transactions);
        } else {
          setTransactions((previous) => [...previous, ...checked.transactions]);
          setNotice(`${checked.transactions.length} JSON transaction(s) validated and staged.`);
        }
      } else {
        setValidationErrors(["Choose a .json or .csv file."]);
      }
    } catch (uploadError) {
      setValidationErrors([errorText(uploadError)]);
    }
  }

  async function saveStagedTransactions() {
    if (!profileId) {
      setNotice("Transactions are staged locally. Run analysis to create the profile and save these transactions.");
      return;
    }
    setUploading(true);
    setError(null);
    setRowErrors([]);
    try {
      await persistStagedTransactions(transactions);
    } catch (uploadError) {
      setError(uploadError);
      setRowErrors(serverRowErrors(uploadError));
    } finally {
      setUploading(false);
    }
  }

  async function runAnalysis(event) {
    event?.preventDefault();
    if (!profileId && !profileInput.trim()) {
      setValidationErrors(["Enter a profile ID before running the analysis."]);
      return;
    }
    if (!transactions.length) {
      if (profileId) {
        setLoading(true);
        setError(null);
        try {
          await getProfileSummary(profileId);
          const latest = await getLatestExpenseAnalysis(profileId);
          const payload = analysisPayload(latest);
          setAnalysis(payload);
          setAnalysisStatus(payload?.status ?? latest?.status ?? "unknown");
        } catch (runError) {
          setError(runError);
        } finally {
          setLoading(false);
        }
        return;
      }
      setValidationErrors(["Add at least one transaction before running analysis."]);
      return;
    }
    if (profileId) {
      setLoading(true);
      setError(null);
      setRowErrors([]);
      setValidationErrors([]);
      setNotice("");
      try {
        await persistStagedTransactions(transactions);
      } catch (runError) {
        setError(runError);
        setRowErrors(serverRowErrors(runError));
      } finally {
        setLoading(false);
      }
      return;
    }
    const selectedProfileId = profileId || profileInput.trim();
    setLoading(true);
    setError(null);
    setRowErrors([]);
    setValidationErrors([]);
    setNotice("");
    try {
      const response = resultEnvelope(await runExpenseAnalysis({
        profile: {
          profile_id: selectedProfileId,
          currency,
          transactions,
        },
      }));
      setAnalysis(response.result);
      setAnalysisStatus(response.status ?? response.result?.status ?? "unknown");
      if (selectedProfileId !== profileId) {
        skipNextLoadRef.current = true;
        setProfileId(selectedProfileId);
      }
      setProfileInput(selectedProfileId);
      setStored(PROFILE_KEY, selectedProfileId);
      setStored(CURRENCY_KEY, currency);
      setTransactions([]);
      setNotice("Analysis completed. Its full result is shown below.");
    } catch (runError) {
      setError(runError);
      setRowErrors(serverRowErrors(runError));
    } finally {
      setLoading(false);
    }
  }

  const moneyColumns = [
    { key: "category", header: "Category" },
    { key: "amount", header: `Monthly total (${currency})`, numeric: true, render: (row) => formatMoney(row.amount, currency) },
  ];

  return (
    <div className="space-y-6">
      <section>
        <h1 className="page-title">Expense Analysis</h1>
        <p className="mt-2 text-sm text-slate-600">Import or enter transactions, then run the expense analysis agent.</p>
      </section>

      {error && (
        <ErrorState
          title={error.code === "persistence_not_configured" ? "Persistence is not configured" : "Expense analysis request failed"}
          message={errorText(error)}
          onRetry={() => setRunKey((value) => value + 1)}
        />
      )}
      {analysisStatus && <StatusBadge status={analysisStatus} label={`Analysis ${analysisStatus}`} />}
      {analysisStatus === "partial" && (
        <Warning title="Partial analysis" message="The agent returned partial results. Review its data gaps and limitations before relying on the analysis." />
      )}
      {analysisStatus === "failed" && (
        <ErrorState title="Analysis failed" message="The agent reported failed status. Results are not presented as a successful analysis." />
      )}
      {notice && <p className="text-sm text-slate-600" role="status">{notice}</p>}

      <section className="surface-card space-y-4">
        <h2 className="text-base font-semibold text-slate-800">Profile and transactions</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold text-slate-600">
            Profile ID
            <input className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal" value={profileInput} onChange={(event) => setProfileInput(event.target.value)} placeholder="profile-123" />
          </label>
          <label className="text-xs font-semibold text-slate-600">
            Currency
            <input className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-normal uppercase" maxLength={3} value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} />
          </label>
        </div>
        <label className="block text-sm font-medium text-slate-700">
          Upload transaction JSON or CSV
          <input className="mt-2 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-2" type="file" accept=".json,.csv,application/json,text/csv" onChange={onUploadFile} disabled={uploading} />
        </label>
        <p className="text-xs text-slate-500">
          CSV columns: id, date, description, amount, type; optional merchant, category, is_recurring. New profiles are created when analysis runs; existing profiles can save staged rows directly.
        </p>
        <form className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6" onSubmit={addManualTransaction}>
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction ID" placeholder="ID (optional)" value={manual.id} onChange={(event) => updateManual("id", event.target.value)} />
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction date" type="date" value={manual.date} onChange={(event) => updateManual("date", event.target.value)} required />
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Description" placeholder="Description" value={manual.description} onChange={(event) => updateManual("description", event.target.value)} required />
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Amount" inputMode="decimal" placeholder="Amount" value={manual.amount} onChange={(event) => updateManual("amount", event.target.value)} required />
          <select className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction type" value={manual.type} onChange={(event) => updateManual("type", event.target.value)}>
            <option value="expense">Expense</option>
            <option value="income">Income</option>
          </select>
          <select className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction category" value={manual.category} onChange={(event) => updateManual("category", event.target.value)}>
            {CATEGORIES.map((category) => <option key={category} value={category}>{category.replaceAll("_", " ")}</option>)}
          </select>
          <button className="rounded-md border border-brand-blue px-3 py-2 text-sm font-semibold text-brand-blue sm:col-span-2 xl:col-span-6" type="submit">Add transaction</button>
        </form>
        {validationErrors.length > 0 && (
          <div role="alert" className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p className="font-semibold">Check the transaction data</p>
            <ul className="mt-2 list-inside list-disc">{validationErrors.map((message, index) => <li key={`${message}-${index}`}>{message}</li>)}</ul>
          </div>
        )}
        {transactions.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
            <p className="text-sm text-slate-600">{transactions.length} validated transaction(s) staged.</p>
            <div className="flex gap-2">
              {profileId && <button className="rounded-md border border-slate-300 px-3 py-2 text-sm" type="button" onClick={saveStagedTransactions} disabled={uploading}>{uploading ? "Saving…" : "Save transactions"}</button>}
              <button className="rounded-md bg-brand-blue px-3 py-2 text-sm font-semibold text-white" type="button" onClick={runAnalysis} disabled={loading}>{loading ? "Analyzing…" : "Run analysis"}</button>
            </div>
          </div>
        )}
        {rowErrors.length > 0 && (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-3">
            <h3 className="font-semibold text-red-800">Server rejected transaction rows</h3>
            <ul className="mt-2 space-y-2 text-sm text-red-700">
              {rowErrors.map((rowError, index) => (
                <li key={`${rowError.row ?? "row"}-${index}`}>
                  Row {rowError.row ?? index + 1}: {rowError.message ?? rowError.code}
                  {rowError.errors?.map((issue) => <div className="ml-3 text-xs" key={`${issue.field}-${issue.message}`}>{issue.field}: {issue.message}</div>)}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {loading && <Loading label="Loading expense analysis" />}
      {!loading && !analysis && !error && transactions.length === 0 && (
        <Empty title="No expense analysis yet" description="Add transactions above and run the analysis. Results are produced by the expense-analysis API." />
      )}
      {analysis && analysisStatus !== "failed" && (
        <>
          {analysis.limitations?.length > 0 && (
            <Warning title="Analysis limitations" message={analysis.limitations.map((item) => item.message ?? item).join(" · ")} />
          )}
          {summary ? (
            <>
              <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Expense summary">
                <MetricCard label="Monthly income" value={formatMoney(amountOf(summary.monthly_income), summary.currency)} />
                <MetricCard label="Monthly expenses" value={formatMoney(amountOf(summary.monthly_expenses), summary.currency)} />
                <MetricCard label="Available surplus" value={formatMoney(amountOf(summary.available_surplus), summary.currency)} />
                <MetricCard label="Months covered" value={String(summary.months_covered ?? "—")} detail={`${summary.period_start ?? ""}${summary.period_end ? ` – ${summary.period_end}` : ""}`} />
              </section>
              <section className="grid gap-4 xl:grid-cols-2">
                <ChartCard title="Spending by category" description="Monthly category totals from the analysis.">
                  {categoryRows.length ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={categoryRows} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                        <CartesianGrid stroke="#E2E8F0" strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="category" tickLine={false} axisLine={false} />
                        <YAxis tickLine={false} axisLine={false} width={72} />
                        <Tooltip formatter={(value) => formatMoney(value, summary.currency)} />
                        <Bar dataKey="chartAmount" name="Monthly spend" fill="#072F5F" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  ) : <Empty title="No category totals were returned" />}
                </ChartCard>
                <section className="surface-card">
                  <h2 className="text-base font-semibold text-slate-800">Category breakdown</h2>
                  <div className="mt-4"><DataTable columns={moneyColumns} rows={categoryRows} getRowKey={(row) => row.category} emptyTitle="No category totals were returned" /></div>
                </section>
              </section>
            </>
          ) : (
            <Warning title="Summary not returned" message="The agent did not provide a financial summary; no metric values are inferred." />
          )}

          <section className="grid gap-4 xl:grid-cols-2">
            <section className="surface-card">
              <h2 className="text-base font-semibold text-slate-800">Recurring expenses</h2>
              {(analysis.recurring_expenses ?? []).length ? (
                <ul className="mt-3 divide-y divide-slate-100">
                  {analysis.recurring_expenses.map((item, index) => (
                    <li className="flex flex-wrap justify-between gap-2 py-3" key={`${item.description}-${index}`}>
                      <span>{item.description} <span className="text-xs text-slate-500">· {item.category} · {item.occurrences} occurrences</span></span>
                      <strong>{formatMoney(amountOf(item.monthly_amount), summary?.currency)}</strong>
                    </li>
                  ))}
                </ul>
              ) : <Empty title="No recurring expenses reported" />}
            </section>
            <section className="surface-card">
              <h2 className="text-base font-semibold text-slate-800">Possible duplicates</h2>
              {duplicates.length ? (
                <ul className="mt-3 space-y-3">{duplicates.map((item) => <li className="rounded-md border border-amber-200 bg-amber-50 p-3" key={item.transaction_id}><p className="font-medium text-amber-900">{item.transaction_id} · {formatMoney(amountOf(item.amount), summary?.currency)}</p><p className="mt-1 text-sm text-amber-800">{item.reason}</p></li>)}</ul>
              ) : <Empty title="No possible duplicates reported" />}
            </section>
          </section>

          <section className="surface-card">
            <h2 className="text-base font-semibold text-slate-800">Outliers</h2>
            {outliers.length ? (
              <ul className="mt-3 space-y-3">{outliers.map((item) => <li className="rounded-md border border-slate-200 p-3" key={item.transaction_id}><p className="font-medium text-slate-800">{item.transaction_id} · {formatMoney(amountOf(item.amount), summary?.currency)}</p><p className="mt-1 text-sm text-slate-600"><strong>Reason:</strong> {item.reason}</p></li>)}</ul>
            ) : <Empty title="No outliers reported" />}
          </section>

          <section className="surface-card">
            <h2 className="text-base font-semibold text-slate-800">Data gaps and clarifying questions</h2>
            {(analysis.data_gaps ?? []).length ? (
              <ul className="mt-3 space-y-3">{analysis.data_gaps.map((gap, index) => <li className="rounded-md border border-amber-200 bg-amber-50 p-3" key={`${gap.transaction_id ?? "gap"}-${index}`}><p className="font-medium text-amber-900">{gap.issue}</p>{gap.transaction_id && <p className="mt-1 text-xs text-amber-800">Transaction: {gap.transaction_id}</p>}<p className="mt-1 text-sm text-amber-800">{gap.question}</p></li>)}</ul>
            ) : <Empty title="No data gaps reported" />}
          </section>
          <section className="surface-card flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-sm font-semibold text-slate-700">Analysis version</h2><p className="mt-1 break-all font-mono text-xs text-slate-500">{analysis.analysis_version ?? "Not provided"}</p></div>
            <button className="rounded-md border border-slate-300 px-3 py-2 text-sm" type="button" onClick={() => setRunKey((value) => value + 1)} disabled={loading}>Refresh latest analysis</button>
          </section>
        </>
      )}
    </div>
  );
}
