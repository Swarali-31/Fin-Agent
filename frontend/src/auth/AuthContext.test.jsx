import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "./AuthContext.jsx";
import { request } from "../services/api.js";
vi.mock("../services/api.js", () => ({ request:vi.fn() }));
const alice = {id:"alice",name:"Alice",profile_id:"personal-alice",currency:"INR"};
const bob = {id:"bob",name:"Bob",profile_id:"personal-bob",currency:"USD"};
function Session() {
  const {user, signIn, signOut} = useAuth();
  return <><p>{user?.name || "Signed out"}</p><button onClick={() => signOut()}>Sign out</button><button onClick={() => signIn("login", {email:"alice"})}>Login Alice</button><button onClick={() => signIn("login", {email:"bob"})}>Login Bob</button></>;
}
beforeEach(() => {
  localStorage.clear(); vi.resetAllMocks();
  request.mockImplementation(async (path, options) => path === "/auth/logout" ? {} : options?.body?.email === "bob" ? bob : alice);
});
afterEach(cleanup);
it("restores the selected profile and currency after signing out and back in", async () => {
  localStorage.setItem("finagent.userId","alice"); localStorage.setItem("finagent.profileId","family"); localStorage.setItem("finagent.currency","EUR");
  render(<AuthProvider><Session /></AuthProvider>);
  await screen.findByText("Alice");
  fireEvent.click(screen.getByRole("button", {name:"Sign out"}));
  await screen.findByText("Signed out");
  expect(localStorage.getItem("finagent.profileId")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name:"Login Alice"}));
  await screen.findByText("Alice");
  expect(localStorage.getItem("finagent.profileId")).toBe("family");
  expect(localStorage.getItem("finagent.currency")).toBe("EUR");
});
it("keeps remembered profiles separate between accounts", async () => {
  localStorage.setItem("finagent.workspace.alice", JSON.stringify({profileId:"family",currency:"EUR"}));
  render(<AuthProvider><Session /></AuthProvider>);
  await screen.findByText("Alice");
  expect(localStorage.getItem("finagent.profileId")).toBe("family");
  fireEvent.click(screen.getByRole("button", {name:"Login Bob"}));
  await screen.findByText("Bob");
  await waitFor(() => expect(localStorage.getItem("finagent.profileId")).toBe("personal-bob"));
  expect(localStorage.getItem("finagent.currency")).toBe("USD");
});
