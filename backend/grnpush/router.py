import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from grn_log import LogEntry, append_entries, mark_pdf_attached, read_log
from grnpush.gmail_pdf import download_attachment, fetch_grn_pdfs
from grnpush.mapper import BillGroup, build_bill_payload, group_grns
from grnpush.unicommerce_client import unicommerce
from grnpush.zoho_bill_client import zoho_bill

logger = logging.getLogger("grn_push")

router = APIRouter(prefix="/grn-push", tags=["grn-push"])

DEFAULT_FACILITIES = ["EL_BLR_APEX", "EL_BLR_APEX_QC", "EL_VIRTUAL_BLR"]


# ── Step 1 ────────────────────────────────────────────────────────────────────

class ReceiptsRequest(BaseModel):
    start: str
    end: str


class ReceiptItem(BaseModel):
    grn_code: str
    facility: str


class ReceiptsResponse(BaseModel):
    receipts: list[ReceiptItem]
    errors: list[str] = []


# ── Step 2 ────────────────────────────────────────────────────────────────────

class FetchDetailsRequest(BaseModel):
    receipts: list[ReceiptItem]


class FetchDetailsResponse(BaseModel):
    bills: list[BillGroup]


# ── Step 3 ────────────────────────────────────────────────────────────────────

class CreateBillsRequest(BaseModel):
    bills: list[BillGroup]


class BillResult(BaseModel):
    bill_number: str
    vendor_name: str = ""
    grn_codes: list[str] = []
    items_count: int = 0
    total_value: float = 0.0
    will_skip: bool = False
    status: str
    bill_id: Optional[str] = None
    pdf_attached: bool = False
    error: Optional[str] = None


class CreateBillsResponse(BaseModel):
    total: int
    ok: int
    failed: int
    results: list[BillResult]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/receipts", response_model=ReceiptsResponse, summary="Step 1 — List GRN codes from Unicommerce")
def get_receipts(body: ReceiptsRequest) -> ReceiptsResponse:
    _check_unicommerce_config()
    receipts: list[ReceiptItem] = []
    errors: list[str] = []

    for facility in DEFAULT_FACILITIES:
        logger.info("Listing GRNs for %s from %s to %s", facility, body.start, body.end)
        try:
            codes = unicommerce.get_inflow_receipts_range(body.start, body.end, facility)
            for code in codes:
                receipts.append(ReceiptItem(grn_code=code, facility=facility))
        except Exception as exc:
            msg = f"{facility}: {exc}"
            logger.error("Failed to list GRNs — %s", msg)
            errors.append(msg)

    return ReceiptsResponse(receipts=receipts, errors=errors)


@router.post("/fetch-details", response_model=FetchDetailsResponse, summary="Step 2 — Fetch GRN details and group by bill number")
def fetch_details(body: FetchDetailsRequest) -> FetchDetailsResponse:
    _check_unicommerce_config()
    grns: list[tuple[dict, str]] = []

    for item in body.receipts:
        try:
            grn = unicommerce.get_inflow_receipt(item.grn_code, item.facility)
            grns.append((grn, item.facility))
        except Exception as exc:
            logger.error("Failed to fetch GRN %s: %s", item.grn_code, exc)

    bills = group_grns(grns)

    all_grn_codes = [item.grn_code for item in body.receipts]
    gmail_refs = fetch_grn_pdfs(all_grn_codes)
    for bill in bills:
        bill.grn_gmail_attachments = {
            code: gmail_refs[code]
            for code in bill.grn_codes
            if code in gmail_refs
        }

    logger.info("Grouped %d GRN(s) into %d bill(s)", len(grns), len(bills))
    return FetchDetailsResponse(bills=bills)


_SKIP_KEYWORDS = {"kitting", "dekitting", "return"}


def _should_skip(group: "BillGroup") -> bool:
    bill_lower = group.bill_number.lower()
    return any(kw in bill_lower for kw in _SKIP_KEYWORDS)


@router.post("/create-bills", response_model=CreateBillsResponse, summary="Step 3 — Push grouped bills as drafts to Zoho")
def create_bills(body: CreateBillsRequest) -> CreateBillsResponse:
    results: list[BillResult] = []

    for group in body.bills:
        total_value = sum(i.get("quantity", 0) * i.get("rate", 0) for i in group.line_items)
        base = BillResult(
            bill_number=group.bill_number,
            vendor_name=group.vendor_name,
            grn_codes=group.grn_codes,
            items_count=len(group.line_items),
            total_value=total_value,
            will_skip=_should_skip(group),
            status="",
        )
        if _should_skip(group):
            logger.info("Skipping bill %r (kitting/dekitting/return)", group.bill_number)
            base.status = "skipped"
            results.append(base)
            continue

        log_by_grn = {e.grn_code: e for e in read_log()}
        try:
            existing = zoho_bill.find_bill(group.bill_number)
            if existing:
                bill_id = existing["bill_id"]
                bill_date = existing["date"]
                new_entries = []
                for grn_code in group.grn_codes:
                    if grn_code not in log_by_grn:
                        new_entries.append(LogEntry(
                            grn_code=grn_code,
                            bill_number=group.bill_number,
                            bill_id=bill_id,
                            pdf_attached=False,
                            created_at=bill_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        ))
                if new_entries:
                    append_entries(new_entries)
                    log_by_grn.update({e.grn_code: e for e in new_entries})
                pdf_attached = all(log_by_grn.get(c) and log_by_grn[c].pdf_attached for c in group.grn_codes)
                logger.info("Bill %r already exists in Zoho (bill_id=%s)", group.bill_number, bill_id)
                base.status = "existing"
                base.bill_id = bill_id
                base.pdf_attached = pdf_attached
                results.append(base)
                continue

            vendor_id = zoho_bill.find_vendor_id(group.vendor_code, group.vendor_name, group.vendor_gst)
            if not vendor_id:
                raise ValueError(f"Zoho vendor not found: {group.vendor_code!r}")

            is_interstate = zoho_bill.is_interstate_vendor(vendor_id)
            skus = {item.get("sku", "") for item in group.line_items if item.get("sku")}
            item_meta_map = {sku: zoho_bill.find_item_metadata(sku) for sku in skus}
            payload = build_bill_payload(group, vendor_id, item_meta_map, is_interstate)
            bill = zoho_bill.create_draft_bill(payload)
            bill_id = bill["bill_id"]

            if group.grn_gmail_attachments:
                try:
                    attach_files = [
                        (ref.filename, download_attachment(ref.message_id, ref.attachment_id))
                        for ref in group.grn_gmail_attachments.values()
                    ]
                    zoho_bill.attach_pdf(bill_id, attach_files)
                except Exception as attach_exc:
                    logger.warning("PDF attach failed for bill %s: %s", bill_id, attach_exc)

            base.status = "ok"
            base.bill_id = bill_id
            results.append(base)
        except Exception as exc:
            logger.error("Bill %s failed: %s", group.bill_number, exc)
            base.status = "error"
            base.error = str(exc)
            results.append(base)

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    return CreateBillsResponse(total=len(results), ok=ok, failed=len(results) - ok - skipped, results=results)


@router.get("/fetch-pdf/{grn_code}", summary="Fetch vendor invoice PDF from Gmail for a GRN code")
def fetch_pdf(grn_code: str) -> StreamingResponse:
    refs = fetch_grn_pdfs([grn_code])
    if grn_code not in refs:
        raise HTTPException(status_code=404, detail=f"No email with PDF found for GRN {grn_code!r}")
    ref = refs[grn_code]
    pdf_bytes = download_attachment(ref.message_id, ref.attachment_id)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{ref.filename}"'},
    )


# ── One-click run ─────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    start: str
    end: str


class RunResponse(BaseModel):
    total: int
    ok: int
    failed: int
    skipped: int
    results: list[BillResult]


@router.post("/run", response_model=RunResponse, summary="One-click — list GRNs, group, and push bills to Zoho")
def run_pipeline(body: RunRequest) -> RunResponse:
    _check_unicommerce_config()

    # Step 1: collect GRN codes across all facilities
    receipts: list[ReceiptItem] = []
    for facility in DEFAULT_FACILITIES:
        try:
            codes = unicommerce.get_inflow_receipts_range(body.start, body.end, facility)
            for code in codes:
                receipts.append(ReceiptItem(grn_code=code, facility=facility))
        except Exception as exc:
            logger.error("Failed listing GRNs for %s: %s", facility, exc)

    if not receipts:
        return RunResponse(total=0, ok=0, failed=0, skipped=0, results=[])

    # Step 2: fetch GRN details + group by bill number
    grns: list[tuple[dict, str]] = []
    for item in receipts:
        try:
            grn = unicommerce.get_inflow_receipt(item.grn_code, item.facility)
            grns.append((grn, item.facility))
        except Exception as exc:
            logger.error("Failed fetching GRN %s: %s", item.grn_code, exc)

    bills = group_grns(grns)

    # Step 3: create bills in Zoho + write log
    results: list[BillResult] = []
    log_entries: list[LogEntry] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_by_grn = {e.grn_code: e for e in read_log()}

    for group in bills:
        total_value = sum(i.get("quantity", 0) * i.get("rate", 0) for i in group.line_items)
        base = BillResult(
            bill_number=group.bill_number,
            vendor_name=group.vendor_name,
            grn_codes=group.grn_codes,
            items_count=len(group.line_items),
            total_value=total_value,
            will_skip=_should_skip(group),
            status="",
        )
        if _should_skip(group):
            base.status = "skipped"
            results.append(base)
            continue

        try:
            existing = zoho_bill.find_bill(group.bill_number)
            if existing:
                bill_id = existing["bill_id"]
                bill_date = existing["date"]
                for grn_code in group.grn_codes:
                    if grn_code not in log_by_grn:
                        entry = LogEntry(
                            grn_code=grn_code,
                            bill_number=group.bill_number,
                            bill_id=bill_id,
                            pdf_attached=False,
                            created_at=bill_date or today,
                        )
                        log_entries.append(entry)
                        log_by_grn[grn_code] = entry
                pdf_attached = all(log_by_grn.get(c) and log_by_grn[c].pdf_attached for c in group.grn_codes)
                logger.info("Bill %r already exists in Zoho (bill_id=%s)", group.bill_number, bill_id)
                base.status = "existing"
                base.bill_id = bill_id
                base.pdf_attached = pdf_attached
                results.append(base)
                continue

            vendor_id = zoho_bill.find_vendor_id(group.vendor_code, group.vendor_name)
            if not vendor_id:
                raise ValueError(f"Vendor not found: {group.vendor_code!r}")

            is_interstate = zoho_bill.is_interstate_vendor(vendor_id)
            skus = {item.get("sku", "") for item in group.line_items if item.get("sku")}
            item_meta_map = {sku: zoho_bill.find_item_metadata(sku) for sku in skus}
            payload = build_bill_payload(group, vendor_id, item_meta_map, is_interstate)
            bill = zoho_bill.create_draft_bill(payload)
            bill_id = bill["bill_id"]

            for grn_code in group.grn_codes:
                entry = LogEntry(
                    grn_code=grn_code,
                    bill_number=group.bill_number,
                    bill_id=bill_id,
                    pdf_attached=False,
                    created_at=today,
                )
                log_entries.append(entry)
                log_by_grn[grn_code] = entry

            base.status = "ok"
            base.bill_id = bill_id
            results.append(base)
        except Exception as exc:
            logger.error("Bill %s failed: %s", group.bill_number, exc)
            base.status = "error"
            base.error = str(exc)
            results.append(base)

    if log_entries:
        append_entries(log_entries)

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    return RunResponse(total=len(results), ok=ok, failed=len(results) - ok - skipped, skipped=skipped, results=results)


# ── Attach PDF(s) ─────────────────────────────────────────────────────────────

_bill_locks: dict[str, threading.Lock] = {}
_bill_locks_mutex = threading.Lock()


def _get_bill_lock(key: str) -> threading.Lock:
    with _bill_locks_mutex:
        if key not in _bill_locks:
            _bill_locks[key] = threading.Lock()
        return _bill_locks[key]


class GrnAttachResult(BaseModel):
    grn_code: str
    bill_number: str
    status: str  # "ok" | "already_attached" | "no_bill" | "no_pdf" | "error"
    filenames: list[str] = []
    error: Optional[str] = None


class AttachPdfsRequest(BaseModel):
    receipts: list[ReceiptItem]


class AttachPdfsResponse(BaseModel):
    total_bills: int
    total_grns: int
    results: list[GrnAttachResult]


@router.post("/attach-pdfs", response_model=AttachPdfsResponse, summary="Fetch GRNs, group by bill, attach Gmail PDFs to Zoho bills")
def attach_pdfs_batch(body: AttachPdfsRequest) -> AttachPdfsResponse:
    _check_unicommerce_config()

    # Fetch GRN details from Unicommerce and group by bill number
    grns: list[tuple[dict, str]] = []
    for item in body.receipts:
        try:
            grn = unicommerce.get_inflow_receipt(item.grn_code, item.facility)
            grns.append((grn, item.facility))
        except Exception as exc:
            logger.error("Failed to fetch GRN %s: %s", item.grn_code, exc)

    bill_groups = group_grns(grns)

    # Read log once for the initial fast-path check
    attached_set = {e.grn_code for e in read_log() if e.pdf_attached}
    grn_results: list[GrnAttachResult] = []

    for group in bill_groups:
        pending_fast = [c for c in group.grn_codes if c not in attached_set]

        if not pending_fast:
            for grn_code in group.grn_codes:
                grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="already_attached"))
            continue

        with _get_bill_lock(group.bill_number):
            # Re-read inside the lock — another concurrent call may have finished in the meantime
            attached_locked = {e.grn_code for e in read_log() if e.pdf_attached}
            pending = [c for c in group.grn_codes if c not in attached_locked]

            if not pending:
                for grn_code in group.grn_codes:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="already_attached"))
                continue

            # One Zoho call per bill: find bill by number + vendor
            try:
                vendor_id = zoho_bill.find_vendor_id(group.vendor_code, group.vendor_name, group.vendor_gst)
                bill = zoho_bill.find_bill(group.bill_number, vendor_id=vendor_id)
            except Exception as exc:
                logger.error("Error looking up bill %r: %s", group.bill_number, exc)
                for grn_code in group.grn_codes:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="error", error=str(exc)))
                continue

            if not bill:
                logger.warning("Bill %r not found in Zoho", group.bill_number)
                for grn_code in group.grn_codes:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="no_bill"))
                continue

            bill_id = bill["bill_id"]

            # Fetch PDFs from Gmail for pending GRNs only
            refs = fetch_grn_pdfs(pending)

            # Download PDFs for every GRN that has a Gmail match
            files: list[tuple[str, bytes]] = []
            attached_grns: list[str] = []
            for grn_code, ref in refs.items():
                try:
                    pdf_bytes = download_attachment(ref.message_id, ref.attachment_id)
                    files.append((ref.filename, pdf_bytes))
                    attached_grns.append(grn_code)
                except Exception as exc:
                    logger.error("Failed to download PDF for GRN %s: %s", grn_code, exc)

            if not files:
                for grn_code in group.grn_codes:
                    status = "already_attached" if grn_code in attached_locked else "no_pdf"
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status=status))
                continue

            # POST to Zoho — only after all files are ready
            try:
                zoho_bill.attach_pdf(bill_id, files)
            except RuntimeError as exc:
                logger.error("Zoho attach failed for bill %s: %s", bill_id, exc)
                for grn_code in group.grn_codes:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="error", error=str(exc)))
                continue

            filenames = [fn for fn, _ in files]

            # Mark ONLY the GRNs whose PDF was in this POST — upserts if not in log yet
            for grn_code in attached_grns:
                mark_pdf_attached(grn_code, bill_number=group.bill_number, bill_id=bill_id)

            for grn_code in group.grn_codes:
                if grn_code in attached_locked:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="already_attached"))
                elif grn_code in attached_grns:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="ok", filenames=filenames))
                else:
                    grn_results.append(GrnAttachResult(grn_code=grn_code, bill_number=group.bill_number, status="no_pdf"))

    return AttachPdfsResponse(total_bills=len(bill_groups), total_grns=len(grn_results), results=grn_results)


# ── Sync Log ─────────────────────────────────────────────────────────────────

class SyncLogRequest(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class SyncLogResponse(BaseModel):
    fetched: int
    added: int


@router.post("/sync-log", response_model=SyncLogResponse, summary="Import existing Zoho bills into the local GRN log")
def sync_log(body: SyncLogRequest) -> SyncLogResponse:
    bills = zoho_bill.list_bills(date_from=body.date_from, date_to=body.date_to)

    existing_codes = {e.grn_code for e in read_log()}
    new_entries: list[LogEntry] = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for bill in bills:
        bill_id = bill["bill_id"]
        bill_number = bill["bill_number"]
        cf_grn = bill["cf_grn"]
        if not cf_grn or not bill_id:
            continue
        for grn_code in [g.strip() for g in cf_grn.split(",") if g.strip()]:
            if grn_code not in existing_codes:
                new_entries.append(LogEntry(
                    grn_code=grn_code,
                    bill_number=bill_number,
                    bill_id=bill_id,
                    pdf_attached=False,
                    created_at=bill["date"] or today,
                ))
                existing_codes.add(grn_code)

    if new_entries:
        append_entries(new_entries)
    logger.info("sync-log: fetched=%d added=%d", len(bills), len(new_entries))
    return SyncLogResponse(fetched=len(bills), added=len(new_entries))


# ── Log ───────────────────────────────────────────────────────────────────────

class LogResponse(BaseModel):
    entries: list[LogEntry]


@router.get("/log", response_model=LogResponse, summary="View GRN push history log")
def get_log() -> LogResponse:
    return LogResponse(entries=read_log())


def _check_unicommerce_config() -> None:
    if not settings.unicommerce_username or not settings.unicommerce_password:
        raise HTTPException(
            status_code=503,
            detail="UNICOMMERCE_USERNAME / UNICOMMERCE_PASSWORD not configured in .env",
        )
