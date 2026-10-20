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
  it("renders a calculated Bengali savings answer without an unsupported-answer error", async () => {
    runFinancialResearch.mockResolvedValue({result:{question:"Based on my spending, how much could I save each month?", calculated_answer:"ডেমো তথ্য। মাসে 25,000.00 INR সঞ্চয়ের জন্য অবশিষ্ট থাকতে পারে।",findings:[],sources:[],limitations:[]}});
    renderPage(<FinancialResearch />);
    fireEvent.change(screen.getByLabelText("Answer language"), {target:{value:"Bengali"}});
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {target:{value:"Based on my spending, how much could I save each month?"}});
    fireEvent.click(screen.getByRole("button", {name:"Send"}));
    expect(await screen.findByText(/মাসে 25,000.00 INR/)).toBeTruthy();
    expect(screen.getByText("Calculated from your saved transactions")).toBeTruthy();
    expect(screen.queryByText(/No supported answer/)).toBeNull();
    expect(screen.queryByText("Research incomplete")).toBeNull();
    expect(screen.queryByRole("button", {name:"Retry answer"})).toBeNull();
  });

  it("retries a failed AI answer without duplicating the question in conversation", async () => {
    runFinancialResearch.mockResolvedValueOnce({result:{question:"Explain emergency funds",findings:[],sources:[sourceFixture],limitations:[{code:"synthesis_unavailable",message:"The provider is temporarily unavailable."}]}})
      .mockResolvedValueOnce({result:{question:"Explain emergency funds",findings:[{statement:"TEST recovered explanation",source_ids:[]}],sources:[],limitations:[]}});
    renderPage(<FinancialResearch />);
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {target:{value:"Explain emergency funds"}});
    fireEvent.click(screen.getByRole("button", {name:"Send"}));
    const retry = await screen.findByRole("button", {name:"Retry answer"});
    expect(screen.getByText(/Your question is valid/)).toBeTruthy();
    fireEvent.click(retry);
    expect(await screen.findByText("TEST recovered explanation")).toBeTruthy();
    expect(runFinancialResearch.mock.calls[1][0].conversation).toEqual([]);
    expect(screen.getAllByText("Explain emergency funds")).toHaveLength(1);
  });

  it("requests detailed sections by default and preserves explanatory paragraphs", async () => {
    runFinancialResearch.mockResolvedValue({result:{findings:[{title:"Build your emergency fund",statement:"Start with essential expenses.\n\nSet a monthly saving amount.",source_ids:[sourceFixture.source_id]}],sources:[sourceFixture],limitations:[]}});
    renderPage(<FinancialResearch />);
    expect(screen.getByLabelText("Answer detail").value).toBe("detailed");
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {target:{value:"Explain emergency funds in detail"}});
    fireEvent.click(screen.getByRole("button", {name:"Send"}));
    expect(await screen.findByRole("heading", {name:"Build your emergency fund"})).toBeTruthy();
    expect(screen.getByText(/Start with essential expenses/).className).toContain("whitespace-pre-wrap");
    expect(runFinancialResearch).toHaveBeenCalledWith(expect.objectContaining({response_detail:"detailed"}), undefined);
    expect(screen.queryByText("Research incomplete")).toBeNull();
    expect(screen.queryByText("Context and assumptions")).toBeNull();
  });

  it("allows brief answers and distinguishes context from actual research failure", async () => {
    runFinancialResearch.mockResolvedValue({result:{findings:[{statement:"TEST supported answer",source_ids:[]}],limitations:[
      {code:"research_limitation",message:"Your current account balance was not provided."},
      {code:"search_incomplete",message:"One source search timed out."},
    ]}});
    renderPage(<FinancialResearch />);
    fireEvent.change(screen.getByLabelText("Answer detail"), {target:{value:"brief"}});
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {target:{value:"Explain saving"}});
    fireEvent.click(screen.getByRole("button", {name:"Send"}));
    expect(await screen.findByText("TEST supported answer")).toBeTruthy();
    expect(runFinancialResearch).toHaveBeenCalledWith(expect.objectContaining({response_detail:"brief"}), undefined);
    expect(screen.getByText("Context and assumptions")).toBeTruthy();
    expect(screen.getByText("Your current account balance was not provided.")).toBeTruthy();
    expect(screen.getByText("Research incomplete")).toBeTruthy();
    expect(screen.getByText("One source search timed out.")).toBeTruthy();
  });

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

  it("sends the selected profile and displays the financial context used", async () => {
    localStorage.setItem("finagent.profileId", "TEST-profile");
    runFinancialResearch.mockResolvedValue({result: {
      findings: [{statement:"Your recorded surplus supports saving regularly.", source_ids:[]}],
      financial_context: {is_sample:true, summary:{currency:"INR", period_start:"2026-09", period_end:"2026-10", monthly_income:{amount:"1000.00"}, monthly_expenses:{amount:"200.00"}, available_surplus:{amount:"800.00"}}, data_notes:["TEST data note"]},
    }});
    renderPage(<FinancialResearch />);
    fireEvent.change(screen.getByLabelText("What would you like to learn about money?"), {target:{value:"How much can I save?"}});
    fireEvent.click(screen.getByRole("button", {name:"Send"}));
    expect(await screen.findByText("Financial data used · DEMO")).toBeTruthy();
    expect(screen.getByText(/income INR 1000.00, spending 200.00, left over 800.00/)).toBeTruthy();
    expect(runFinancialResearch).toHaveBeenCalledWith(expect.objectContaining({question:"How much can I save?"}), "TEST-profile");
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
