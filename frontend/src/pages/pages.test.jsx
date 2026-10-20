import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ApiError } from "../services/api.js";
import Dashboard from "./Dashboard.jsx";
import MasterAgent from "./MasterAgent.jsx";

vi.mock("../services/agents.js", () => ({ listAgents: vi.fn() }));
vi.mock("../services/budgets.js", () => ({ listBudgets: vi.fn() }));
vi.mock("../services/profiles.js", () => ({
  createSampleData: vi.fn(),
  createProfile: vi.fn(),
  listProfiles: vi.fn().mockResolvedValue([]),
  getProfileSummary: vi.fn(),
}));
vi.mock("../services/workflows.js", () => ({
  createWorkflow: vi.fn(),
  getWorkflow: vi.fn(),
  getWorkflowTrace: vi.fn(),
  listWorkflows: vi.fn(),
}));

import { listAgents } from "../services/agents.js";
import { listBudgets } from "../services/budgets.js";
import { createSampleData, getProfileSummary } from "../services/profiles.js";
import {
  createWorkflow,
  getWorkflow,
  getWorkflowTrace,
  listWorkflows,
} from "../services/workflows.js";

function renderPage(element) {
  return render(<MemoryRouter>{element}</MemoryRouter>);
}

function makeApiError(code, message, status = 503) {
  return new ApiError({ code, message, status, request_id: "TEST FIXTURE: request" });
}

beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
  listAgents.mockResolvedValue({
    expense_analysis: {
      capabilities: ["expense_analysis"],
      integration_status: { status: "available", missing: [] },
    },
  });
  listWorkflows.mockResolvedValue({ items: [], total: 0 });
  listBudgets.mockResolvedValue({ items: [], total: 0 });
});

afterEach(cleanup);

describe("Dashboard", () => {
  it("renders a loading state while dashboard API requests are pending", () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    listAgents.mockReturnValue(new Promise(() => {}));
    listWorkflows.mockReturnValue(new Promise(() => {}));
    getProfileSummary.mockReturnValue(new Promise(() => {}));
    listBudgets.mockReturnValue(new Promise(() => {}));

    renderPage(<Dashboard />);

    expect(screen.getByText("Loading financial overview")).toBeTruthy();
  });

  it("shows persistence configuration errors from the API", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    listWorkflows.mockRejectedValue(makeApiError(
      "persistence_not_configured",
      "Persistence is unavailable.",
    ));
    getProfileSummary.mockRejectedValue(makeApiError(
      "persistence_not_configured",
      "Persistence is unavailable.",
    ));
    listBudgets.mockRejectedValue(makeApiError(
      "persistence_not_configured",
      "Persistence is unavailable.",
    ));

    renderPage(<Dashboard />);

    expect(await screen.findByText(/503 persistence_not_configured/)).toBeTruthy();
    expect(screen.getByText("Profile data unavailable")).toBeTruthy();
  });

  it("renders API figures, the sample badge, activity, and agent status", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    localStorage.setItem("finagent.sampleProfileId", "TEST FIXTURE: profile");
    listWorkflows.mockResolvedValue({
      items: [{
        run_id: "TEST FIXTURE: run",
        status: "success",
        input: { task: "TEST FIXTURE: review spending" },
        started_at: "2026-01-01T00:00:00Z",
      }],
    });
    getProfileSummary.mockResolvedValue({
      currency: "USD",
      months_covered: 1,
      monthly_income: { amount: "4200.00" },
      monthly_expenses: { amount: "3000.00" },
      available_surplus: { amount: "1200.00" },
      category_totals: { housing: { amount: "1800.00" }, groceries: { amount: "1200.00" } },
    });
    listBudgets.mockResolvedValue({
      items: [{
        result: {
          planned_monthly_savings: { amount: "500.00" },
          feasibility: { is_feasible: true },
        },
      }],
    });

    renderPage(<Dashboard />);

    expect(await screen.findByText("Sample data")).toBeTruthy();
    expect(screen.getByText("$4,200.00")).toBeTruthy();
    expect(screen.getByText("$3,000.00")).toBeTruthy();
    expect(screen.getByText("$1,200.00")).toBeTruthy();
    expect(screen.getByText("$500.00")).toBeTruthy();
    expect(await screen.findByText("TEST FIXTURE: review spending")).toBeTruthy();
    expect(screen.getByText("expense analysis")).toBeTruthy();
  });

  it("creates sample data only after the explicit action and labels the profile", async () => {
    createSampleData.mockResolvedValue({
      profile_id: "TEST FIXTURE: sample-profile",
      is_sample: true,
    });
    getProfileSummary.mockResolvedValue({
      currency: "USD",
      months_covered: 1,
      monthly_income: { amount: "100.00" },
      monthly_expenses: { amount: "50.00" },
      available_surplus: { amount: "50.00" },
      category_totals: { housing: { amount: "50.00" } },
    });

    renderPage(<Dashboard />);
    fireEvent.click(screen.getByRole("button", { name: "Load sample data" }));

    expect(await screen.findByText("Sample data")).toBeTruthy();
    expect(createSampleData).toHaveBeenCalledTimes(1);
    expect(createSampleData.mock.calls[0][0]).toMatch(/^sample-/);
  });
});

describe("Master Agent", () => {
  it("shows loading while polling a running workflow", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    createWorkflow.mockResolvedValue({ run_id: "TEST FIXTURE: run" });
    getWorkflow.mockReturnValue(new Promise(() => {}));
    getWorkflowTrace.mockResolvedValue([]);
    renderPage(<MasterAgent />);

    fireEvent.change(screen.getByLabelText(/What would you like FinAgent to do/), {
      target: { value: "Research emergency funds" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("Workflow is running; refreshing status and trace…")).toBeTruthy();
    expect(createWorkflow).toHaveBeenCalledWith({ task: "Research emergency funds", context: { profile_id: "TEST FIXTURE: profile" } });
  });

  it("shows create-workflow errors, including persistence configuration failures", async () => {
    createWorkflow.mockRejectedValue(makeApiError(
      "persistence_not_configured",
      "Persistence is unavailable.",
    ));
    renderPage(<MasterAgent />);

    fireEvent.change(screen.getByLabelText(/What would you like FinAgent to do/), {
      target: { value: "Research emergency funds" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText(/workspace is unavailable/i)).toBeTruthy();
  });

  it("renders the plan, fallback trace, answer, provenance, and sources", async () => {
    createWorkflow.mockResolvedValue({ run_id: "TEST FIXTURE: run" });
    getWorkflow.mockResolvedValue({
      run_id: "TEST FIXTURE: run",
      status: "success",
      result: {
        status: "success",
        plan: {
          source: "deterministic_fallback",
          steps: [{
            id: "research",
            agent: "financial_research",
            status: "success",
            attempts: 1,
            depends_on: [],
          }],
        },
        results: {},
        errors: [],
        final_answer: "TEST FIXTURE: education answer",
        claims: [{
          agent: "financial_research",
          step_id: "research",
          version: "TEST FIXTURE: version",
          field_path: "findings[0]",
          value: "TEST FIXTURE: finding",
        }],
        sources: [{
          source_id: "TEST FIXTURE: source",
          title: "TEST FIXTURE: source title",
          url: "https://example.invalid/test-source",
        }],
      },
    });
    getWorkflowTrace.mockResolvedValue([{
      event_type: "plan",
      created_at: "2026-01-01T00:00:00Z",
      payload: {
        seq: 1,
        type: "plan",
        summary: "TEST FIXTURE: fallback selected",
        timestamp: "2026-01-01T00:00:00Z",
        details: { planner: "deterministic_fallback" },
      },
    }]);
    renderPage(<MasterAgent />);

    fireEvent.change(screen.getByLabelText(/What would you like FinAgent to do/), {
      target: { value: "Research emergency funds" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByText("TEST FIXTURE: education answer")).toBeTruthy();
    expect(screen.getAllByText("deterministic_fallback").length).toBeGreaterThan(0);
    expect(screen.getByText("financial research")).toBeTruthy();
    expect(screen.getByText("findings[0]")).toBeTruthy();
    expect(screen.getByRole("link", { name: "https://example.invalid/test-source" })).toBeTruthy();
    await waitFor(() => expect(getWorkflow).toHaveBeenCalledTimes(1));
  });
});
