import { queryString, request } from "./api.js";

export const createWorkflow = (payload) =>
  request("/workflows", { method: "POST", body: payload });
export const getWorkflow = (runId) =>
  request(`/workflows/${encodeURIComponent(runId)}`);
export const getWorkflowTrace = (runId) =>
  request(`/workflows/${encodeURIComponent(runId)}/trace`);
export const listWorkflows = (params = {}) =>
  request(`/workflows${queryString(params)}`);
