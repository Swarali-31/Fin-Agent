import { request } from "./api.js";

export const listAgents = () => request("/agents");
export const runExpenseAnalysis = (payload) =>
  request("/agents/expense-analysis/run", { method: "POST", body: payload });
export const createBudget = (payload, profileId) =>
  request(`/agents/budget-planning/run${profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""}`, {
    method: "POST",
    body: payload,
  });
export const reviseBudget = (payload, profileId) =>
  request(`/agents/budget-planning/revise${profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""}`, {
    method: "POST",
    body: payload,
  });
export const runFinancialResearch = (payload) =>
  request("/agents/financial-research/run", { method: "POST", body: payload });
export const runFinancialReport = (payload, profileId) =>
  request(`/agents/financial-report/run${profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""}`, {
    method: "POST",
    body: payload,
  });
