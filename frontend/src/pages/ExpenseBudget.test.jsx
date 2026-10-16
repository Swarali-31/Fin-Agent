import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ApiError } from "../services/api.js";
import ExpenseAnalysis from "./ExpenseAnalysis.jsx";
import BudgetPlanning from "./BudgetPlanning.jsx";

vi.mock("../services/agents.js", () => ({
  runExpenseAnalysis: vi.fn(),
  createBudget: vi.fn(),
  reviseBudget: vi.fn(),
}));
vi.mock("../services/profiles.js", () => ({
  addTransactions: vi.fn(),
  uploadTransactionsCsv: vi.fn(),
  getProfileSummary: vi.fn(),
  getLatestExpenseAnalysis: vi.fn(),
  getTransactions: vi.fn().mockResolvedValue({ transactions: [] }),
  previewTransactionsCsv: vi.fn(),
  correctTransaction: vi.fn(),
  updateTransactionSelection: vi.fn(),
}));
vi.mock("../services/budgets.js", () => ({
  listBudgets: vi.fn(),
  getBudgetHistory: vi.fn(),
}));

import { createBudget, reviseBudget, runExpenseAnalysis } from "../services/agents.js";
import { getBudgetHistory, listBudgets } from "../services/budgets.js";
import { getLatestExpenseAnalysis, getTransactions, updateTransactionSelection } from "../services/profiles.js";

const analysisFixture = {
  agent: "expense_analysis",
  status: "success",
  analysis_version: "TEST FIXTURE: analysis-v1",
  summary: {
    currency: "USD",
    period_start: "2025-01",
    period_end: "2025-01",
    months_covered: 1,
    monthly_income: { amount: "3000.00" },
    monthly_expenses: { amount: "2000.00" },
    available_surplus: { amount: "1000.00" },
    category_totals: { housing: { amount: "1200.00" }, groceries: { amount: "800.00" } },
  },
  recurring_expenses: [{
    description: "TEST FIXTURE: rent",
    category: "housing",
    monthly_amount: { amount: "1200.00" },
    occurrences: 1,
  }],
  unusual_transactions: [
    { transaction_id: "TEST FIXTURE: duplicate", kind: "possible_duplicate", reason: "TEST FIXTURE: similar charge", amount: { amount: "20.00" } },
    { transaction_id: "TEST FIXTURE: outlier", kind: "outlier", reason: "TEST FIXTURE: unusually large", amount: { amount: "900.00" } },
  ],
  data_gaps: [{ transaction_id: "TEST FIXTURE: gap", issue: "TEST FIXTURE: unclear merchant", question: "TEST FIXTURE: identify merchant?" }],
};

const budgetFixture = {
  status: "success",
  budget_id: "TEST FIXTURE: budget-1",
  revision: 1,
  source_analysis_version: "TEST FIXTURE: analysis-v1",
  currency: "USD",
  monthly_income: { amount: "3000.00" },
  planned_monthly_savings: { amount: "500.00" },
  category_limits: [
    {
      category: "housing",
      monthly_limit: { amount: "1200.00" },
      current_monthly_spend: { amount: "1200.00" },
      is_essential: true,
      rationale: "TEST FIXTURE: essential cost",
    },
    {
      category: "groceries",
      monthly_limit: { amount: "700.00" },
      current_monthly_spend: { amount: "800.00" },
      is_essential: false,
      rationale: "TEST FIXTURE: discretionary cut",
    },
  ],
  feasibility: {
    is_feasible: false,
    requested_monthly_savings: { amount: "700.00" },
    max_achievable_monthly_savings: { amount: "500.00" },
    shortfall: { amount: "200.00" },
    suggestions: ["TEST FIXTURE: lower the target"],
  },
  assumptions: ["TEST FIXTURE: income remains stable"],
  trade_offs: ["TEST FIXTURE: less dining"],
};

beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
  getTransactions.mockResolvedValue({ transactions: [] });
});

afterEach(cleanup);

describe("Expense Analysis page", () => {
  it("reruns saved transactions and displays AI spending insights", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: saved-profile");
    getTransactions.mockResolvedValue({ transactions: [{ id: "stored-row", transaction: { id: "stored-row", date: "2026-10-01", description: "TEST FIXTURE", type: "expense", amount: { amount: "20.00" } } }] });
    getLatestExpenseAnalysis.mockResolvedValue({ result: analysisFixture });
    runExpenseAnalysis.mockResolvedValue({ status: "success", result: { ...analysisFixture, spending_patterns: [{ title: "TEST FIXTURE: housing pattern", detail: "Housing is a regular part of your spending." }] } });
    render(<ExpenseAnalysis />);
    const button = await screen.findByRole("button", { name: "Analyze saved transactions" });
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    expect(await screen.findByText("Housing is a regular part of your spending.")).toBeTruthy();
    expect(runExpenseAnalysis).toHaveBeenCalledWith({ profile_id: "TEST FIXTURE: saved-profile" });
  });

  it("shows loading while an existing analysis is fetched", () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    getLatestExpenseAnalysis.mockReturnValue(new Promise(() => {}));
    render(<ExpenseAnalysis />);
    expect(screen.getByText("Loading expense analysis")).toBeTruthy();
  });

  it("shows persistence errors from the backend", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    getLatestExpenseAnalysis.mockRejectedValue(new ApiError({
      code: "persistence_not_configured",
      message: "Persistence disabled",
      status: 503,
    }));
    render(<ExpenseAnalysis />);
    expect(await screen.findByText(/workspace is unavailable/i)).toBeTruthy();
  });

  it("runs analysis and renders returned totals, warnings, and version", async () => {
    runExpenseAnalysis.mockResolvedValue({ status: "partial", result: { ...analysisFixture, status: "partial" } });
    render(<ExpenseAnalysis />);
    fireEvent.change(screen.getByLabelText("Profile ID"), { target: { value: "TEST FIXTURE: profile" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "TEST FIXTURE: salary" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "3000.00" } });
    fireEvent.change(screen.getByLabelText("Transaction type"), { target: { value: "income" } });
    fireEvent.click(screen.getByRole("button", { name: "Add transaction" }));
    fireEvent.click(screen.getByRole("button", { name: "Save and analyze" }));

    expect(await screen.findByText("$3,000.00")).toBeTruthy();
    expect(screen.getByText("Analysis partial")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: analysis-v1")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: similar charge")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: unusually large")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: identify merchant?")).toBeTruthy();
    expect(runExpenseAnalysis).toHaveBeenCalledWith(expect.objectContaining({
      profile: expect.objectContaining({ profile_id: "TEST FIXTURE: profile" }),
    }));
  });

  it("displays per-row server validation errors", async () => {
    runExpenseAnalysis.mockRejectedValue(new ApiError({
      code: "transaction_rows_invalid",
      message: "Rows rejected",
      status: 422,
      details: {
        row_errors: [{ row: 2, code: "invalid_transaction", errors: [{ field: "amount", message: "must be positive" }] }],
      },
    }));
    render(<ExpenseAnalysis />);
    fireEvent.change(screen.getByLabelText("Profile ID"), { target: { value: "TEST FIXTURE: profile" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "TEST FIXTURE: salary" } });
    fireEvent.change(screen.getByLabelText("Amount"), { target: { value: "3000.00" } });
    fireEvent.change(screen.getByLabelText("Transaction type"), { target: { value: "income" } });
    fireEvent.click(screen.getByRole("button", { name: "Add transaction" }));
    fireEvent.click(screen.getByRole("button", { name: "Save and analyze" }));

    expect(await screen.findByText("Server rejected transaction rows")).toBeTruthy();
    expect(screen.getByText("amount: must be positive")).toBeTruthy();
  });
});

describe("Budget Planning page", () => {
  it("shows loading while latest analysis and budget are fetched", () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    getLatestExpenseAnalysis.mockReturnValue(new Promise(() => {}));
    listBudgets.mockReturnValue(new Promise(() => {}));
    render(<BudgetPlanning />);
    expect(screen.getByText("Loading latest analysis and budget")).toBeTruthy();
  });

  it("shows persistence configuration failures", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    getLatestExpenseAnalysis.mockRejectedValue(new ApiError({
      code: "persistence_not_configured",
      message: "Persistence disabled",
      status: 503,
    }));
    listBudgets.mockResolvedValue({ items: [] });
    render(<BudgetPlanning />);
    expect(await screen.findByText(/workspace is unavailable/i)).toBeTruthy();
  });

  it("shows budget feasibility, allocation, stale status and supports revision", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    getLatestExpenseAnalysis.mockResolvedValue({
      analysis_version: "TEST FIXTURE: analysis-v2",
      status: "success",
      result: analysisFixture,
    });
    listBudgets.mockResolvedValue({ items: [{ result: budgetFixture }] });
    getBudgetHistory.mockResolvedValue([{ ...budgetFixture, revision: 1 }]);
    reviseBudget.mockResolvedValue({
      status: "success",
      result: { ...budgetFixture, budget_id: "TEST FIXTURE: budget-2", revision: 2, source_analysis_version: "TEST FIXTURE: analysis-v2" },
    });
    render(<BudgetPlanning />);

    expect(await screen.findByText("Budget is stale")).toBeTruthy();
    expect(screen.getByText("TEST FIXTURE: lower the target")).toBeTruthy();
    expect(screen.getByText("Essential allocation")).toBeTruthy();
    expect(screen.getByText("Discretionary allocation")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Revise to latest analysis" }));
    await waitFor(() => expect(reviseBudget).toHaveBeenCalledWith({
      previous: budgetFixture,
      new_analysis: { ...analysisFixture, analysis_version: "TEST FIXTURE: analysis-v2" },
    }, "TEST FIXTURE: profile"));
  });

  it("creates a budget with the analysis and savings goal supplied by the user", async () => {
    localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
    getLatestExpenseAnalysis.mockResolvedValue(analysisFixture);
    listBudgets.mockResolvedValue({ items: [] });
    createBudget.mockResolvedValue({ status: "success", result: budgetFixture });
    render(<BudgetPlanning />);

    expect(await screen.findByText("$3,000.00")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Monthly savings goal"), { target: { value: "500.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Create my budget" }));
    await waitFor(() => expect(createBudget).toHaveBeenCalledWith(expect.objectContaining({
      expense_analysis: analysisFixture,
      savings_goal: { monthly_target: { amount: "500.00" } },
    }), "TEST FIXTURE: profile"));
  });
});


it("deletes only selected saved rows and allows undo", async () => {
  localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
  getLatestExpenseAnalysis.mockResolvedValue(analysisFixture);
  const row = {id:"rent", date:"2026-08-02", description:"TEST FIXTURE rent", amount:{amount:"20000"}, type:"expense"};
  getTransactions.mockResolvedValueOnce({transactions:[row]}).mockResolvedValueOnce({transactions:[]}).mockResolvedValueOnce({transactions:[row]});
  updateTransactionSelection.mockResolvedValue({updated:1});
  render(<ExpenseAnalysis />);
  const select = await screen.findByLabelText("Select all saved transactions");
  await waitFor(() => expect(screen.getByLabelText("Select TEST FIXTURE rent 2026-08-02 rent")).toBeTruthy());
  fireEvent.click(screen.getByText(/Your saved transactions \(1\)/));
  fireEvent.click(select);
  fireEvent.click(screen.getByRole("button",{name:"Delete selected (1)"}));
  const undo = await screen.findByRole("button",{name:"Undo deletion (1)"});
  expect(updateTransactionSelection).toHaveBeenCalledWith("TEST FIXTURE: profile",["rent"],true);
  fireEvent.click(undo);
  await waitFor(() => expect(updateTransactionSelection).toHaveBeenCalledWith("TEST FIXTURE: profile",["rent"],false));
});

it("includes separate budget runs in history and keeps older versions read-only", async () => {
  localStorage.setItem("finagent.profileId", "TEST FIXTURE: profile");
  getLatestExpenseAnalysis.mockResolvedValue(analysisFixture);
  const latest = {...budgetFixture, budget_id:"latest", revision:3};
  const older = {...budgetFixture, budget_id:"older", revision:1};
  listBudgets.mockResolvedValue({items:[{result:latest},{result:older}]});
  getBudgetHistory.mockResolvedValue([latest]);
  render(<BudgetPlanning />);
  fireEvent.click(await screen.findByRole("button",{name:"View revision 1"}));
  expect(screen.getByRole("button",{name:"Recalculate budget"}).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button",{name:"Return to latest budget"}));
  expect(screen.getByRole("button",{name:"Recalculate budget"}).disabled).toBe(false);
});
