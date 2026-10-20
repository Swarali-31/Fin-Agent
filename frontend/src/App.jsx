import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Auth from "./pages/Auth.jsx";
import { RequireAuth } from "./auth/AuthContext.jsx";
import AppLayout from "./layouts/AppLayout.jsx";
import { Loading } from "./components/StateViews.jsx";

const Dashboard = lazy(() => import("./pages/Dashboard.jsx"));
const MasterAgent = lazy(() => import("./pages/MasterAgent.jsx"));
const ExpenseAnalysis = lazy(() => import("./pages/ExpenseAnalysis.jsx"));
const BudgetPlanning = lazy(() => import("./pages/BudgetPlanning.jsx"));
const FinancialResearch = lazy(() => import("./pages/FinancialResearch.jsx"));
const Profile = lazy(() => import("./pages/Profile.jsx"));
const Reports = lazy(() => import("./pages/Reports.jsx"));

const pages = [
  { path: "profile", title: "Profile", page: Profile },
  { path: "dashboard", title: "Dashboard", page: Dashboard },
  { path: "master-agent", title: "Master Agent", page: MasterAgent },
  { path: "expense-analysis", title: "Expense Analysis", page: ExpenseAnalysis },
  { path: "budget-planning", title: "Budget Planning", page: BudgetPlanning },
  { path: "financial-research", title: "Financial Research", page: FinancialResearch },
  { path: "reports", title: "Reports", page: Reports },
];

function PageStub({ title }) {
  return (
    <section className="page-panel" aria-labelledby="page-title">
      <h1 id="page-title" className="page-title">
        {title}
      </h1>
    </section>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Auth key="login" mode="login" />} />
      <Route path="/signup" element={<Auth key="signup" mode="signup" />} />
      <Route element={<RequireAuth />}>
      <Route element={<AppLayout />}>

        {pages.map((page) => {
          const Page = page.page;
          return (
            <Route
              key={page.path}
              path={page.path}
              element={
                Page ? (
                  <Suspense fallback={<Loading label={`Loading ${page.title}`} />}>
                    <Page />
                  </Suspense>
                ) : (
                  <PageStub title={page.title} />
                )
              }
            />
          );
        })}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
      </Route>
    </Routes>
  );
}
