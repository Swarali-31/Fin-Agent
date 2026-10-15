import { queryString, request } from "./api.js";

export const listBudgets = (params = {}) => request(`/budgets${queryString(params)}`);
export const getBudget = (budgetId) =>
  request(`/budgets/${encodeURIComponent(budgetId)}`);
export const getBudgetHistory = (budgetId) =>
  request(`/budgets/${encodeURIComponent(budgetId)}/history`);
