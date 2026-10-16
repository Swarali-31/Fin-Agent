import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FinancialResearch from "./FinancialResearch.jsx";
import Reports from "./Reports.jsx";
import { ApiError } from "../services/api.js";

vi.mock("../services/agents.js", () => ({
  runFinancialResearch: vi.fn(),
  runFinancialReport: vi.fn(),
}));
vi.mock("../services/profiles.js", () => ({
  getLatestExpenseAnalysis: vi.fn(),
}));
vi.mock("../services/budgets.js", () => ({
  listBudgets: vi.fn(),
}));
vi.mock("../services/research.js", () => ({
  listResearch: vi.fn(),
}));
vi.mock("../services/reports.js", () => ({
  downloadReport: vi.fn(),
  listReports: vi.fn(),
}));

import { runFinancialReport, runFinancialResearch } from "../services/agents.js";
import { getLatestExpenseAnalysis } from "../services/profiles.js";
import { listBudgets } from "../services/budgets.js";
import { listResearch } from "../services/research.js";
import { listReports } from "../services/reports.js";

const sourceFixture = {
  source_id: "TEST FIXTURE: S1",
  title: "TEST FIXTURE: official source",
  url: "https://example.invalid/test-source",
  publisher: "TEST FIXTURE: synthetic publisher",
  tier: "official",
  retrieved_at: "2026-01-01T00:00:00Z",
};

const analysisFixture = {
  status: "success",
  analysis_version: "TEST FIXTURE: analysis-v1",
  summary: { currency: "USD", monthly_income: { amount: "1000.00" } },
};

const budgetFixture = {
  status: "success",
  budget_id: "TEST FIXTURE: budget-v1",
  revision: 1,
  source_analysis_version: "TEST FIXTURE: analysis-v1",
  currency: "USD",
  monthly_income: { amount: "1000.00" },
  planned_monthly_savings: { amount: "100.00" },
  category_limits: [],
  feasibility: { is_feasible: true, shortfall: { amount: "0.00" }, suggestions: [] },
};

function renderPage(page) {
  return render(page);
}

function setupReports() {
  localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
  getLatestExpenseAnalysis.mockResolvedValue(analysisFixture);
  listBudgets.mockResolvedValue({ items: [{ result: budgetFixture }] });
  listResearch.mockResolvedValue({ items: [] });
  listReports.mockResolvedValue({ items: [] });
}

beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
  listResearch.mockResolvedValue({ items: [] });
});

afterEach(cleanup);

describe("Financial Research page", () => {
  it("shows a search configuration state when the provider key is missing", async () => {
    runFinancialResearch.mockRejectedValue(new ApiError({
      code: "search_not_configured",
      message: "Tavily search is not configured.",
      status: 503,
    }));
    renderPage(<FinancialResearch />);
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {
      target: { value: "TEST FIXTURE: educational question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Search not configured")).toBeTruthy();
    expect(screen.getByText(/TAVILY_API_KEY/)).toBeTruthy();
    expect(screen.queryByText(sourceFixture.title)).toBeNull();
  });

  it("renders cited findings and only source dates actually returned", async () => {
    runFinancialResearch.mockResolvedValue({
      status: "success",
      result: {
        status: "success",
        question: "TEST FIXTURE: educational question",
        findings: [{
          statement: "TEST FIXTURE: cited statement",
          source_ids: [sourceFixture.source_id],
          confidence: "high",
        }],
        sources: [sourceFixture],
        disclaimer: "TEST FIXTURE: educational disclaimer",
        limitations: [],
      },
    });
    renderPage(<FinancialResearch />);
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {
      target: { value: "TEST FIXTURE: educational question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("TEST FIXTURE: cited statement")).toBeTruthy();
    const sourceLink = screen.getAllByRole("link", { name: sourceFixture.url })[0];
    expect(sourceLink.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getAllByText(/TEST FIXTURE: synthetic publisher/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Published:/)).toBeNull();
    expect(screen.getByText("TEST FIXTURE: educational disclaimer")).toBeTruthy();
  });
});

describe("Reports page", () => {
  it("shows loading while latest report inputs are loading", () => {
    setupReports();
    getLatestExpenseAnalysis.mockReturnValue(new Promise(() => {}));
    renderPage(<Reports />);
    expect(screen.getByText("Loading latest analysis, budget, and report history")).toBeTruthy();
  });

  it("renders a rejected response and does not show report sections", async () => {
    setupReports();
    runFinancialReport.mockRejectedValue(new ApiError({
      code: "report_inputs_rejected",
      message: "Budget is stale.",
      status: 409,
      details: {
        validation_issues: [{
          code: "STALE_BUDGET",
          severity: "error",
          message: "TEST FIXTURE: budget source differs.",
        }],
      },
    }));
    renderPage(<Reports />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));

    expect(await screen.findByText("Report rejected")).toBeTruthy();
    expect(screen.getByText("STALE_BUDGET")).toBeTruthy();
    expect(screen.getAllByText("Budget is stale.").length).toBeGreaterThan(0);
    expect(screen.queryByText("Spending insights")).toBeNull();
  });

  it("renders flagged validation issues, report sections, and source versions", async () => {
    setupReports();
    runFinancialReport.mockResolvedValue({
      status: "success",
      result: {
        status: "success",
        validation_status: "flagged",
        validation_summary: "TEST FIXTURE: research was partial.",
        validation_issues: [{
          code: "RESEARCH_PARTIAL",
          severity: "warning",
          message: "TEST FIXTURE: check research limitations.",
        }],
        report_version: "TEST FIXTURE: report-v1",
        source_versions: {
          analysis_version: analysisFixture.analysis_version,
          budget_id: budgetFixture.budget_id,
          budget_revision: 1,
        },
        sections: {
          summary: "TEST FIXTURE: report summary",
          spending_insights: ["TEST FIXTURE: spending insight"],
          budget_overview: [],
          savings_opportunities: ["TEST FIXTURE: savings opportunity"],
          research_findings: [{
            statement: "TEST FIXTURE: research statement",
            source_ids: [sourceFixture.source_id],
            confidence: "medium",
          }],
          sources: [sourceFixture],
          assumptions: ["TEST FIXTURE: assumption"],
          risk_considerations: ["TEST FIXTURE: risk"],
        },
      },
    });
    renderPage(<Reports />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));

    expect(await screen.findByText("flagged")).toBeTruthy();
    expect(screen.getByText("RESEARCH_PARTIAL")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: report summary")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: research statement")).toBeTruthy();
    expect(screen.getAllByText(analysisFixture.analysis_version).length).toBeGreaterThan(0);
    expect(screen.getAllByText(budgetFixture.budget_id).length).toBeGreaterThan(0);
  });

  it("renders valid report sections", async () => {
    setupReports();
    runFinancialReport.mockResolvedValue({
      status: "success",
      result: {
        status: "success",
        validation_status: "valid",
        validation_summary: "TEST FIXTURE: inputs valid.",
        validation_issues: [],
        source_versions: {
          analysis_version: analysisFixture.analysis_version,
          budget_id: budgetFixture.budget_id,
          budget_revision: 1,
        },
        sections: {
          summary: "TEST FIXTURE: valid summary",
          spending_insights: [],
          budget_overview: [],
          savings_opportunities: [],
          research_findings: [],
          sources: [],
          assumptions: [],
          risk_considerations: [],
        },
      },
    });
    renderPage(<Reports />);
    fireEvent.click(await screen.findByRole("button", { name: "Generate report" }));

    expect(await screen.findByText("TEST FIXTURE: valid summary")).toBeTruthy();
    expect(screen.getByText("valid")).toBeTruthy();
  });
});

it("sends follow-up context and clears it for a new chat", async () => {
  runFinancialResearch.mockResolvedValue({status:"success",result:{status:"success",findings:[{statement:"TEST FIXTURE answer",source_ids:[]}],sources:[]}});
  renderPage(<FinancialResearch />);
  const input = screen.getByLabelText("What would you like to learn about money?");
  fireEvent.change(input,{target:{value:"What is an emergency fund?"}});
  fireEvent.click(screen.getByRole("button",{name:"Send"}));
  await screen.findByText("TEST FIXTURE answer");
  fireEvent.change(input,{target:{value:"Where should I keep it?"}});
  fireEvent.click(screen.getByRole("button",{name:"Send"}));
  expect(runFinancialResearch.mock.calls[1][0].conversation).toEqual([{role:"user",content:"What is an emergency fund?"},{role:"assistant",content:"TEST FIXTURE answer"}]);
  await screen.findAllByText("TEST FIXTURE answer");
  // Wait for completion before starting the next conversation.
  await screen.findByRole("button",{name:"Send"});
  fireEvent.click(screen.getByRole("button",{name:"New chat"}));
  expect(screen.queryByText("Where should I keep it?")).toBeNull();
});
