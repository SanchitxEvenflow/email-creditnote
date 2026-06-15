"use client";

import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

function escHtml(str: string) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

type ToastType = "success" | "error";

interface EmailResponse {
  to: string;
  sent_count: number;
  emails_sent: number;
  failed: { number: string; error: string }[];
}

export default function Home() {
  const [rawInput, setRawInput] = useState("");
  const [parsedNumbers, setParsedNumbers] = useState<string[]>([]);
  const [emailInput, setEmailInput] = useState("");
  const [subject, setSubject] = useState("Credit Notes");
  const [emailBody, setEmailBody] = useState("Please find the credit note PDFs attached.");
  const [isDragOver, setIsDragOver] = useState(false);
  const [toast, setToast] = useState<{ type: ToastType; msg: string } | null>(null);
  const [result, setResult] = useState<{ type: ToastType; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyMode, setBusyMode] = useState<"download" | "email" | null>(null);
  const [progress, setProgress] = useState(0);
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dlAnchor = useRef<HTMLAnchorElement>(null);

  const parseNumbers = useCallback((raw: string) => {
    const parts = raw
      .split(/[\n,;]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    const unique = [...new Map(parts.map((s) => [s.toUpperCase(), s])).values()];
    setParsedNumbers(unique);
  }, []);

  useEffect(() => {
    parseNumbers(rawInput);
  }, [rawInput, parseNumbers]);

  const removeChip = (idx: number) => {
    const updated = parsedNumbers.filter((_, i) => i !== idx);
    setParsedNumbers(updated);
    setRawInput(updated.join("\n"));
  };

  const clearAll = () => {
    setRawInput("");
    setEmailInput("");
    setParsedNumbers([]);
    setResult(null);
  };

  const showToast = (type: ToastType, msg: string) => {
    setToast({ type, msg });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  };

  const startProgress = () => {
    setProgress(0);
    if (progressTimer.current) clearInterval(progressTimer.current);
    let w = 0;
    progressTimer.current = setInterval(() => {
      w = Math.min(w + Math.random() * 3, 85);
      setProgress(w);
    }, 600);
  };

  const endProgress = () => {
    if (progressTimer.current) clearInterval(progressTimer.current);
    setProgress(100);
    setTimeout(() => setProgress(0), 500);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => setIsDragOver(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setRawInput(ev.target?.result as string);
    };
    reader.readAsText(file);
  };

  const triggerDownload = async () => {
    const numbers = parsedNumbers.slice(0, 500);
    if (!numbers.length) return;
    setBusy(true);
    setBusyMode("download");
    setResult(null);
    startProgress();
    try {
      const resp = await fetch(`${API_BASE}/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credit_note_numbers: numbers }),
      });
      if (!resp.ok) {
        let detail = `Server error ${resp.status}`;
        try {
          detail = (await resp.json()).detail ?? detail;
        } catch {}
        throw new Error(detail);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = dlAnchor.current!;
      a.href = url;
      a.download = "credit_notes.zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      setResult({ type: "success", msg: `Download started — credit_notes.zip (${numbers.length} note${numbers.length > 1 ? "s" : ""})` });
      showToast("success", "ZIP downloaded!");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unexpected error.";
      setResult({ type: "error", msg });
      showToast("error", msg);
    } finally {
      endProgress();
      setBusy(false);
      setBusyMode(null);
    }
  };

  const triggerSendEmail = async () => {
    const numbers = parsedNumbers.slice(0, 500);
    if (!numbers.length || !emailInput.trim()) return;
    setBusy(true);
    setBusyMode("email");
    setResult(null);
    startProgress();
    try {
      const resp = await fetch(`${API_BASE}/send-email`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          credit_note_numbers: numbers,
          to_email: emailInput.trim(),
          subject: subject.trim() || "Credit Notes",
          body: emailBody.trim() || "Please find the credit note PDFs attached.",
        }),
      });
      if (!resp.ok) {
        let detail = `Server error ${resp.status}`;
        try {
          detail = (await resp.json()).detail ?? detail;
        } catch {}
        throw new Error(detail);
      }
      const data: EmailResponse = await resp.json();
      const failNote = data.failed?.length ? ` · ${data.failed.length} failed` : "";
      const emailNote = data.emails_sent > 1 ? ` in ${data.emails_sent} emails (split by size)` : "";
      setResult({ type: "success", msg: `Sent ${data.sent_count} PDF${data.sent_count > 1 ? "s" : ""} to ${data.to}${emailNote}${failNote}` });
      showToast("success", `Email sent to ${data.to}!`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unexpected error.";
      setResult({ type: "error", msg });
      showToast("error", msg);
    } finally {
      endProgress();
      setBusy(false);
      setBusyMode(null);
    }
  };

  const hasNotes = parsedNumbers.length > 0 && parsedNumbers.length <= 500;
  const hasEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailInput.trim());
  const downloadDisabled = busy || !hasNotes;
  const emailDisabled = busy || !hasNotes || !hasEmail;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-indigo-50 flex flex-col items-center pb-16">
      {/* Hidden download anchor */}
      <a ref={dlAnchor} className="hidden" />

      {/* Toast */}
      {toast && (
        <div
          className={`fixed top-6 right-6 z-50 flex items-center gap-3 px-5 py-3 rounded-xl shadow-lg text-sm font-medium max-w-sm ${
            toast.type === "success" ? "bg-green-600 text-white" : "bg-red-600 text-white"
          }`}
        >
          <span className="text-lg">{toast.type === "success" ? "✓" : "✕"}</span>
          <span>{toast.msg}</span>
        </div>
      )}

      {/* Navbar */}
      <nav className="w-full bg-black px-6 py-3 flex items-center mb-8" style={{ minHeight: 64 }}>
        <Image src="/logo.png" className="h-16 w-auto" alt="Evenflow logo" width={160} height={64} priority />
        <span className="flex-1 text-center text-white font-semibold text-xl tracking-tight">
          Email: Credit Notes (Zoho)
        </span>
      </nav>

      <div className="w-full max-w-2xl px-4">
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">

          {/* Credit note input */}
          <div className="p-6 border-b border-slate-100">
            <label className="block text-sm font-semibold text-slate-700 mb-2">
              Credit Note Numbers{" "}
              <span className="ml-1 font-normal text-slate-400">(one per line, or comma-separated)</span>
            </label>
            <div
              className={`drop-zone rounded-xl border-2 border-dashed border-slate-200 bg-slate-50 transition-all${isDragOver ? " drag-over" : ""}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <textarea
                rows={8}
                value={rawInput}
                onChange={(e) => setRawInput(e.target.value)}
                placeholder={"RTVCN2627/0432\nRTVCN2627/0433\nRTVCN2627/0434\n...or paste a comma-separated list"}
                className="w-full bg-transparent px-4 py-3 text-sm text-slate-700 placeholder-slate-400 resize-none outline-none font-mono"
              />
              <div className="flex items-center justify-between px-4 py-2 border-t border-dashed border-slate-200 text-xs text-slate-400">
                <span>Drag &amp; drop a <code>.txt</code> file here</span>
                <button onClick={clearAll} className="text-slate-400 hover:text-red-400 transition-colors">Clear all</button>
              </div>
            </div>
          </div>

          {/* Chips */}
          {parsedNumbers.length > 0 && (
            <div className="px-6 py-4 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Parsed</span>
                <span className="text-xs font-semibold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded-full">
                  {parsedNumbers.length}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {parsedNumbers.slice(0, 500).map((num, idx) => (
                  <span key={idx} className="chip">
                    <span dangerouslySetInnerHTML={{ __html: escHtml(num) }} />
                    <button onClick={() => removeChip(idx)} title="Remove">×</button>
                  </span>
                ))}
                {parsedNumbers.length > 500 && (
                  <span className="text-xs text-red-400 font-medium self-center">
                    +{parsedNumbers.length - 500} ignored
                  </span>
                )}
              </div>
              {parsedNumbers.length > 500 && (
                <p className="mt-2 text-xs text-red-500 font-medium">Maximum 500 credit notes allowed.</p>
              )}
            </div>
          )}

          {/* Email input */}
          <div className="px-6 pt-5 pb-2">
            <label className="block text-sm font-semibold text-slate-700 mb-2">
              Send to Email{" "}
              <span className="ml-1 font-normal text-slate-400">(required for Send Email)</span>
            </label>
            <input
              type="email"
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              placeholder="recipient@example.com"
              className="w-full px-4 py-2.5 text-sm border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 transition text-slate-700 placeholder-slate-400"
            />
          </div>

          {/* Subject & Body */}
          <div className="px-6 pt-4 pb-2 flex flex-col gap-3">
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Subject</label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full px-4 py-2.5 text-sm border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 transition text-slate-700"
              />
            </div>
            <div>
              <label className="block text-sm font-semibold text-slate-700 mb-1">Email Body</label>
              <textarea
                rows={3}
                value={emailBody}
                onChange={(e) => setEmailBody(e.target.value)}
                className="w-full px-4 py-2.5 text-sm border border-slate-200 rounded-xl outline-none focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400 transition text-slate-700 resize-y"
              />
            </div>
          </div>

          {/* Action buttons */}
          <div className="px-6 pt-3 pb-6 flex gap-3">
            <button
              onClick={triggerDownload}
              disabled={downloadDisabled}
              className="flex-1 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-xl transition-colors text-sm"
            >
              {busy && busyMode === "download" ? (
                <div className="spinner shrink-0 ![border-top-color:#fff]" />
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3" />
                </svg>
              )}
              <span>{busy && busyMode === "download" ? `Fetching ${parsedNumbers.slice(0, 500).length}…` : "Download ZIP"}</span>
            </button>

            <button
              onClick={triggerSendEmail}
              disabled={emailDisabled}
              className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-semibold py-3 px-4 rounded-xl transition-colors text-sm"
            >
              {busy && busyMode === "email" ? (
                <div className="spinner shrink-0 ![border-top-color:#fff]" />
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              )}
              <span>{busy && busyMode === "email" ? `Sending ${parsedNumbers.slice(0, 500).length}…` : "Send Email"}</span>
            </button>
          </div>

          {/* Progress bar */}
          {busy && (
            <div className="px-6 pb-4">
              <div className="flex items-center gap-2 text-sm text-slate-500 mb-2">
                <div className="spinner !border-slate-300 ![border-top-color:#6366f1]" />
                <span>{busyMode === "download" ? "Resolving IDs and downloading PDFs…" : "Fetching PDFs and sending email…"}</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-indigo-500 h-1.5 rounded-full transition-all duration-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="text-xs text-slate-400 mt-1">This may take 10–40 seconds depending on batch size.</p>
            </div>
          )}

          {/* Result banner */}
          {result && (
            <div className={`mx-6 mb-6 flex items-start gap-3 rounded-xl px-4 py-3 text-sm font-medium ${
              result.type === "success" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
            }`}>
              <span className="text-lg mt-0.5">{result.type === "success" ? "✓" : "✕"}</span>
              <span>{result.msg}</span>
            </div>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          Tokens are refreshed automatically. Failed notes appear as <code>_ERROR.txt</code> in the ZIP.
        </p>
      </div>
    </div>
  );
}
