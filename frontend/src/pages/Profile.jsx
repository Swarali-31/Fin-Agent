import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { createProfile, deleteProfile, listProfiles } from "../services/profiles.js";

export default function Profile() {
  const { user } = useAuth();
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [profiles, setProfiles] = useState([]);
  const [selected, setSelected] = useState(() => localStorage.getItem("finagent.profileId") || "");
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pendingDelete, setPendingDelete] = useState(null);
  const [busy, setBusy] = useState(false);
  async function load() { const data = await listProfiles(); setProfiles(Array.isArray(data) ? data : data.items || []); }
  useEffect(() => { load().catch((cause) => setError(cause.message)); }, []);
  function choose(id, records = profiles) {
    const profile = records.find((item) => item.profile_id === id);
    if (!profile) return;
    localStorage.setItem("finagent.profileId", id);
    localStorage.setItem("finagent.currency", profile.currency);
    if (profile.is_sample) localStorage.setItem("finagent.sampleProfileId", id);
    else localStorage.removeItem("finagent.sampleProfileId");
    if (user?.id) localStorage.setItem(`finagent.workspace.${user.id}`, JSON.stringify({profileId:id, currency:profile.currency, isSample:!!profile.is_sample}));
    setSelected(id); setMessage(`Selected ${id}. All agent pages will use this profile.`);
  }
  async function removeProfile() {
    if (!pendingDelete) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await deleteProfile(pendingDelete.profile_id);
      const remaining = profiles.filter((item) => item.profile_id !== pendingDelete.profile_id);
      setProfiles(remaining);
      if (selected === pendingDelete.profile_id) {
        localStorage.removeItem("finagent.profileId");
        localStorage.removeItem("finagent.currency");
        localStorage.removeItem("finagent.sampleProfileId");
        if (user?.id) localStorage.removeItem(`finagent.workspace.${user.id}`);
        setSelected("");
        if (remaining.length) choose(remaining[0].profile_id, remaining);
      }
      setMessage(`Deleted ${pendingDelete.profile_id} and its saved financial records.`);
      setPendingDelete(null);
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try { await createProfile(name.trim(), currency); const data = await listProfiles(); const records = Array.isArray(data) ? data : data.items || []; if (mounted.current) { setProfiles(records); choose(name.trim(),records); setName(""); } }
    catch (cause) { setError(cause.message); } finally { setBusy(false); }
  }
  return <div className="space-y-6"><section><h1 className="page-title">Your profile</h1><p className="mt-2 text-sm text-slate-600">Choose whose finances to work on. Each financial profile keeps its transactions, budgets and reports together.</p></section>
    <section className="surface-card"><h2 className="font-semibold">Your account</h2><p className="mt-3">{user?.name}</p><p className="text-sm text-slate-600">{user?.email}</p><p className="mt-3 text-sm">Your financial records are saved in the cloud and belong to your signed-in account.</p></section>
    <section className="surface-card space-y-4"><h2 className="font-semibold">Financial profiles ({profiles.length})</h2>
      <p className="text-sm text-slate-600">Select a profile to use its data across all agent pages.</p>
      {!profiles.length && <p>No financial profiles yet. Create one below to start adding expenses.</p>}
      <ul className="space-y-3">{profiles.map((profile) => <li key={profile.profile_id} className="rounded-lg border border-slate-200 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3"><div className="min-w-0"><h3 className="break-all font-semibold">{profile.profile_id}{selected === profile.profile_id ? " · Selected" : ""}</h3>
        <p className="mt-1 text-sm text-slate-600">{profile.currency} · {profile.transaction_count ?? 0} active transactions · {profile.file_count ?? 0} files · {profile.deleted_count ?? 0} deleted transactions{profile.is_sample ? " · Sample data" : ""}</p></div>
        <div className="flex gap-3"><button disabled={busy || selected === profile.profile_id} onClick={() => choose(profile.profile_id)} className="rounded-md border border-slate-300 px-3 py-2 disabled:opacity-50" aria-label={`Select ${profile.profile_id}`}>{selected === profile.profile_id ? "Selected" : "Select profile"}</button>
        <button disabled={busy} onClick={() => setPendingDelete(profile)} className="rounded-md border border-red-200 px-3 py-2 text-red-700" aria-label={`Delete ${profile.profile_id}`}>Delete profile</button></div></div>
      </li>)}</ul>
      {pendingDelete && <div role="alertdialog" aria-label="Delete financial profile" className="rounded-lg border border-red-300 bg-red-50 p-4 space-y-3"><h3 className="font-semibold">Delete {pendingDelete.profile_id}?</h3><p>This permanently removes this profile, its transactions (including deleted transactions), file history, analyses, budgets, research and reports. This cannot be undone.</p><div className="flex gap-3"><button disabled={busy} onClick={removeProfile} className="rounded-md bg-red-700 px-4 py-2 text-white">{busy ? "Deleting…" : "Permanently delete profile"}</button><button disabled={busy} onClick={() => setPendingDelete(null)} className="rounded-md border border-slate-300 px-4 py-2">Cancel</button></div></div>}
      <Link to="/expense-analysis" className="inline-block text-brand-blue underline">Add expenses or import a file →</Link></section>
    <form onSubmit={submit} className="surface-card space-y-4"><h2 className="font-semibold">Create a financial profile</h2><label className="block text-sm">Profile name<input required maxLength={128} value={name} onChange={(event) => setName(event.target.value)} className="mt-2 block w-full rounded-md border border-slate-300 p-3" placeholder="For example: DEMO-family" /></label><label className="block text-sm">Currency<select value={currency} onChange={(event) => setCurrency(event.target.value)} className="ml-3 rounded-md border border-slate-300 p-2">{["INR","USD","EUR","GBP"].map((value) => <option key={value}>{value}</option>)}</select></label><p className="text-sm text-slate-600">Choose a separate profile for each sample file so demonstration data stays separate from your own expenses.</p><button disabled={busy || !name.trim()} className="rounded-md bg-brand-blue px-4 py-2 text-white disabled:opacity-50">{busy ? "Creating…" : "Create and select"}</button></form>
    {message && <p role="status">{message}</p>}{error && <p role="alert" className="text-red-700">{error}</p>}</div>;
}
