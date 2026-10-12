import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./api.js";

describe("API client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("unwraps successful response envelope data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            request_id: "req-success",
            status: "ok",
            data: { value: "TEST FIXTURE: response" },
            warnings: [],
            error: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(request("/health")).resolves.toEqual({
      value: "TEST FIXTURE: response",
    });
  });

  it("throws ApiError with backend code, message, request ID, and details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            request_id: "req-invalid",
            status: "error",
            data: null,
            warnings: [],
            error: {
              code: "validation_error",
              message: "Request validation failed.",
              details: { errors: [{ field: "amount" }] },
            },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(request("/profiles")).rejects.toMatchObject({
      name: "ApiError",
      code: "validation_error",
      message: "Request validation failed.",
      request_id: "req-invalid",
      status: 422,
      details: { errors: [{ field: "amount" }] },
    });
  });

  it("rejects malformed envelopes with ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ data: "not an envelope" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(request("/health")).rejects.toBeInstanceOf(ApiError);
    await expect(request("/health")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });
});
