import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { createProfile, listProfiles } from "../services/profiles.js";

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
    setSelected(id); setMessage(`Selected ${id}. All agent pages will use this profile.`);
  }
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try { await createProfile(name.trim(), currency); const data = await listProfiles(); const records = Array.isArray(data) ? data : data.items || []; if (mounted.current) { setProfiles(records); choose(name.trim(),records); setName(""); } }
    catch (cause) { setError(cause.message); } finally { setBusy(false); }
  }
  return <div className="space-y-6"><section><h1 className="page-title">Your profile</h1><p className="mt-2 text-sm text-slate-600">Choose whose finances to work on. Each financial profile keeps its transactions, budgets and reports together.</p></section>
    <section className="surface-card"><h2 className="font-semibold">Your account</h2><p className="mt-3">{user?.name}</p><p className="text-sm text-slate-600">{user?.email}</p><p className="mt-3 text-sm">Your financial records are saved in the cloud and belong to your signed-in account.</p></section>
    <section className="surface-card space-y-3"><h2 className="font-semibold">Financial profiles</h2><label className="block text-sm">Selected profile<select aria-label="Selected profile" value={selected} onChange={(event) => choose(event.target.value)} className="mt-2 block w-full rounded-md border border-slate-300 p-3"><option value="" disabled>Choose a profile</option>{profiles.map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{profile.profile_id} · {profile.currency}{profile.is_sample ? " · Sample data" : ""}</option>)}</select></label><Link to="/expense-analysis" className="inline-block text-brand-blue underline">Add expenses or import a file →</Link></section>
    <form onSubmit={submit} className="surface-card space-y-4"><h2 className="font-semibold">Create a financial profile</h2><label className="block text-sm">Profile name<input required maxLength={128} value={name} onChange={(event) => setName(event.target.value)} className="mt-2 block w-full rounded-md border border-slate-300 p-3" placeholder="For example: DEMO-family" /></label><label className="block text-sm">Currency<select value={currency} onChange={(event) => setCurrency(event.target.value)} className="ml-3 rounded-md border border-slate-300 p-2">{["INR","USD","EUR","GBP"].map((value) => <option key={value}>{value}</option>)}</select></label><p className="text-sm text-slate-600">Choose a separate profile for each sample file so demonstration data stays separate from your own expenses.</p><button disabled={busy || !name.trim()} className="rounded-md bg-brand-blue px-4 py-2 text-white disabled:opacity-50">{busy ? "Creating…" : "Create and select"}</button></form>
    {message && <p role="status">{message}</p>}{error && <p role="alert" className="text-red-700">{error}</p>}</div>;
}
