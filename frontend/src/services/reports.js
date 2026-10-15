import { queryString, request } from "./api.js";

export const listReports = (params = {}) => request(`/reports${queryString(params)}`);
export const getReport = (reportId) =>
  request(`/reports/${encodeURIComponent(reportId)}`);
export const downloadReport = (reportId, format = "json") =>
  request(
    `/reports/${encodeURIComponent(reportId)}/download${queryString({ format })}`,
  );
