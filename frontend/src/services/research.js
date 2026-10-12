import { queryString, request } from "./api.js";

export const listResearch = (params = {}) => request(`/research${queryString(params)}`);
export const getResearch = (researchId) =>
  request(`/research/${encodeURIComponent(researchId)}`);
