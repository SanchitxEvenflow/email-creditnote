"use client";

import { useState, useRef, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type StepStatus = "IDLE" | "STEP_1_FETCHING" | "STEP_1_DONE" | "STEP_2_FETCHING" | "STEP_2_DONE" | "STEP_3_PUSHING" | "DONE" | "ERROR";

interface Receipt {
  grn_code: string;
  facility: string;
}

interface Step1Result {
  receipts: Receipt[];
  errors: string[];
}

interface LineItem {
  name: string;
  description: string;
  quantity: number;
  rate: number;
  sku: string;
}

interface BillGroup {
  bill_number: string;
  po_code: string;
  grn_codes: string[];
  facilities: string[];
  vendor_code: string;
  vendor_name: string;
  date: string | null;
  invoice_date: string | null;
  line_items: LineItem[];
  notes: string;
}

interface BillResult {
  bill_number: string;
  status: "ok" | "error" | "skipped";
  bill_id: string | null;
  error: string | null;
}

interface Step3Result {
  total: number;
  ok: number;
  failed: number;
  results: BillResult[];
}

const formatDateDDMMYYYY = (date: Date) => {
  const d = date.getDate().toString().padStart(2, '0');
  const m = (date.getMonth() + 1).toString().padStart(2, '0');
  const y = date.getFullYear();
  return `${d}/${m}/${y}`;
};

const parseDateToYYYYMMDD = (ddmmyyyy: string) => {
  const parts = ddmmyyyy.split('/');
  if (parts.length === 3) {
    return `${parts[2]}-${parts[1]}-${parts[0]}`;
  }
  return ddmmyyyy; // fallback
};

export default function GrnPushPage() {
  const [startDate, setStartDate] = useState(formatDateDDMMYYYY(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)));
  const [endDate, setEndDate] = useState(formatDateDDMMYYYY(new Date()));
  
  const [status, setStatus] = useState<StepStatus>("IDLE");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [facilityErrors, setFacilityErrors] = useState<string[]>([]);
  
  const [bills, setBills] = useState<BillGroup[]>([]);
  
  const [pushResults, setPushResults] = useState<Step3Result | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const runPipeline = async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    setErrorMsg(null);
    setReceipts([]);
    setFacilityErrors([]);
    setBills([]);
    setPushResults(null);

    try {
      // STEP 1
      setStatus("STEP_1_FETCHING");
      const res1 = await fetch(`${API_BASE}/grn-push/receipts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: parseDateToYYYYMMDD(startDate), end: parseDateToYYYYMMDD(endDate) }),
        signal
      });
      if (!res1.ok) throw new Error(`Step 1 failed: ${res1.statusText}`);
      const data1: Step1Result = await res1.json();
      setReceipts(data1.receipts);
      setFacilityErrors(data1.errors || []);
      setStatus("STEP_1_DONE");

      if (data1.receipts.length === 0) {
        setStatus("DONE");
        return; // Nothing to process
      }

      // Small delay for UI polish
      await new Promise(r => setTimeout(r, 600));

      // STEP 2
      setStatus("STEP_2_FETCHING");
      const res2 = await fetch(`${API_BASE}/grn-push/fetch-details`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ receipts: data1.receipts }),
        signal
      });
      if (!res2.ok) throw new Error(`Step 2 failed: ${res2.statusText}`);
      const data2: { bills: BillGroup[] } = await res2.json();
      setBills(data2.bills);
      setStatus("STEP_2_DONE");

      if (data2.bills.length === 0) {
        setStatus("DONE");
        return;
      }

      await new Promise(r => setTimeout(r, 1000));

      // STEP 3
      setStatus("STEP_3_PUSHING");
      const res3 = await fetch(`${API_BASE}/grn-push/create-bills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bills: data2.bills }),
        signal
      });
      if (!res3.ok) throw new Error(`Step 3 failed: ${res3.statusText}`);
      const data3: Step3Result = await res3.json();
      setPushResults(data3);
      setStatus("DONE");

    } catch (err: unknown) {
      if (err instanceof Error) {
        if (err.name === "AbortError") return;
        setErrorMsg(err.message || "An unexpected error occurred");
      } else {
        setErrorMsg("An unexpected error occurred");
      }
      setStatus("ERROR");
    }
  };

  const isRunning = ["STEP_1_FETCHING", "STEP_2_FETCHING", "STEP_3_PUSHING"].includes(status);

  return (
    <div className="w-full max-w-5xl mx-auto py-8 px-6">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-800 tracking-tight">GRN Push</h1>
        <p className="text-slate-500 mt-2">Push Unicommerce GRNs to Zoho Books seamlessly</p>
      </div>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden mb-8">
        <div className="p-6 border-b border-slate-100 bg-slate-50 flex items-end gap-4 flex-wrap">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">Start Date (DD/MM/YYYY)</label>
            <input 
              type="text" 
              placeholder="DD/MM/YYYY"
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              disabled={isRunning}
              className="px-4 py-2 border border-slate-300 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 text-slate-700 w-44 text-center placeholder-slate-400 font-mono tracking-wider"
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-2">End Date (DD/MM/YYYY)</label>
            <input 
              type="text" 
              placeholder="DD/MM/YYYY"
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              disabled={isRunning}
              className="px-4 py-2 border border-slate-300 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50 text-slate-700 w-44 text-center placeholder-slate-400 font-mono tracking-wider"
            />
          </div>
          <button
            onClick={runPipeline}
            disabled={isRunning}
            className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl transition-all disabled:opacity-50 flex items-center gap-2 ml-auto shadow-md hover:shadow-lg"
          >
            {isRunning ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                <span>Running Pipeline...</span>
              </>
            ) : (
              <span>🚀 Start Process</span>
            )}
          </button>
        </div>

        {errorMsg && (
          <div className="mx-6 mt-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-100 flex items-center gap-3">
            <span className="text-xl">⚠️</span>
            <span className="font-medium">{errorMsg}</span>
          </div>
        )}

        <div className="p-6">
          {/* Step 1 Results */}
          <div className={`transition-all duration-500 mb-6 ${status === "IDLE" || status === "STEP_1_FETCHING" ? "opacity-50" : "opacity-100"}`}>
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2 mb-3">
              1. Fetching GRNs
              {status === "STEP_1_FETCHING" && <span className="flex h-3 w-3 relative"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span><span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500"></span></span>}
              {["STEP_1_DONE", "STEP_2_FETCHING", "STEP_2_DONE", "STEP_3_PUSHING", "DONE"].includes(status) && <span className="text-green-500">✓</span>}
            </h2>
            {receipts.length > 0 && (
              <div className="bg-indigo-50 text-indigo-800 px-4 py-3 rounded-xl inline-flex items-center gap-2 font-medium border border-indigo-100">
                <span>Found {receipts.length} GRNs across {new Set(receipts.map(r => r.facility)).size} facilities</span>
              </div>
            )}
            {facilityErrors.length > 0 && (
              <div className="mt-3 flex flex-col gap-1">
                {facilityErrors.map((err, i) => (
                  <div key={i} className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg border border-red-100">{err}</div>
                ))}
              </div>
            )}
          </div>

          {/* Step 2 Results */}
          <div className={`transition-all duration-500 mb-6 ${["IDLE", "STEP_1_FETCHING", "STEP_1_DONE"].includes(status) ? "opacity-30" : "opacity-100"}`}>
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2 mb-3">
              2. Processing Bill Details
              {status === "STEP_2_FETCHING" && <span className="flex h-3 w-3 relative"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span><span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500"></span></span>}
              {["STEP_2_DONE", "STEP_3_PUSHING", "DONE"].includes(status) && <span className="text-green-500">✓</span>}
            </h2>
            
            {bills.length > 0 && (
              <div className="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
                <table className="w-full text-sm text-left">
                  <thead className="bg-slate-50 text-slate-600 font-semibold uppercase text-xs">
                    <tr>
                      <th className="px-4 py-3 border-b border-slate-200">Bill #</th>
                      <th className="px-4 py-3 border-b border-slate-200">Vendor</th>
                      <th className="px-4 py-3 border-b border-slate-200">GRNs</th>
                      <th className="px-4 py-3 border-b border-slate-200">Items</th>
                      <th className="px-4 py-3 text-right border-b border-slate-200">Total Value</th>
                      <th className="px-4 py-3 text-center border-b border-slate-200">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {bills.map((bill, i) => {
                      const total = bill.line_items.reduce((sum, item) => sum + (item.quantity * item.rate), 0);
                      const willSkip = bill.bill_number.toLowerCase().match(/kitting|dekitting|return/);
                      return (
                        <tr key={i} className={`hover:bg-slate-50 transition-colors ${willSkip ? 'bg-slate-50 text-slate-500' : 'text-slate-800'}`}>
                          <td className="px-4 py-3 font-medium">{bill.bill_number}</td>
                          <td className="px-4 py-3">{bill.vendor_name}</td>
                          <td className="px-4 py-3">
                            <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs font-mono">{bill.grn_codes.length}</span>
                          </td>
                          <td className="px-4 py-3">{bill.line_items.length}</td>
                          <td className="px-4 py-3 text-right font-medium">₹{total.toLocaleString('en-IN', { maximumFractionDigits: 2 })}</td>
                          <td className="px-4 py-3 text-center">
                            {willSkip ? (
                              <span className="px-2 py-1 bg-slate-200 text-slate-600 rounded text-xs font-semibold">Skip</span>
                            ) : (
                              <span className="px-2 py-1 bg-indigo-100 text-indigo-700 rounded text-xs font-semibold">Ready</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Step 3 Results */}
          <div className={`transition-all duration-500 ${["IDLE", "STEP_1_FETCHING", "STEP_1_DONE", "STEP_2_FETCHING", "STEP_2_DONE"].includes(status) ? "opacity-30" : "opacity-100"}`}>
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2 mb-3">
              3. Zoho Push Results
              {status === "STEP_3_PUSHING" && <span className="flex h-3 w-3 relative"><span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span><span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500"></span></span>}
              {status === "DONE" && <span className="text-green-500">✓</span>}
            </h2>

            {pushResults && (
              <div className="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                {pushResults.results.map((res, i) => (
                  <div key={i} className={`p-4 rounded-xl border ${
                    res.status === 'ok' ? 'bg-green-50 border-green-200' :
                    res.status === 'error' ? 'bg-red-50 border-red-200' : 'bg-slate-50 border-slate-200'
                  }`}>
                    <div className="font-semibold flex items-center justify-between mb-1 text-slate-800">
                      <span>{res.bill_number}</span>
                      {res.status === 'ok' && <span className="text-green-600 text-lg">✓</span>}
                      {res.status === 'error' && <span className="text-red-600 text-lg">✗</span>}
                      {res.status === 'skipped' && <span className="text-slate-400 font-bold">—</span>}
                    </div>
                    {res.status === 'ok' && <div className="text-sm text-green-700 font-medium">ID: {res.bill_id}</div>}
                    {res.status === 'error' && <div className="text-sm text-red-600 font-medium">{res.error}</div>}
                    {res.status === 'skipped' && <div className="text-sm text-slate-500 font-medium">Skipped rule match</div>}
                  </div>
                ))}
              </div>
            )}
            
            {status === "DONE" && pushResults && (
              <div className="mt-6 bg-slate-900 text-white p-5 rounded-xl flex items-center justify-between shadow-lg">
                <span className="font-semibold text-lg">Pipeline Completed</span>
                <div className="flex gap-4 bg-slate-800 px-4 py-2 rounded-lg">
                  <span className="text-emerald-400 font-medium">{pushResults.ok} Created</span>
                  <span className="text-rose-400 font-medium">{pushResults.failed} Failed</span>
                  <span className="text-slate-400 font-medium">{pushResults.total - pushResults.ok - pushResults.failed} Skipped</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
