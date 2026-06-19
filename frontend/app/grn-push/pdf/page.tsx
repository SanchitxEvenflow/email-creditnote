"use client";

import { useState, useRef, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

type PageStatus = "IDLE" | "FETCHING_GRNS" | "GRNS_READY" | "ATTACHING" | "DONE" | "ERROR";
type AttachStatus = "ok" | "no_bill" | "no_pdf" | "error";

interface Receipt {
  grn_code: string;
  facility: string;
}

interface AttachResult {
  grn_code: string;
  status: AttachStatus;
  filenames?: string[];
  bill_number?: string;
  error?: string;
}

const formatDateDDMMYYYY = (date: Date) => {
  const d = date.getDate().toString().padStart(2, "0");
  const m = (date.getMonth() + 1).toString().padStart(2, "0");
  const y = date.getFullYear();
  return `${d}/${m}/${y}`;
};

const parseDateToYYYYMMDD = (ddmmyyyy: string) => {
  const parts = ddmmyyyy.split("/");
  if (parts.length === 3) return `${parts[2]}-${parts[1]}-${parts[0]}`;
  return ddmmyyyy;
};

const Spinner = () => (
  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
  </svg>
);

export default function PdfPage() {
  const [startDate, setStartDate] = useState(formatDateDDMMYYYY(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)));
  const [endDate, setEndDate] = useState(formatDateDDMMYYYY(new Date()));
  const [pageStatus, setPageStatus] = useState<PageStatus>("IDLE");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [facilityErrors, setFacilityErrors] = useState<string[]>([]);
  const [results, setResults] = useState<AttachResult[]>([]);
  const [attachingGrn, setAttachingGrn] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => { abortRef.current?.abort(); }, []);

  const fetchGRNs = async () => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    setErrorMsg(null);
    setReceipts([]);
    setFacilityErrors([]);
    setResults([]);
    setPageStatus("FETCHING_GRNS");

    try {
      const res = await fetch(`${API_BASE}/grn-push/receipts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: parseDateToYYYYMMDD(startDate), end: parseDateToYYYYMMDD(endDate) }),
        signal,
      });
      if (!res.ok) throw new Error(`Failed to fetch GRNs: ${res.statusText}`);
      const data: { receipts: Receipt[]; errors: string[] } = await res.json();
      setReceipts(data.receipts);
      setFacilityErrors(data.errors ?? []);
      setPageStatus("GRNS_READY");
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setErrorMsg(err instanceof Error ? err.message : "Unexpected error");
      setPageStatus("ERROR");
    }
  };

  const attachPDFs = async () => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    setResults([]);
    setErrorMsg(null);
    setPageStatus("ATTACHING");

    try {
      const res = await fetch(`${API_BASE}/grn-push/attach-pdfs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ receipts }),
        signal,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(body.detail ?? res.statusText);
      }

      const data: { results: Array<{ grn_code: string; bill_number: string; status: string; filenames: string[]; error?: string }> } = await res.json();

      const mapped: AttachResult[] = data.results.map(r => {
        const status: AttachStatus =
          r.status === "ok" || r.status === "already_attached" ? "ok"
          : r.status === "no_bill" ? "no_bill"
          : r.status === "no_pdf" ? "no_pdf"
          : "error";
        return {
          grn_code: r.grn_code,
          bill_number: r.bill_number,
          status,
          filenames: r.filenames,
          error: r.error,
        };
      });

      setResults(mapped);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        setPageStatus("IDLE");
        return;
      }
      setErrorMsg(err instanceof Error ? err.message : "Unexpected error");
      setPageStatus("ERROR");
      return;
    }

    setAttachingGrn(null);
    setPageStatus("DONE");
  };

  const isFetching = pageStatus === "FETCHING_GRNS";
  const isAttaching = pageStatus === "ATTACHING";
  const isRunning = isFetching || isAttaching;

  const countByStatus = (s: AttachStatus) => results.filter(r => r.status === s).length;
  const progress = receipts.length > 0 ? Math.round((results.length / receipts.length) * 100) : 0;

  return (
    <div className="w-full max-w-5xl mx-auto py-8 px-6">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-800 tracking-tight">PDF Attachment</h1>
        <p className="text-slate-500 mt-2">Fetch GRNs and attach Gmail PDFs to Zoho bills</p>
      </div>

      {/* Date inputs */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden mb-6">
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
            onClick={fetchGRNs}
            disabled={isRunning}
            className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl shadow transition disabled:opacity-50 flex items-center gap-2"
          >
            {isFetching ? <><Spinner /> Fetching…</> : "Fetch GRNs"}
          </button>
          {pageStatus === "GRNS_READY" && receipts.length > 0 && (
            <button
              onClick={attachPDFs}
              disabled={isRunning}
              className="px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded-xl shadow transition disabled:opacity-50 flex items-center gap-2"
            >
              Attach PDFs →
            </button>
          )}
        </div>

        {/* GRN count summary */}
        {(pageStatus === "GRNS_READY" || pageStatus === "ATTACHING" || pageStatus === "DONE") && (
          <div className="px-6 py-4 flex items-center gap-3 border-b border-slate-100">
            <span className="inline-flex items-center gap-1.5 bg-indigo-50 text-indigo-700 text-sm font-semibold px-3 py-1 rounded-full">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              {receipts.length} GRNs fetched
            </span>
            {facilityErrors.map((e, i) => (
              <span key={i} className="text-xs text-amber-700 bg-amber-50 px-2 py-1 rounded-lg">{e}</span>
            ))}
          </div>
        )}

        {/* Progress / status while attaching */}
        {(pageStatus === "ATTACHING" || (pageStatus === "DONE" && results.length > 0)) && (
          <div className="px-6 py-4 border-b border-slate-100">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-slate-600">
                {pageStatus === "ATTACHING"
                  ? "Fetching GRNs, searching Gmail and attaching PDFs…"
                  : `Completed — ${results.length} GRNs processed`}
              </span>
              {pageStatus === "DONE" && (
                <span className="text-sm font-semibold text-slate-700">100%</span>
              )}
            </div>
            <div className="w-full bg-slate-100 rounded-full h-2">
              <div
                className="bg-indigo-500 h-2 rounded-full transition-all duration-300"
                style={{ width: pageStatus === "DONE" ? "100%" : "60%" }}
              />
            </div>
          </div>
        )}

        {/* Summary chips after attaching */}
        {results.length > 0 && (
          <div className="px-6 py-4 flex flex-wrap gap-3 border-b border-slate-100">
            {countByStatus("ok") > 0 && (
              <span className="inline-flex items-center gap-1.5 bg-green-50 text-green-700 text-sm font-semibold px-3 py-1 rounded-full">
                ✓ {countByStatus("ok")} Attached
              </span>
            )}
            {countByStatus("no_pdf") > 0 && (
              <span className="inline-flex items-center gap-1.5 bg-amber-50 text-amber-700 text-sm font-semibold px-3 py-1 rounded-full">
                ⚠ {countByStatus("no_pdf")} No PDF
              </span>
            )}
            {countByStatus("no_bill") > 0 && (
              <span className="inline-flex items-center gap-1.5 bg-red-50 text-red-700 text-sm font-semibold px-3 py-1 rounded-full">
                ⚑ {countByStatus("no_bill")} Bill Not Pushed
              </span>
            )}
            {countByStatus("error") > 0 && (
              <span className="inline-flex items-center gap-1.5 bg-rose-50 text-rose-700 text-sm font-semibold px-3 py-1 rounded-full">
                ✕ {countByStatus("error")} Errors
              </span>
            )}
          </div>
        )}

        {/* Results table */}
        {results.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-left">
                  <th className="px-5 py-3 font-semibold text-slate-600">GRN Code</th>
                  <th className="px-5 py-3 font-semibold text-slate-600">Status</th>
                  <th className="px-5 py-3 font-semibold text-slate-600">Bill Number</th>
                  <th className="px-5 py-3 font-semibold text-slate-600">Files</th>
                  <th className="px-5 py-3 font-semibold text-slate-600">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {results.map(r => (
                  <tr
                    key={r.grn_code}
                    className={
                      r.status === "no_bill"
                        ? "bg-amber-50 border-l-4 border-l-amber-400"
                        : r.status === "ok"
                        ? "hover:bg-slate-50"
                        : "hover:bg-slate-50"
                    }
                  >
                    <td className="px-5 py-3 font-mono font-medium text-slate-700">{r.grn_code}</td>
                    <td className="px-5 py-3">
                      {r.status === "ok" && (
                        <span className="inline-flex items-center gap-1 bg-green-100 text-green-700 text-xs font-semibold px-2.5 py-1 rounded-full">
                          ✓ Attached
                        </span>
                      )}
                      {r.status === "no_pdf" && (
                        <span className="inline-flex items-center gap-1 bg-amber-100 text-amber-700 text-xs font-semibold px-2.5 py-1 rounded-full">
                          ⚠ No PDF
                        </span>
                      )}
                      {r.status === "no_bill" && (
                        <span className="inline-flex items-center gap-1 bg-amber-200 text-amber-800 text-xs font-semibold px-2.5 py-1 rounded-full">
                          ⚑ Bill Not Pushed
                        </span>
                      )}
                      {r.status === "error" && (
                        <span className="inline-flex items-center gap-1 bg-red-100 text-red-700 text-xs font-semibold px-2.5 py-1 rounded-full">
                          ✕ Error
                        </span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-slate-600 font-mono text-xs">{r.bill_number ?? "—"}</td>
                    <td className="px-5 py-3 text-slate-600 text-xs truncate max-w-xs">
                      {r.filenames && r.filenames.length > 0 ? r.filenames.join(", ") : "—"}
                    </td>
                    <td className="px-5 py-3 text-xs">
                      {r.status === "no_bill" ? (
                        <span className="text-amber-700 font-medium">Create the bill first via the Bills tab</span>
                      ) : r.error ? (
                        <span className="text-slate-400">{r.error}</span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Error banner */}
      {errorMsg && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm font-medium">
          {errorMsg}
        </div>
      )}

      {/* Empty state after fetch */}
      {pageStatus === "GRNS_READY" && receipts.length === 0 && (
        <div className="text-center py-12 text-slate-400">
          No GRNs found for this date range.
        </div>
      )}
    </div>
  );
}
