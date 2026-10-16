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
 expect(addTransactions).toHaveBeenCalledWith("TEST",[transaction]);
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
