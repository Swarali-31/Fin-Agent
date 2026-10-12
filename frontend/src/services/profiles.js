import { queryString, request } from "./api.js";

export const addTransactions = (profileId, transactions, importMetadata) =>
  request(`/profiles/${encodeURIComponent(profileId)}/transactions`, {
    method: "POST",
    body: { transactions, ...(importMetadata ? { import_metadata: importMetadata } : {}) },
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

export const createProfile = (profileId, currency = "INR") =>
  request("/profiles", { method: "POST", body: { profile_id: profileId, currency } });
export const listProfiles = () => request("/profiles");
export const getTransactions = (profileId) => request(`/profiles/${encodeURIComponent(profileId)}/transactions`);
export const previewTransactionsCsv = (profileId, body) => request(`/profiles/${encodeURIComponent(profileId)}/imports/preview`, { method: "POST", body });
export const correctTransaction = (profileId, transaction) => request(`/profiles/${encodeURIComponent(profileId)}/transactions/${encodeURIComponent(transaction.id)}/correct`, { method: "POST", body: transaction });

export const updateTransactionSelection = (profileId, transactionIds, deleted = true) => request(`/profiles/${encodeURIComponent(profileId)}/transactions/selection`, { method: "POST", body: { transaction_ids: transactionIds, deleted } });

export const deleteProfile = (profileId) => request(`/profiles/${encodeURIComponent(profileId)}`, { method: "DELETE" });
