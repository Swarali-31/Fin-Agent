import { createContext, useContext, useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { request } from "../services/api.js";
import { Loading, ErrorState } from "../components/StateViews.jsx";

const AuthContext = createContext(null);
const workspaceKeys = ["finagent.profileId", "finagent.currency", "finagent.sampleProfileId", "finagent.userId"];
function clearWorkspace() {
  try { workspaceKeys.forEach((key) => localStorage.removeItem(key)); } catch { /* No financial data is stored here. */ }
}
function rememberWorkspace(user) {
  try {
    if (localStorage.getItem("finagent.userId") !== user.id) clearWorkspace();
    localStorage.setItem("finagent.userId", user.id);
    if (!localStorage.getItem("finagent.profileId") && user.profile_id) localStorage.setItem("finagent.profileId", user.profile_id);
    localStorage.setItem("finagent.currency", user.currency || "INR");
  } catch { /* The account remains authenticated through its HttpOnly cookie. */ }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  async function refresh() {
    setLoading(true);
    setError(null);
    try { const current = await request("/auth/me"); rememberWorkspace(current); setUser(current); }
    catch (cause) { setUser(null); if (cause.status !== 401) setError(cause); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    void refresh();
    const expired = () => { clearWorkspace(); setUser(null); };
    window.addEventListener("finagent:session-expired", expired);
    return () => window.removeEventListener("finagent:session-expired", expired);
  }, []);
  async function signIn(mode, body) {
    const current = await request(`/auth/${mode}`, { method: "POST", body });
    clearWorkspace(); rememberWorkspace(current); setUser(current); setError(null);
    return current;
  }
  async function signOut() {
    await request("/auth/logout", { method: "POST" });
    clearWorkspace(); setUser(null);
  }
  return <AuthContext.Provider value={{ user, loading, error, refresh, signIn, signOut }}>{children}</AuthContext.Provider>;
}
export const useAuth = () => useContext(AuthContext);

export function RequireAuth() {
  const { user, loading, error, refresh } = useAuth();
  const location = useLocation();
  if (loading) return <div className="auth-loading"><Loading label="Opening your workspace" /></div>;
  if (error) return <div className="auth-loading"><ErrorState title="Workspace unavailable" message="We could not connect to your account. Please try again." onRetry={refresh} /></div>;
  return user ? <Outlet /> : <Navigate to="/login" state={{ from: location.pathname }} replace />;
}
