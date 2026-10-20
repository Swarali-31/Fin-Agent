import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight, BarChart3, Check, Leaf, Search, ShieldCheck, Sparkles, Wallet, FileText } from "lucide-react";
import { useAuth } from "../auth/AuthContext.jsx";

export default function Landing() {
  const { user } = useAuth();
  return <div className="landing-page">
    <header className="public-nav wrap">
      <Link to="/" className="public-brand"><span className="public-brand-mark"><Leaf size={22} /></span>finagent<span className="brand-period">.</span></Link>
      <nav aria-label="Public navigation"><a href="#how-it-works">How it works</a><a href="#your-agents">Your agents</a><Link to={user ? "/dashboard" : "/login"}>{user ? "My workspace" : "Log in"}</Link><Link className="button-dark" to={user ? "/dashboard" : "/signup"}>{user ? "Open dashboard" : "Get started"}<ArrowUpRight size={16} /></Link></nav>
    </header>
    <main>
      <section className="landing-hero wrap">
        <div className="hero-copy">
          <div className="eyebrow-pill"><span /> A little clarity. A lot more possibility.</div>
          <h1>Your money,<br /><em>with a plan.</em></h1>
          <p className="hero-description">Turn everyday expenses into a clearer financial future. Meet your personal team of AI agents for spending insights, thoughtful budgets, and source-backed research.</p>
          <div className="hero-actions"><Link to={user ? "/dashboard" : "/signup"} className="button-dark button-large">Build my financial picture <ArrowRight size={18} /></Link><a href="#how-it-works" className="understated-link">See how it works <ArrowUpRight size={15} /></a></div>
          <div className="hero-notes"><span><Check size={15} /> Your data, your workspace</span><span><Check size={15} /> No bank connection needed</span></div>
        </div>
        <div className="hero-visual" aria-label="Illustrative overview of how FinAgent works">
          <div className="orbit orbit-one" /><div className="orbit orbit-two" />
          <div className="visual-main-card">
            <div className="visual-card-top"><span><span className="tiny-leaf"><Leaf size={15}/></span> YOUR FINANCIAL PICTURE</span><span className="illustration-label">Illustration</span></div>
            <h2>Make room for<br />what matters.</h2><p>Small insights. More intentional choices.</p>
            <div className="illustration-bars" aria-hidden="true">{[34,49,42,67,57,79,91].map((height, i) => <div key={i} style={{ height: `${height}%` }} />)}</div>
            <div className="visual-card-bottom"><span>See patterns in your spending</span><ArrowUpRight size={20} /></div>
          </div>
          <div className="floating-note note-top"><span className="floating-icon"><Sparkles size={19} /></span><div><strong>A team on your side</strong><small>Four agents. One connected plan.</small></div></div>
          <div className="floating-note note-bottom"><span className="floating-icon"><ShieldCheck size={20} /></span><div><strong>A workspace of your own</strong><small>Sign in. Pick up where you left off.</small></div></div>
          <span className="visual-caption">A preview of the experience, not financial results.</span>
        </div>
      </section>
      <section id="how-it-works" className="how-section wrap">
        <div className="section-heading"><span className="section-kicker">LESS GUESSWORK, MORE DIRECTION</span><h2>Start with what you spend.<br />See where you can go.</h2></div>
        <div className="journey-grid">{[
          ["01", "Bring your everyday expenses", "Add income and expenses by hand or import a CSV. No complicated setup."],
          ["02", "Understand the bigger picture", "Find spending patterns and build a budget using your actual financial data."],
          ["03", "Take the next step", "Ask a financial question or generate a report with the decisions and sources in one place."],
        ].map(([n,title,body]) => <article key={n}><span className="step-number">{n}</span><h3>{title}</h3><p>{body}</p></article>)}</div>
      </section>
      <section id="your-agents" className="agents-section"><div className="wrap"><div className="section-heading"><span className="section-kicker">MEET YOUR FINANCIAL TEAM</span><h2>One workspace.<br />Four ways to move forward.</h2><p>The Master Agent connects the steps, so you don’t have to.</p></div><div className="agent-feature-grid">{[
        [BarChart3,"Expense Analysis","Know where it goes.","Understand categories, recurring costs, and unusual spending in your own transactions."],
        [Wallet,"Budget Planning","Give every goal a plan.","Build and revise a budget grounded in your latest spending analysis."],
        [Search,"Financial Research","Find the why behind it.","Explore financial questions with real search results and linked sources when search is configured."],
        [FileText,"Financial Report","See the whole story.","Bring validated analysis and budget results together in a report you can revisit."],
      ].map(([Icon,name,title,body]) => <article key={name}><Icon size={23}/><small>{name}</small><h3>{title}</h3><p>{body}</p></article>)}</div></div></section>
      <section className="landing-cta wrap"><div><span className="section-kicker">YOUR NEXT CHAPTER STARTS HERE</span><h2>Make your money<br /><em>make more sense.</em></h2></div><Link className="button-dark button-large" to={user ? "/dashboard" : "/signup"}>Start my workspace <ArrowRight size={18}/></Link></section>
    </main>
    <footer className="public-footer wrap"><Link className="public-brand" to="/"><Leaf size={21}/> finagent.</Link><span>Personal finance, with perspective.</span><small>Educational insights. Not a substitute for professional financial advice.</small></footer>
  </div>;
}
