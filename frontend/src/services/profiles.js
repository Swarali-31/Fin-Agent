import { queryString, request } from "./api.js";

export const addTransactions = (profileId, transactions) =>
  request(`/profiles/${encodeURIComponent(profileId)}/transactions`, {
    method: "POST",
    body: { transactions },
  });

export async function uploadTransactionsCsv(profileId, file) {
  return request(`/profiles/${encodeURIComponent(profileId)}/transactions`, {
    method: "POST",
    headers: { "Content-Type": "text/csv" },
    body: await file.text(),
  });
}

export const createSampleData = (profileId) =>
  request(`/profiles/${encodeURIComponent(profileId)}/sample-data`, {
    method: "POST",
  });
export const getProfileSummary = (profileId) =>
  request(`/profiles/${encodeURIComponent(profileId)}/summary`);
export const listExpenseAnalyses = (profileId, params = {}) =>
  request(
    `/profiles/${encodeURIComponent(profileId)}/expense-analyses${queryString(params)}`,
  );
export const getLatestExpenseAnalysis = (profileId) =>
  request(`/profiles/${encodeURIComponent(profileId)}/expense-analyses/latest`);
