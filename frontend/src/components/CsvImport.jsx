import { useEffect, useRef, useState } from "react";
import { addTransactions, previewTransactionsCsv } from "../services/profiles.js";

const CATEGORIES = ["housing","groceries","utilities","transport","dining","entertainment","healthcare","education","insurance","debt_payment","subscriptions","shopping","travel","other"];
const FIELDS = { date: "Date", description: "Description or merchant", amount: "Amount", debit: "Debit / money out", credit: "Credit / money in", type: "Transaction type", category: "Category (optional)", id: "Reference / ID (optional)", currency: "Currency (optional)", is_recurring: "Recurring (optional)" };
export default function CsvImport({ profileId, onAnalyze, onBusy }) {
  const [typeOverrides, setTypeOverrides] = useState({});
  const [categoryOverrides, setCategoryOverrides] = useState({});
  const [showAll, setShowAll] = useState(false);
  const [file, setFile] = useState(null);
  const [text, setText] = useState("");
  const [mapping, setMapping] = useState(null);
  const [dateFormat, setDateFormat] = useState("auto");
  const [convention, setConvention] = useState("auto");
  const [numberFormat, setNumberFormat] = useState("decimal_point");
  const [preview, setPreview] = useState(null);
  const [excluded, setExcluded] = useState([]);
  const [duplicatePolicy, setDuplicatePolicy] = useState("review");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState("");
  const [saved, setSaved] = useState(false);
  const [finished, setFinished] = useState(false);
  const generation = useRef(0);
  useEffect(() => { onBusy?.(Boolean(phase)); return () => onBusy?.(false); }, [phase,onBusy]);
  useEffect(() => { setTypeOverrides({}); setCategoryOverrides({}); setShowAll(false); }, [preview]);
  useEffect(() => { setFile(null); setText(""); setPreview(null); setSaved(false); setFinished(false); setError(""); }, [profileId]);
  useEffect(() => {
    if (!text || !profileId || saved) return;
    let cancelled = false;
    const run = ++generation.current;
    setLoading(true); setError("");
    const timer = setTimeout(() => {
      previewTransactionsCsv(profileId, { csv_text: text, mapping, date_format: dateFormat, convention, number_format: numberFormat })
        .then((value) => { if (!cancelled && run === generation.current) setPreview(value); })
        .catch((cause) => { if (!cancelled) { setError(cause.message); setPreview(null); } })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [text, profileId, mapping, dateFormat, convention, numberFormat, saved]);
  async function selectFile(event) {
    const selected = event.target.files?.[0]; event.target.value = "";
    if (!selected) return;
    setError(""); setPreview(null); setSaved(false); setFinished(false); setExcluded([]); setMapping(null); setDateFormat("auto"); setConvention("auto"); setNumberFormat("decimal_point"); setDuplicatePolicy("review");
    if (!selected.name.toLowerCase().endsWith(".csv")) { setError("Choose a CSV file. PDF bank statements and spreadsheets must be exported as CSV first."); setText(""); return; }
    if (selected.size > 2_000_000) { setError("Choose a CSV smaller than 2 MB."); setText(""); return; }
    setFile(selected.name);
    try { setText(await selected.text()); } catch { setError("This file could not be read. Export it as UTF-8 CSV and try again."); }
  }
  const rows = (preview?.rows || []).map((row) => row.transaction ? { ...row, transaction:{ ...row.transaction, type:typeOverrides[row.row] || row.transaction.type, category: Object.hasOwn(categoryOverrides,row.row) ? categoryOverrides[row.row] : row.transaction.category } } : row);
  const active = rows.filter((row) => !excluded.includes(row.row));
  const invalid = active.filter((row) => row.error);
  const duplicates = active.filter((row) => row.duplicate);
  const ready = active.filter((row) => row.transaction && !(row.duplicate && duplicatePolicy === "skip"));
  const canAnalyze = Boolean(profileId && ready.some((row) => row.transaction.type !== "transfer") && !invalid.length && !preview?.issues?.length && (!duplicates.length || duplicatePolicy !== "review") && !loading && !phase && !finished);
  async function analyze() {
    if (!canAnalyze && !saved) return;
    setError("");
    try {
      if (!saved) {
        setPhase("Saving your transactions…");
        const used = new Set();
        const transactions = ready.map(({ transaction, duplicate }) => {
          const value = { ...transaction };
          if (duplicate || used.has(value.id)) value.id = `kept-${crypto.randomUUID()}`;
          used.add(value.id); return value;
        });
        await addTransactions(profileId, transactions, { filename: file, format: "csv" });
        setSaved(true);
      }
      setPhase("Analyzing your spending… This can take a minute.");
      await onAnalyze();
      setFinished(true);
    } catch (cause) { setError(`${saved ? "Your transactions are already saved. " : ""}${cause.message || "Please try again."}`); }
    finally { setPhase(""); }
  }
  return <section className="surface-card space-y-4" aria-labelledby="upload-title">
    <h2 id="upload-title" className="text-lg font-semibold">1. Upload your transactions</h2>
    <p className="text-sm text-slate-600">Upload your bank statement or expense CSV. We support date, description/narration/merchant, and either an amount or separate debit and credit columns. No transaction IDs are needed. Files must use UTF-8 text, with up to 5,000 rows.</p>
    <p className="text-sm"><a className="text-brand-blue underline" href="/sample-expenses.csv" download>Download a clearly labelled sample CSV</a> · <a href="/profile" className="text-brand-blue underline">Choose your profile and currency</a></p>
    {!profileId && <p role="alert">Choose or create a financial profile first so your transactions are saved in the right place.</p>}
    <label className="block rounded-lg border-2 border-dashed border-slate-300 p-5 text-sm font-medium">Choose a CSV file<input aria-label="Upload expense CSV" className="mt-3 block w-full" type="file" accept=".csv,text/csv" onChange={selectFile} disabled={!profileId || Boolean(phase)} /></label>
    {loading && <p role="status">Reading and checking your file…</p>}
    {preview && <details open={!finished}><summary className="cursor-pointer font-medium">{finished ? `${ready.length} transactions imported — view file details` : "Review this file before saving"}</summary>
      <h2 className="text-lg font-semibold">2. Check your file</h2>
      <p className="text-sm">{file} · {preview.row_count} rows. Nothing is saved until you choose Analyze my spending.</p>
      <details open={Boolean(preview.issues.length)}><summary className="cursor-pointer font-medium">Check or change column mapping</summary><div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{Object.entries(FIELDS).map(([key,label]) => <label className="text-sm" key={key}>{label}<select aria-label={`${label} column`} disabled={saved || Boolean(phase)} className="mt-1 block w-full rounded-md border border-slate-300 p-2" value={(mapping || preview.mapping)[key] || ""} onChange={(event) => setMapping({ ...preview.mapping, ...mapping, [key]: event.target.value })}><option value="">Not in this file</option>{preview.headers.map((header) => <option key={header}>{header}</option>)}</select></label>)}</div></details>
      <p className="text-sm text-slate-600">Detected columns: Date = {preview.mapping.date || "choose above"}; description = {preview.mapping.description || "choose above"}; amount = {preview.mapping.amount || `${preview.mapping.debit || "debit?"} / ${preview.mapping.credit || "credit?"}`}.</p>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">Date format<select aria-label="CSV date format" disabled={saved || Boolean(phase)} className="mt-1 block w-full rounded-md border border-slate-300 p-2" value={dateFormat} onChange={(event) => setDateFormat(event.target.value)}><option value="auto">Detect unambiguous dates</option><option value="day_first">Day / month / year</option><option value="month_first">Month / day / year</option></select></label>
        <label className="text-sm">How are amounts shown?<select aria-label="CSV amount convention" disabled={saved || Boolean(phase)} className="mt-1 block w-full rounded-md border border-slate-300 p-2" value={convention} onChange={(event) => setConvention(event.target.value)}><option value="auto">Detect from type or debit/credit columns</option><option value="typed">Type column says income/expense/refund/transfer</option><option value="negative_expenses">Negative = spent; positive = received</option><option value="positive_expenses">Positive = spent; negative = received</option><option value="debit_credit">Separate debit and credit columns</option></select></label>
        <label className="text-sm">Number format<select aria-label="CSV number format" disabled={saved || Boolean(phase)} className="mt-1 block w-full rounded-md border border-slate-300 p-2" value={numberFormat} onChange={(event) => setNumberFormat(event.target.value)}><option value="decimal_point">1,234.56 or 1,23,456.78</option><option value="decimal_comma">1.234,56</option></select></label>
      </div>
      {preview.issues.length > 0 && <ul role="alert" className="list-inside list-disc text-sm text-amber-800">{preview.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>}
      {preview.warnings?.length > 0 && <details><summary className="cursor-pointer text-sm">{preview.warnings.length} category notice(s)</summary>{preview.warnings.map((message) => <p className="text-sm" key={message}>{message}</p>)}</details>}
      {duplicates.length > 0 && <label className="block text-sm text-amber-900">{duplicates.length} possible duplicate row(s). Identical purchases may be genuine; choose what to do.<select aria-label="Duplicate handling" disabled={saved || Boolean(phase)} className="mt-2 block rounded-md border border-amber-300 p-2" value={duplicatePolicy} onChange={(event) => setDuplicatePolicy(event.target.value)}><option value="review">Choose duplicate handling</option><option value="skip">Skip the flagged duplicate rows</option><option value="keep">Keep them as separate transactions</option></select></label>}
      <div className="table-scroll"><table className="data-table"><thead><tr><th>Row</th><th>Date</th><th>Description</th><th>Money</th><th>Type / check</th></tr></thead><tbody>{rows.filter((row) => row.error || row.duplicate).concat(rows.filter((row) => !row.error && !row.duplicate).slice(0,showAll ? undefined : 8)).map((row) => <tr key={row.row}><td>{row.row}</td><td>{row.transaction?.date || String(row.raw[preview.mapping.date] || "")}</td><td>{row.transaction?.description || String(row.raw[preview.mapping.description] || "")}</td><td>{row.transaction?.amount?.amount || "—"}</td><td>{excluded.includes(row.row) ? "Excluded by you" : row.error || `${row.transaction?.type || "Needs mapping"}${row.duplicate ? " · possible duplicate" : ""}`}{row.transaction && !saved && <select aria-label={`Type for row ${row.row}`} className="ml-2 rounded border border-slate-300 p-1" disabled={Boolean(phase)} value={row.transaction.type} onChange={(event) => setTypeOverrides((previous) => ({...previous,[row.row]:event.target.value}))}>{["income","expense","refund","transfer"].map((kind) => <option key={kind}>{kind}</option>)}</select>}{row.transaction?.type === "expense" && !saved && <select aria-label={`Category for row ${row.row}`} className="ml-2 rounded border border-slate-300 p-1" disabled={Boolean(phase)} value={row.transaction.category || ""} onChange={(event) => setCategoryOverrides((previous) => ({...previous,[row.row]:event.target.value || null}))}><option value="">Not categorized (shows as Other)</option>{CATEGORIES.map((category) => <option key={category}>{category}</option>)}</select>}{row.error && !saved && <button type="button" className="ml-2 underline" disabled={Boolean(phase)} onClick={() => setExcluded((previous) => previous.includes(row.row) ? previous.filter((id) => id !== row.row) : [...previous,row.row])}>{excluded.includes(row.row) ? `Restore row ${row.row}` : `Exclude row ${row.row}`}</button>}</td></tr>)}</tbody></table></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Show all transactions</label>
      <p className="text-xs text-slate-500">Preview shows up to eight clean rows and every flagged row. No invalid rows are silently discarded. Change the mapping or exclude each invalid row yourself.</p>
      <p className="text-sm">Refunds count as money received and are labelled separately. Transfers between your own accounts are saved but excluded from income and spending. Mark these in the file's Type column or use a row's type selector above. Descriptions alone are not used to guess them.</p>
      <p className="font-semibold" role="status">{ready.length} transactions ready to analyze.{excluded.length > 0 ? ` ${excluded.length} excluded by you.` : ""}{duplicatePolicy === "skip" && duplicates.length > 0 ? ` ${duplicates.length} duplicates will be skipped.` : ""}</p>
      {ready.length > 0 && ready.every((row) => row.transaction.type === "transfer") && <p className="text-sm text-amber-800">This file contains only transfers. Add income or expenses before analyzing spending.</p>}
      {invalid.length > 0 && <p className="text-sm text-amber-800">Correct or exclude {invalid.length} unreadable row(s) before continuing.</p>}
      <button type="button" onClick={() => void analyze()} disabled={!(canAnalyze || (saved && !finished && !phase))} className="rounded-md bg-brand-blue px-5 py-3 font-semibold text-white disabled:opacity-50">{phase || (finished ? "Transactions saved and analyzed" : saved ? "Retry spending analysis" : "Analyze my spending")}</button>
      {saved && !finished && !phase && <p className="text-sm">Your transactions are saved. Retrying analysis will not import them again.</p>}
      {phase && <p role="status" className="text-sm">{phase}</p>}
    </details>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
  </section>;
}
