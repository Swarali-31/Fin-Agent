import { useState } from "react";
import {
  Activity,
  BarChart3,
  FileText,
  LayoutDashboard,
  Menu,
  Search,
  Sparkles,
  WalletCards,
  X,
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

const navigation = [
  { label: "Dashboard", to: "/dashboard", icon: LayoutDashboard },
  { label: "Master Agent", to: "/master-agent", icon: Sparkles },
  { label: "Expense Analysis", to: "/expense-analysis", icon: BarChart3 },
  { label: "Budget Planning", to: "/budget-planning", icon: WalletCards },
  { label: "Financial Research", to: "/financial-research", icon: Search },
  { label: "Reports", to: "/reports", icon: FileText },
];

function currentTitle(pathname) {
  return navigation.find((item) => item.to === pathname)?.label ?? "Dashboard";
}

export default function AppLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const title = currentTitle(location.pathname);

  return (
    <div className="app-shell">
      {drawerOpen && (
        <button
          className="drawer-scrim"
          type="button"
          aria-label="Close navigation menu"
          onClick={() => setDrawerOpen(false)}
        />
      )}
      <aside className={`sidebar ${drawerOpen ? "sidebar-open" : ""}`}>
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <Activity size={20} strokeWidth={2.2} />
          </div>
          <span>FinAgent</span>
          <button
            className="icon-button drawer-close"
            type="button"
            aria-label="Close navigation menu"
            onClick={() => setDrawerOpen(false)}
          >
            <X size={20} />
          </button>
        </div>
        <p className="nav-caption">WORKSPACE</p>
        <nav className="primary-nav" aria-label="Main navigation">
          {navigation.map(({ label, to, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `nav-link${isActive ? " nav-link-active" : ""}`
              }
              onClick={() => setDrawerOpen(false)}
            >
              <Icon size={18} strokeWidth={1.9} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="sidebar-footer-dot" aria-hidden="true" />
          Financial workspace
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <button
            className="icon-button mobile-menu-button"
            type="button"
            aria-label="Open navigation menu"
            aria-expanded={drawerOpen}
            onClick={() => setDrawerOpen(true)}
          >
            <Menu size={21} />
          </button>
          <div className="topbar-heading">
            <span className="topbar-eyebrow">FINANCIAL WORKSPACE</span>
            <h2>{title}</h2>
          </div>
          <div className="topbar-right">
            <span className="environment-label">Personal finance</span>
            <div className="avatar" aria-label="User profile">
              F
            </div>
          </div>
        </header>
        <main className="main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
