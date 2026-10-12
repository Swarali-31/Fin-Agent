const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || "/api/v1").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor({ code, message, request_id, status, details }) {
    super(message || "The request could not be completed.");
    this.name = "ApiError";
    this.code = code || "api_error";
    this.message = message || "The request could not be completed.";
    this.request_id = request_id || null;
    this.status = status ?? null;
    this.details = details ?? null;
  }
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      credentials: "include",
      headers,
      body:
        options.body !== undefined && typeof options.body !== "string"
          ? JSON.stringify(options.body)
          : options.body,
    });
  } catch (error) {
    throw new ApiError({
      code: "network_error",
      message: error instanceof Error ? error.message : "Network request failed.",
      request_id: null,
    });
  }

  if (response.ok && options.responseType === "blob") return response.blob();

  let envelope;
  try {
    envelope = await response.json();
  } catch {
    throw new ApiError({
      code: "invalid_response",
      message: "The server returned a non-JSON response.",
      request_id: response.headers.get("X-Request-ID"),
      status: response.status,
    });
  }

  if (
    !envelope ||
    typeof envelope !== "object" ||
    !("status" in envelope) ||
    !("request_id" in envelope)
  ) {
    throw new ApiError({
      code: "invalid_response",
      message: "The server response did not match the API envelope.",
      request_id: response.headers.get("X-Request-ID"),
      status: response.status,
    });
  }

  if (!response.ok || envelope.status === "error") {
    const error = envelope.error || {};
    if (response.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event("finagent:session-expired"));
    }
    throw new ApiError({
      code: error.code || `http_${response.status}`,
      message: error.message || response.statusText || "The request failed.",
      request_id: envelope.request_id,
      status: response.status,
      details: error.details,
    });
  }

  if (envelope.status !== "ok") {
    throw new ApiError({
      code: "invalid_response",
      message: "The server returned an unknown envelope status.",
      request_id: envelope.request_id,
      status: response.status,
    });
  }

  return envelope.data;
}

export function queryString(params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, String(value));
    }
  }
  const value = query.toString();
  return value ? `?${value}` : "";
}
