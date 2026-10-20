import { useEffect, useState } from "react";
import { runFinancialResearch } from "../services/agents.js";
import { listResearch } from "../services/research.js";
import SourceList from "../components/SourceList.jsx";

function answerText(result) {
  return result.calculated_answer || (result.findings || []).map((finding) => finding.statement).join("\n\n");
}

function ResearchNotes({ limitations = [] }) {
  const contextCodes = new Set(["research_limitation", "personalized_advice_reframed"]);
  const notes = limitations.filter((item) => contextCodes.has(item.code));
  const problems = limitations.filter((item) => !contextCodes.has(item.code));
  return <>
    {problems.length > 0 && <div role="status" className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><p className="font-semibold">Research incomplete</p><ul className="mt-2 list-disc space-y-2 pl-5">{problems.map((item,i) => <li key={i}>{item.message || item}</li>)}</ul><p className="mt-2">You can retry the question. The source links show what was retrieved.</p></div>}
    {notes.length > 0 && <details className="mt-4 text-sm text-slate-600"><summary className="cursor-pointer">Context and assumptions</summary><p className="mt-2">These notes explain what the answer depends on; they do not mean the request failed.</p><ul className="mt-2 list-disc space-y-2 pl-5">{notes.map((item,i) => <li key={i}>{item.message || item}</li>)}</ul></details>}
  </>;
}

export default function FinancialResearch() {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState([]);
  const [region, setRegion] = useState("IN");
  const [language, setLanguage] = useState("auto");
  const [detail, setDetail] = useState("detailed");
  const [historyError, setHistoryError] = useState("");
  const profileId = localStorage.getItem("finagent.profileId") || undefined;
  useEffect(() => {
    let active = true;
    listResearch(profileId ? {profile_id: profileId} : {}).then((data) => {
      if (active) { setHistory(data?.items || []); setHistoryError(""); }
    }).catch(() => { if (active) setHistoryError("Saved research is temporarily unavailable."); });
    return () => { active = false; };
  }, [profileId, messages]);

  async function send(event, retryText) {
    event?.preventDefault();
    const text = (retryText || question).trim();
    if (!text || loading) return;
    const previousMessages = retryText && messages.at(-1)?.role === "assistant" ? messages.slice(0,-2) : messages;
    const conversation = previousMessages.filter((message) => message.content).slice(-12).map(({role, content}) => ({role, content: content.slice(0,6000)}));
    setMessages([...previousMessages, {role:"user", content:text}]);
    setQuestion(""); setLoading(true); setError(null);
    try {
      const response = await runFinancialResearch({ question:text, jurisdiction:region || "IN", response_language:language, response_detail:detail, max_sources:5, conversation }, profileId);
      const result = response.result || response;
      const content = answerText(result);
      setMessages((previous) => [...previous, {role:"assistant", content, result}]);
    } catch (cause) {
      setMessages((previous) => previous.slice(0,-1));
      setQuestion(text);
      setError(cause);
    } finally { setLoading(false); }
  }
  function openHistory(item) {
    const result = item.result;
    if (!result) return;
    setMessages([{role:"user", content:result.question}, {role:"assistant", content:answerText(result), result}]);
    setError(null); setQuestion("");
  }
  return <div className="mx-auto max-w-4xl space-y-5">
    <div className="flex items-center justify-between gap-4"><div><h1 className="page-title">Financial Research</h1><p className="mt-2 text-sm text-slate-600">Ask about your money. Answers use your selected profile’s saved transactions and budget.</p></div><button disabled={loading} className="rounded-md border px-3 py-2 text-sm" onClick={() => {setMessages([]); setQuestion(""); setError(null);}}>New chat</button></div>
    <details className="surface-card"><summary className="cursor-pointer text-sm font-semibold">Saved questions and settings</summary><label className="mt-3 block text-sm">Country or region<input className="ml-3 rounded border p-2" value={region} maxLength={64} onChange={(event) => setRegion(event.target.value)} /></label>{historyError && <p role="alert">{historyError}</p>}{history.map((item) => <button key={item.id} disabled={loading} className="mt-3 block text-left text-sm text-brand-blue underline" onClick={() => openHistory(item)}>{item.result?.question || "Saved question"}</button>)}</details>
    {!messages.length && <div className="flex flex-wrap gap-2" aria-label="Example research questions">{["Based on my spending, how much could I save each month?", "Help me plan an emergency fund using my expenses.", "Which spending categories could I reduce to reach my goal?"].map((text) => <button key={text} className="rounded-full border px-3 py-2 text-sm" onClick={() => setQuestion(text)}>{text}</button>)}</div>}
    <label className="block text-sm">Answer language<select aria-label="Answer language" value={language} onChange={(event) => setLanguage(event.target.value)} className="ml-3 rounded border bg-white p-2">{[["auto","Match my question"],["English","English"],["Hindi","हिन्दी"],["Marathi","मराठी"],["Gujarati","ગુજરાતી"],["Bengali","বাংলা"],["Tamil","தமிழ்"],["Telugu","తెలుగు"],["Kannada","ಕನ್ನಡ"],["Malayalam","മലയാളം"],["Punjabi","ਪੰਜਾਬੀ"],["Spanish","Español"],["French","Français"],["Arabic","العربية"]].map(([value,label]) => <option value={value} key={value}>{label}</option>)}</select></label>
    <label className="block text-sm">Answer detail<select aria-label="Answer detail" value={detail} onChange={(event) => setDetail(event.target.value)} className="ml-3 rounded border bg-white p-2"><option value="detailed">Detailed explanation with examples</option><option value="brief">Brief answer</option></select></label>
    <div role="log" aria-label="Research conversation" aria-live="polite" className="space-y-5">
      {messages.map((message,index) => <article key={index} className={message.role === "user" ? "ml-8 rounded-xl bg-brand-blue p-4 text-white" : "surface-card mr-4"}>
        <p className="mb-2 text-xs font-semibold uppercase opacity-70">{message.role === "user" ? "You" : "FinAgent"}</p>
        {message.role === "user" ? <p dir="auto" className="whitespace-pre-wrap">{message.content}</p> : <>
          {message.result?.calculated_answer ? <div><p className="mb-2 text-xs font-medium text-slate-500">Calculated from your saved transactions</p><p dir="auto" className="whitespace-pre-wrap text-sm leading-7">{message.result.calculated_answer}</p></div> : message.result?.findings?.length ? <div className="space-y-5">{message.result.findings.map((finding,i) => <section key={i}>{finding.title && <h2 dir="auto" className="mb-2 text-base font-semibold text-slate-900">{finding.title}</h2>}<p dir="auto" className="whitespace-pre-wrap text-sm leading-7">{finding.statement}</p><div className="mt-2 flex flex-wrap gap-3">{(message.result.sources || []).filter((source) => finding.source_ids?.includes(source.source_id)).map((source) => <a className="text-xs text-brand-blue underline" key={source.source_id} href={source.url} target="_blank" rel="noopener noreferrer">{source.publisher || source.title}</a>)}</div></section>)}</div> : <p className="text-sm">{message.result?.limitations?.some((item) => item.code === "synthesis_unavailable") ? "The AI provider could not finish this answer. Your question is valid; retry below." : "No supported answer could be prepared from the available data and sources."}</p>}
          {message.result?.financial_context && <details className="mt-3 text-xs text-slate-600"><summary className="cursor-pointer">Financial data used{message.result.financial_context.is_sample ? " · DEMO" : ""}</summary>{message.result.financial_context.summary && <p className="mt-2">Saved transactions: {message.result.financial_context.summary.period_start} to {message.result.financial_context.summary.period_end}. Monthly averages: income {message.result.financial_context.summary.currency} {message.result.financial_context.summary.monthly_income.amount}, spending {message.result.financial_context.summary.monthly_expenses.amount}, left over {message.result.financial_context.summary.available_surplus.amount}.</p>}{message.result.financial_context.data_notes?.map((note,i) => <p key={i} className="mt-1">{note}</p>)}</details>}
          <ResearchNotes limitations={message.result?.limitations} />
          {!message.result?.calculated_answer && index === messages.length - 1 && (!message.result?.findings?.length || message.result?.limitations?.some((item) => item.code === "synthesis_unavailable")) && <button type="button" disabled={loading} className="mt-3 rounded border border-slate-300 px-3 py-2 text-sm disabled:opacity-50" onClick={() => void send(null, message.result?.question || messages[index-1]?.content)}>Retry answer</button>}
          {!!message.result?.errors?.length && <p role="alert" className="mt-3 text-sm text-red-700">{message.result.errors.map((item) => item.message).join(" ")}</p>}
          {message.result?.disclaimer && <p className="mt-3 text-xs text-slate-500">{message.result.disclaimer}</p>}
          {!!message.result?.sources?.length && <details className="mt-3 text-sm"><summary className="cursor-pointer">Sources ({message.result.sources.length})</summary><SourceList sources={message.result.sources} /></details>}
        </>}
      </article>)}
      {loading && <p role="status" className="text-sm text-slate-600">Searching sources and writing an answer…</p>}
    </div>
    {error && <div role="alert" className="rounded border border-red-200 p-3 text-sm text-red-800"><p>{["search_not_configured","misconfigured"].includes(error.code) ? "Search not configured" : "Couldn't send your question"}</p><p>{error.message}</p>{["search_not_configured","misconfigured"].includes(error.code) && <details><summary>Connection settings</summary>Configure TAVILY_API_KEY in the backend environment.</details>}</div>}
    <form onSubmit={send} className="surface-card flex items-end gap-3"><label htmlFor="research-question" className="flex-1 text-sm font-semibold">What would you like to learn about money?<textarea id="research-question" className="mt-2 block min-h-20 w-full rounded-md border p-3 font-normal" placeholder={messages.length ? "Ask a follow-up…" : "Ask a financial question…"} value={question} maxLength={6000} onChange={(event) => setQuestion(event.target.value)} required onKeyDown={(event) => {if(event.key === "Enter" && !event.shiftKey) {event.preventDefault(); if(question.trim() && !loading) void send(event);}}} /></label><button className="rounded-md bg-brand-blue px-4 py-3 text-white disabled:opacity-50" disabled={loading || !question.trim()}>{loading ? "Thinking…" : "Send"}</button></form>
    <p className="text-xs text-slate-500">Suggestions depend on the details available. Check sources and update your profile when your finances change.</p>
  </div>;
}
