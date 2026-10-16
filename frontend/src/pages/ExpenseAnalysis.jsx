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
import CsvImport from "../components/CsvImport.jsx";
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
  getTransactions,
  correctTransaction,
  updateTransactionSelection,
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
    if (!["income", "expense", "refund", "transfer"].includes(type)) errors.push(`Row ${row}: type must be income, expense, refund or transfer.`);
    if (transaction.category && !CATEGORIES.includes(transaction.category)) {
      errors.push(`Row ${row}: category is not supported.`);
    }
    return Boolean(
      id && !errors.some((message) => message.startsWith(`Row ${row}:`)) &&
      date && !Number.isNaN(Date.parse(date)) &&
      String(transaction.description ?? "").trim() &&
      Number.isFinite(Number(amount)) && Number(amount) > 0 &&
      ["income", "expense", "refund", "transfer"].includes(type) &&
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


function errorText(error) {
  if (error instanceof ApiError && error.code === "persistence_not_configured") {
    return "Your saved workspace is unavailable. Please check the database connection. Configure DATABASE_URL to save transactions and analyses.";
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
    is_current: data.is_current,
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
  const [savedTransactions, setSavedTransactions] = useState([]);
  const [transactionError, setTransactionError] = useState("");
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
  const [editing, setEditing] = useState(null);
  const [selectedRows, setSelectedRows] = useState([]);
  const [deletedRows, setDeletedRows] = useState([]);
  const [correctionMessage, setCorrectionMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [rowErrors, setRowErrors] = useState([]);
  const [validationErrors, setValidationErrors] = useState([]);
  const [notice, setNotice] = useState("");
  const [runKey, setRunKey] = useState(0);
  const skipNextLoadRef = useRef(false);

  useEffect(() => {
    setSelectedRows([]); setDeletedRows([]);
  }, [profileId]);

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

  useEffect(() => {
    if (!profileId) return;
    let active = true;
    getTransactions(profileId).then((data) => { if (active) { setSavedTransactions(data.transactions || []); setTransactionError(""); } })
      .catch((cause) => { if (active) setTransactionError(cause.message); });
    return () => { active = false; };
  }, [profileId, runKey]);

  const summary = analysis?.summary;
  const categoryRows = useMemo(
    () => Object.entries(summary?.category_totals ?? {}).map(([category, total]) => ({
      category: category.replaceAll("_", " "),
      amount: amountOf(total),
      chartAmount: Number(amountOf(total)),
    })).sort((left,right) => right.chartAmount-left.chartAmount),
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

  async function analyzeImported() {
    const envelope = resultEnvelope(await runExpenseAnalysis({ profile_id: profileId }));
    if (envelope.status === "failed") throw new Error("Analysis could not finish. Your transactions are saved; try again.");
    const payload = analysisPayload(envelope);
    setAnalysis(payload); setAnalysisStatus(payload?.status ?? envelope.status);
    const records = await getTransactions(profileId); setSavedTransactions(records.transactions || []);
    setNotice(payload?.status === "success" ? "Your spending analysis is ready below." : "Your totals are ready. Review the note below for any unavailable insights.");
  }

  async function changeSelection(deleted) {
    const ids = deleted ? selectedRows : deletedRows;
    if (!ids.length) return;
    setUploading(true); setError(null);
    try {
      await updateTransactionSelection(profileId, ids, deleted);
      const records = await getTransactions(profileId);
      setSavedTransactions(records.transactions || []);
      setDeletedRows(deleted ? ids : []); setSelectedRows([]); setEditing(null);
      setAnalysis(null); setAnalysisStatus(null);
      setCorrectionMessage(deleted ? "Selected transactions deleted. Analyze again to update your budget." : "Transactions restored. Analyze again to update your results.");
    } catch (cause) { setError(cause); } finally { setUploading(false); }
  }

  async function saveCorrection(event) {
    event.preventDefault(); setError(null); setUploading(true);
    try {
      await correctTransaction(profileId, editing);
      setEditing(null); setAnalysis(null); setAnalysisStatus(null);
      const records = await getTransactions(profileId); setSavedTransactions(records.transactions || []);
      setCorrectionMessage("Saved your correction. Analyze your spending again before creating a budget or report.");
    } catch (cause) { setError(cause); } finally { setUploading(false); }
  }

  async function analyzeSavedTransactions() {
    setLoading(true); setError(null); setNotice("");
    try {
      const envelope = resultEnvelope(await runExpenseAnalysis({ profile_id: profileId }));
      const payload = analysisPayload(envelope);
      setAnalysis(payload); setAnalysisStatus(payload?.status ?? envelope.status);
      setNotice(payload?.status === "success" ? "Analysis complete. Your latest spending insights are below." : "Your figures were updated. Check the analysis limitations for any unavailable AI features.");
    } catch (cause) { setError(cause); } finally { setLoading(false); }
  }

  async function refreshAfterTransactionUpload() {
    await runExpenseAnalysis({ profile_id: profileId });
    const latest = await getLatestExpenseAnalysis(profileId);
    const payload = analysisPayload(latest);
    setAnalysis(payload);
    setAnalysisStatus(payload?.status ?? latest?.status ?? "unknown");
    setRunKey((value) => value + 1);
    setNotice("Transactions were saved and the latest analysis refreshed.");
  }

  async function persistStagedTransactions(batch) {
    await addTransactions(profileId, batch);
    await runExpenseAnalysis({ profile_id: profileId });
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
      await persistStagedTransactions(checkedTransactions);
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
      if (file.name.toLowerCase().endsWith(".json")) {
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
          await runExpenseAnalysis({ profile_id: profileId });
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
      <CsvImport profileId={profileId} onAnalyze={analyzeImported} onBusy={setUploading} />
      <div className="surface-card flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">Analyze saved transactions</h2><p className="mt-1 text-sm text-slate-600">Update insights after changing your transactions.</p></div><button type="button" className="rounded-md bg-brand-blue px-4 py-2 text-white disabled:opacity-50" disabled={!profileId || !savedTransactions.length || loading || uploading} onClick={() => void analyzeSavedTransactions()}>{loading ? "Please wait…" : "Analyze saved transactions"}</button></div>
      {analysis?.is_current === false && <Warning title="Your transactions changed" message="Run Analyze saved transactions again to update these results before creating a budget or report." />}
      {analysisStatus && <StatusBadge status={analysisStatus} label={`Analysis ${analysisStatus}`} />}
      {analysisStatus === "partial" && (
        <Warning title="Partial analysis" message="The agent returned partial results. Review its data gaps and limitations before relying on the analysis." />
      )}
      {analysisStatus === "failed" && (
        <ErrorState title="Analysis failed" message="The agent reported failed status. Results are not presented as a successful analysis." />
      )}
      {deletedRows.length > 0 && <button type="button" disabled={uploading} className="text-brand-blue underline" onClick={() => changeSelection(false)}>Undo deletion ({deletedRows.length})</button>}
      {correctionMessage && <p role="status" className="text-sm text-amber-800">{correctionMessage}</p>}
      {editing && <form className="surface-card space-y-3" onSubmit={saveCorrection}><h2 className="font-semibold">Correct this saved transaction</h2><label className="block text-sm">Description<input aria-label="Correct description" value={editing.description} onChange={(event) => setEditing({ ...editing, description:event.target.value })} className="ml-2 rounded border p-2" required /></label><label className="block text-sm">Date<input aria-label="Correct date" type="date" value={editing.date} onChange={(event) => setEditing({ ...editing, date:event.target.value })} className="ml-2 rounded border p-2" required /></label><label className="block text-sm">Amount<input aria-label="Correct amount" type="number" min="0.01" step="0.01" value={editing.amount.amount} onChange={(event) => setEditing({ ...editing, amount:{amount:event.target.value} })} className="ml-2 rounded border p-2" required /></label><label className="block text-sm">Type<select aria-label="Correct type" value={editing.type} onChange={(event) => setEditing({ ...editing, type:event.target.value })} className="ml-2 rounded border p-2">{["income","expense","refund","transfer"].map((kind) => <option key={kind}>{kind}</option>)}</select></label><label className="block text-sm">Category<select aria-label="Correct category" value={editing.category || "other"} onChange={(event) => setEditing({...editing, category:event.target.value})} className="ml-2 rounded border p-2">{CATEGORIES.map((category) => <option key={category}>{category}</option>)}</select></label><label className="block text-sm">Recurring payment<select aria-label="Recurring payment" className="ml-2 rounded border p-2" value={editing.is_recurring == null ? "unknown" : String(editing.is_recurring)} onChange={(event) => setEditing({...editing, is_recurring:event.target.value === "unknown" ? null : event.target.value === "true"})}><option value="unknown">Not sure</option><option value="true">Yes</option><option value="false">No</option></select></label><button disabled={uploading} className="rounded bg-brand-blue px-4 py-2 text-white">Save correction</button><button className="ml-3 underline" type="button" onClick={() => setEditing(null)}>Cancel</button></form>}
      {notice && <p className="text-sm text-slate-600" role="status">{notice}</p>}

      <details className="surface-card space-y-4"><summary className="cursor-pointer font-semibold">Add transactions manually or import JSON</summary>
        <h2 className="text-base font-semibold text-slate-800">Add your income and expenses</h2>
        <p className="text-sm text-slate-500">Add transactions to the list below, then choose Save and analyze. Your account keeps your saved history.</p>
        <details className="profile-settings"><summary>Profile and currency settings</summary>
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
        </details>
        <label className="block text-sm font-medium text-slate-700">
          Import JSON transactions
          <input className="mt-2 block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-2" type="file" accept=".json,application/json" onChange={onUploadFile} disabled={uploading} />
        </label>
        <p className="text-xs text-slate-500">
          For bank CSV files, use the guided upload above. JSON imports are intended for advanced users.
        </p>
        <form className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6" onSubmit={addManualTransaction}>
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction ID" placeholder="ID (optional)" value={manual.id} onChange={(event) => updateManual("id", event.target.value)} />
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction date" type="date" value={manual.date} onChange={(event) => updateManual("date", event.target.value)} required />
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Description" placeholder="Description" value={manual.description} onChange={(event) => updateManual("description", event.target.value)} required />
          <input className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Amount" inputMode="decimal" placeholder="Amount" value={manual.amount} onChange={(event) => updateManual("amount", event.target.value)} required />
          <select className="rounded-md border border-slate-300 px-3 py-2 text-sm" aria-label="Transaction type" value={manual.type} onChange={(event) => updateManual("type", event.target.value)}>
            <option value="expense">Expense</option>
            <option value="income">Income</option><option value="refund">Refund received</option><option value="transfer">Transfer between own accounts</option>
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
              <button className="rounded-md bg-brand-blue px-3 py-2 text-sm font-semibold text-white" type="button" onClick={runAnalysis} disabled={loading}>{loading ? "Saving and analyzing…" : "Save and analyze"}</button>
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
      </details>

      {loading && <Loading label="Loading expense analysis" />}
      {transactionError && <ErrorState title="Saved transactions unavailable" message={transactionError} />}
      <details className="surface-card"><summary className="cursor-pointer font-semibold">Your saved transactions ({savedTransactions.length}) — manage</summary><div className="my-3 flex gap-4 items-center"><label><input type="checkbox" aria-label="Select all saved transactions" checked={savedTransactions.length > 0 && selectedRows.length === savedTransactions.length} onChange={(event) => setSelectedRows(event.target.checked ? savedTransactions.map((row) => row.id) : [])} /> Select all</label><button type="button" disabled={!selectedRows.length || uploading} className="rounded border border-red-300 px-3 py-2 text-red-700 disabled:opacity-50" onClick={() => changeSelection(true)}>Delete selected ({selectedRows.length})</button></div><DataTable rows={savedTransactions} getRowKey={(row) => row.id} emptyTitle="No saved transactions yet. Add your first expense above." columns={[
        { key: "select", header: "Select", render: (row) => <input type="checkbox" aria-label={`Select ${row.description} ${row.date} ${row.id}`} checked={selectedRows.includes(row.id)} onChange={(event) => setSelectedRows((ids) => event.target.checked ? [...ids,row.id] : ids.filter((id) => id !== row.id))} /> },
        { key: "date", header: "Date" }, { key: "description", header: "Description" },
        { key: "type", header: "Type" }, { key: "category", header: "Category", render: (row) => (row.category || "Uncategorized").replaceAll("_", " ") },
        { key: "amount", header: "Amount", numeric: true, render: (row) => formatMoney(row.amount?.amount, currency) },
        { key: "edit", header: "Correct", render: (row) => <button type="button" className="text-brand-blue underline" onClick={() => { setEditing(row); setCorrectionMessage(""); }}>Edit {row.description}</button> },
      ]} /></details>
      {!loading && !analysis && !error && transactions.length === 0 && (
        <Empty title="Start with your transactions" description="Upload a CSV, check its preview, then choose Analyze my spending. We will explain where your money went." />
      )}
      {analysis && analysisStatus !== "failed" && (
        <>
          {analysis.limitations?.length > 0 && (
            <Warning title="Analysis limitations" message={analysis.limitations.map((item) => item.message ?? item).join(" · ")} />
          )}
          {summary ? (
            <>
              <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Expense summary">
                <MetricCard label="Total money received" value={formatMoney(amountOf(summary.received_total) ?? Number(amountOf(summary.monthly_income)) * summary.months_covered, summary.currency)} />
                <MetricCard label="Total money spent" value={formatMoney(amountOf(summary.spent_total) ?? Number(amountOf(summary.monthly_expenses)) * summary.months_covered, summary.currency)} />
                <MetricCard label="Money left over" value={formatMoney(summary.received_total && summary.spent_total ? Number(amountOf(summary.received_total)) - Number(amountOf(summary.spent_total)) : Number(amountOf(summary.available_surplus)) * summary.months_covered, summary.currency)} />
                <MetricCard label="Months covered" value={String(summary.months_covered ?? "—")} detail={`${summary.period_start ?? ""}${summary.period_end ? ` – ${summary.period_end}` : ""}`} />
              </section>
              <p className="text-sm text-slate-600">Period: {summary.period_start} to {summary.period_end} · {summary.currency} · {summary.transaction_count ?? savedTransactions.length} transactions. Money left over = money received minus money spent. Transfers between your own accounts are excluded. These figures describe the uploaded period, not your bank balance.</p>
              {Number(amountOf(summary.refund_total)) > 0 && <p className="text-sm text-amber-800">Money received includes {formatMoney(amountOf(summary.refund_total), summary.currency)} in refunds. Refunds are returned money, not regular earnings. Keep this in mind when setting a monthly budget.</p>}
              <section className="surface-card"><h2 className="font-semibold">What this means</h2><p className="mt-2 text-sm">{Number(amountOf(summary.available_surplus)) >= 0 ? "You received more money than you spent. You can use the money left over toward a savings goal." : "You spent more than you received. Review your largest spending categories before choosing a savings target."}</p><p className="mt-2 text-sm">Monthly average: {formatMoney(amountOf(summary.monthly_income), summary.currency)} received and {formatMoney(amountOf(summary.monthly_expenses), summary.currency)} spent.</p><a href="/budget-planning" className="mt-3 inline-block text-brand-blue underline">Next: create my monthly budget →</a></section>
              {summary.monthly_breakdown?.length > 1 && <section className="surface-card"><h2 className="font-semibold">Your money month by month</h2><DataTable rows={summary.monthly_breakdown} getRowKey={(row) => row.month} columns={[{key:"month",header:"Month"},{key:"received",header:"Received",render:(row) => formatMoney(row.received,summary.currency)},{key:"spent",header:"Spent",render:(row) => formatMoney(row.spent,summary.currency)}]} /></section>}
              <section className="grid gap-4 xl:grid-cols-2">
                <ChartCard title="Spending by category" description="Monthly category totals from the analysis.">
                  {categoryRows.length ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={categoryRows} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                        <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" vertical={false} />
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

          <section className="surface-card"><h2 className="text-base font-semibold text-slate-800">Your spending insights</h2>{analysis.spending_patterns?.length ? <ul className="mt-3 space-y-4">{analysis.spending_patterns.map((insight, index) => <li key={index}><h3 className="font-semibold">{insight.title}</h3><p className="mt-1 text-sm text-slate-600">{insight.detail}</p></li>)}</ul> : <p className="mt-3 text-sm text-slate-600">No AI spending insights are available for this analysis. Your calculated totals are shown above; check the limitations for the reason.</p>}</section>
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
            <details className="surface-card">
              <summary className="cursor-pointer font-semibold">Possible duplicates ({duplicates.length})</summary><p className="mt-2 text-sm text-slate-600">Matching date, merchant and amount. Review saved transactions; keep both only if they are separate purchases.</p>
              {duplicates.length ? (
                <ul className="mt-3 space-y-3">{duplicates.map((item) => <li className="rounded-md border border-amber-200 bg-amber-50 p-3" key={item.transaction_id}><p className="font-medium text-amber-900">{savedTransactions.find((row) => row.id === item.transaction_id)?.description || "Expense"} · {formatMoney(amountOf(item.amount), summary?.currency)}</p><p className="mt-1 text-sm text-amber-800">{item.reason}</p></li>)}</ul>
              ) : <Empty title="No possible duplicates reported" />}
            </details>
          </section>

          <details className="surface-card">
            <summary className="cursor-pointer font-semibold">Unusual expenses ({outliers.length})</summary>
            {outliers.length ? (
              <ul className="mt-3 space-y-3">{outliers.map((item) => <li className="rounded-md border border-slate-200 p-3" key={item.transaction_id}><p className="font-medium text-slate-800">{savedTransactions.find((row) => row.id === item.transaction_id)?.description || "Expense"} · {formatMoney(amountOf(item.amount), summary?.currency)}</p><p className="mt-1 text-sm text-slate-600"><strong>Reason:</strong> {item.reason}</p></li>)}</ul>
            ) : <Empty title="No outliers reported" />}
          </details>

          <details className="surface-card">
            <summary className="cursor-pointer font-semibold">Details to review</summary><p className="mt-2 text-sm text-slate-600">Some rows are missing a category or recurring-payment setting. Use Edit in saved transactions to correct them.</p>
            {(analysis.data_gaps ?? []).length ? (
              <ul className="mt-3 space-y-3">{analysis.data_gaps.filter((gap, index, gaps) => gaps.findIndex((item) => item.transaction_id === gap.transaction_id && item.question === gap.question) === index && (gap.transaction_id || !gaps.some((item) => item.transaction_id && item.question === gap.question))).map((gap, index) => <li className="rounded-md border border-amber-200 bg-amber-50 p-3" key={`${gap.transaction_id ?? "gap"}-${index}`}><p className="font-medium text-amber-900">{savedTransactions.find((transaction) => transaction.id === gap.transaction_id)?.description || "A detail to review"}{gap.transaction_id && <span className="ml-2 text-xs font-normal">{savedTransactions.find((transaction) => transaction.id === gap.transaction_id)?.date}</span>}</p><p className="mt-1 text-sm text-amber-800">{gap.question}</p></li>)}</ul>
            ) : <Empty title="No data gaps reported" />}
          </details>
          <details className="surface-card"><summary className="cursor-pointer font-medium">Analysis details</summary><div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="text-sm font-semibold text-slate-700">Saved analysis reference</h2><p className="mt-1 break-all font-mono text-xs text-slate-500">{analysis.analysis_version ?? "Not provided"}</p></div>
            <button className="rounded-md border border-slate-300 px-3 py-2 text-sm" type="button" onClick={() => setRunKey((value) => value + 1)} disabled={loading}>Refresh latest analysis</button>
          </div></details>
        </>
      )}
    </div>
  );
}
