import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Auth from "./Auth.jsx";
import { useAuth } from "../auth/AuthContext.jsx";
import { request } from "../services/api.js";

vi.mock("../auth/AuthContext.jsx", () => ({ useAuth: vi.fn() }));
vi.mock("../services/api.js", () => ({ request: vi.fn() }));
const signIn = vi.fn();
beforeEach(() => {
  vi.resetAllMocks();
  useAuth.mockReturnValue({ user: null, signIn });
  request.mockResolvedValue({ accounts_available: true });
});
afterEach(cleanup);
function open(mode = "login") {
  render(<MemoryRouter><Auth mode={mode} /></MemoryRouter>);
}
it.each(["", "bad-email", "alice@example", "alice..smith@example.com", "alice@-example.com"])("rejects invalid email %s before contacting login", async (email) => {
  open();
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByText(/Enter a valid email address/)).toBeTruthy();
  expect(signIn).not.toHaveBeenCalled();
});
it("explains password length and requires a nonblank signup name", () => {
  open("signup");
  fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "   " } });
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "alice@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
  fireEvent.click(screen.getByRole("button", { name: "Create my workspace" }));
  expect(screen.getByText("Enter your name.")).toBeTruthy();
  expect(screen.getByText("Password must contain 8–128 characters.")).toBeTruthy();
  expect(signIn).not.toHaveBeenCalled();
});
it("normalizes email and displays incorrect-credentials feedback from the server", async () => {
  signIn.mockRejectedValue(new Error("Email or password is incorrect."));
  open();
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "Alice+test@Example.COM" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "test-password" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  await waitFor(() => expect(signIn).toHaveBeenCalledWith("login", { email: "alice+test@example.com", password: "test-password" }));
  expect(await screen.findByText("Email or password is incorrect.")).toBeTruthy();
});
