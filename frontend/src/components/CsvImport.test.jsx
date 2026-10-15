import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import CsvImport from "./CsvImport.jsx";
import { addTransactions, previewTransactionsCsv } from "../services/profiles.js";
vi.mock("../services/profiles.js", () => ({ addTransactions: vi.fn(), previewTransactionsCsv: vi.fn() }));
const transaction={id:"TEST-FIXTURE-1",date:"2026-01-01",description:"DEMO food",type:"expense",amount:{amount:"100.00"}};
const preview={headers:["Date","Description","Amount"],mapping:{date:"Date",description:"Description",amount:"Amount"},convention:"positive_expenses",row_count:1,issues:[],warnings:[],rows:[{row:2,raw:{},transaction,error:null,duplicate:null}]};
beforeEach(() => { vi.resetAllMocks(); previewTransactionsCsv.mockResolvedValue(preview); addTransactions.mockResolvedValue({inserted:1}); });
afterEach(cleanup);
async function upload() { const file=new File(["Date,Description,Amount\n2026-01-01,DEMO food,100"],"DEMO.csv",{type:"text/csv"}); file.text=async()=>"Date,Description,Amount\n2026-01-01,DEMO food,100"; fireEvent.change(screen.getByLabelText("Upload expense CSV"),{target:{files:[file]}}); await screen.findByText(/1 transactions ready to analyze/); }
it("previews a CSV without saving, then saves and calls real analysis callback only on confirmation", async () => {
 const analyze=vi.fn().mockResolvedValue(); render(<CsvImport profileId="TEST" onAnalyze={analyze}/>); await upload();
 expect(addTransactions).not.toHaveBeenCalled(); expect(analyze).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole("button",{name:"Analyze my spending"}));
 await waitFor(()=>expect(analyze).toHaveBeenCalledTimes(1));
 expect(addTransactions).toHaveBeenCalledWith("TEST",[transaction],{filename:"DEMO.csv",format:"csv"});
});
it("does not reimport saved rows when analysis fails and is retried",async()=>{
 const analyze=vi.fn().mockRejectedValueOnce(new Error("AI unavailable")).mockResolvedValueOnce(); render(<CsvImport profileId="TEST" onAnalyze={analyze}/>); await upload();
 fireEvent.click(screen.getByRole("button",{name:"Analyze my spending"})); await screen.findByText(/AI unavailable/);
 fireEvent.click(screen.getByRole("button",{name:"Retry spending analysis"})); await waitFor(()=>expect(analyze).toHaveBeenCalledTimes(2)); expect(addTransactions).toHaveBeenCalledTimes(1);
});
it("requires explicit handling of duplicate rows",async()=>{
 previewTransactionsCsv.mockResolvedValue({...preview,rows:[{...preview.rows[0],duplicate:"already_saved"}]});render(<CsvImport profileId="TEST" onAnalyze={vi.fn()}/>);await upload();
 expect(screen.getByRole("button",{name:"Analyze my spending"}).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText("Duplicate handling"),{target:{value:"keep"}});
 expect(screen.getByRole("button",{name:"Analyze my spending"}).disabled).toBe(false);
});
it("makes every invalid row visible and requires explicit exclusion",async()=>{
 previewTransactionsCsv.mockResolvedValue({...preview,row_count:2,rows:[preview.rows[0],{row:3,raw:{Date:"bad"},error:"Unreadable date",transaction:null}]});render(<CsvImport profileId="TEST" onAnalyze={vi.fn()}/>);await upload();
 expect(screen.getByText("Unreadable date")).toBeTruthy();expect(screen.getByRole("button",{name:"Analyze my spending"}).disabled).toBe(true);
 fireEvent.click(screen.getByRole("button",{name:"Exclude row 3"}));expect(screen.getByRole("button",{name:"Analyze my spending"}).disabled).toBe(false);
});

it("accepts multiple files and reviews the next only after the previous file is saved", async () => {
  const first = new File(["first"], "first.csv", {type:"text/csv"}); first.text = async () => "first";
  const second = new File(["second"], "second.csv", {type:"text/csv"}); second.text = async () => "second";
  previewTransactionsCsv.mockImplementation(async (_profile, body) => ({...preview, rows:[{...preview.rows[0],transaction:{...transaction,id:body.csv_text}}]}));
  const analyze = vi.fn().mockResolvedValue();
  render(<CsvImport profileId="TEST" onAnalyze={analyze} />);
  expect(screen.getByLabelText("Upload expense CSV").multiple).toBe(true);
  fireEvent.change(screen.getByLabelText("Upload expense CSV"), {target:{files:[first, second]}});
  await screen.findByText("Review first.csv");
  expect(previewTransactionsCsv).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", {name:"Analyze my spending"}));
  await screen.findByText("Review second.csv");
  expect(addTransactions.mock.calls[0][2]).toEqual({filename:"first.csv",format:"csv"});
  expect(previewTransactionsCsv.mock.calls[1][1].csv_text).toBe("second");
  fireEvent.click(screen.getByRole("button", {name:"Analyze my spending"}));
  await screen.findByText(/2 file\(s\) saved/);
  expect(addTransactions.mock.calls[1][2]).toEqual({filename:"second.csv",format:"csv"});
  expect(analyze).toHaveBeenCalledTimes(2);
});

it("can continue a multi-file import after analysis fails without saving the first twice", async () => {
  const first = new File(["first"], "first.csv"); first.text = async () => "first";
  const second = new File(["second"], "second.csv"); second.text = async () => "second";
  const analyze = vi.fn().mockRejectedValueOnce(new Error("Provider unavailable")).mockResolvedValue();
  render(<CsvImport profileId="TEST" onAnalyze={analyze} />);
  fireEvent.change(screen.getByLabelText("Upload expense CSV"), {target:{files:[first,second]}});
  await screen.findByText("Review first.csv");
  fireEvent.click(screen.getByRole("button", {name:"Analyze my spending"}));
  await screen.findByText(/Provider unavailable/);
  fireEvent.click(screen.getByRole("button", {name:/Continue to the next file/}));
  await screen.findByText("Review second.csv");
  expect(addTransactions).toHaveBeenCalledTimes(1);
});
