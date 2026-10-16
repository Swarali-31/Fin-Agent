import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Check, Eye, EyeOff, Leaf, LockKeyhole } from "lucide-react";
import { useAuth } from "../auth/AuthContext.jsx";
import { request } from "../services/api.js";

export default function Auth({ mode }) {
  const signup = mode === "signup";
  const { user, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [form, setForm] = useState({ name: "", email: "", password: "", currency: "INR" });
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [available, setAvailable] = useState(null);
  useEffect(() => {
    let active = true;
    request("/auth/setup").then((value) => { if (active) setAvailable(value.accounts_available); }).catch(() => { if (active) setError("We couldn’t reach the server. Please try again shortly."); });
    return () => { active = false; };
  }, []);
  const change = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  if (user) return <Navigate to="/dashboard" replace />;
  async function submit(event) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      const body = signup ? form : { email: form.email, password: form.password };
      await signIn(mode, body);
      const from = location.state?.from;
      navigate(typeof from === "string" && from.startsWith("/") && !from.startsWith("//") ? from : signup ? "/expense-analysis" : "/dashboard", { replace: true });
    } catch (cause) {
      setError(cause.code === "persistence_not_configured" ? "This workspace is waiting for its cloud database connection. Please try again after setup is complete." : cause.message);
    } finally { setBusy(false); }
  }
  return <div className="auth-page">
    <aside className="auth-story"><Link className="public-brand" to="/"><Leaf size={25}/> finagent.</Link><div><span className="section-kicker">A FRESH PERSPECTIVE ON YOUR FINANCES</span><h1>Make space<br />for your<br /><em>future self.</em></h1><p>A personal workspace to understand today’s spending and plan tomorrow’s possibilities.</p><ul><li><Check size={17}/> Start with your actual expenses</li><li><Check size={17}/> Get a plan that builds on your data</li><li><Check size={17}/> Keep your history in one place</li></ul></div><span className="auth-story-footer">Thoughtful decisions start with a clearer picture.</span></aside>
    <main className="auth-form-side"><Link to="/" className="auth-back"><ArrowLeft size={16}/> Back to home</Link><div className="auth-form-wrap"><span className="auth-lock"><LockKeyhole size={22}/></span><span className="section-kicker">{signup ? "YOUR NEXT CHAPTER" : "YOUR PERSONAL WORKSPACE"}</span><h2>{signup ? "Let’s get you started." : "Good to see you again."}</h2><p>{signup ? "Create your account. We’ll make a personal profile ready for your first expense." : "Sign in to continue with your expenses, goals, and financial picture."}</p>
      {available === false && <div className="setup-notice" role="status"><strong>Cloud setup in progress</strong><p>Your workspace’s Supabase database hasn’t been connected yet. Account creation and sign-in will become available once setup is complete.</p></div>}
      {error && <div className="auth-error" role="alert">{error}</div>}
      <form onSubmit={submit} className="auth-form">
        {signup && <label>Your name<input autoComplete="name" value={form.name} onChange={change("name")} required maxLength={100} placeholder="What should we call you?" /></label>}
        <label>Email address<input autoComplete="email" type="email" value={form.email} onChange={change("email")} required placeholder="you@example.com" /></label>
        <label>Password<div className="password-input"><input autoComplete={signup ? "new-password" : "current-password"} type={visible ? "text" : "password"} minLength={8} maxLength={128} value={form.password} onChange={change("password")} required placeholder={signup ? "At least 8 characters" : "Enter your password"}/><button type="button" aria-label={visible ? "Hide password" : "Show password"} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18}/> : <Eye size={18}/>}</button></div></label>
        {signup && <label>Your currency<select value={form.currency} onChange={change("currency")}><option value="INR">INR — Indian rupee</option><option value="USD">USD — US dollar</option><option value="GBP">GBP — British pound</option><option value="EUR">EUR — Euro</option><option value="CAD">CAD — Canadian dollar</option><option value="AUD">AUD — Australian dollar</option></select><small>You can keep separate profiles for other currencies later.</small></label>}
        <button className="button-dark button-large" type="submit" disabled={busy || available === false}>{busy ? "One moment…" : signup ? "Create my workspace" : "Sign in"}<ArrowRight size={17}/></button>
      </form><p className="auth-switch">{signup ? "Already have an account?" : "New here?"} <Link to={signup ? "/login" : "/signup"}>{signup ? "Sign in" : "Create an account"}</Link></p><p className="auth-footnote"><LockKeyhole size={13}/> Your financial data is saved to your account, not this browser.</p>
    </div></main>
  </div>;
}
