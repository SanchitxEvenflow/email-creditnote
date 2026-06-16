import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
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
    status: str
    bill_id: Optional[str] = None
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
        if _should_skip(group):
            logger.info("Skipping bill %r (kitting/dekitting/return)", group.bill_number)
            results.append(BillResult(bill_number=group.bill_number, status="skipped"))
            continue

        try:
            if zoho_bill.bill_exists(group.bill_number):
                raise ValueError(f"Bill {group.bill_number!r} already exists in Zoho")

            vendor_id = zoho_bill.find_vendor_id(group.vendor_code, group.vendor_name)
            if not vendor_id:
                raise ValueError(f"Zoho vendor not found: {group.vendor_code!r}")

            is_interstate = zoho_bill.is_interstate_vendor(group.vendor_name)
            skus = {item.get("sku", "") for item in group.line_items if item.get("sku")}
            item_meta_map = {sku: zoho_bill.find_item_metadata(sku) for sku in skus}
            payload = build_bill_payload(group, vendor_id, item_meta_map, is_interstate)
            bill = zoho_bill.create_draft_bill(payload)
            results.append(BillResult(bill_number=group.bill_number, status="ok", bill_id=bill["bill_id"]))
        except Exception as exc:
            logger.error("Bill %s failed: %s", group.bill_number, exc)
            results.append(BillResult(bill_number=group.bill_number, status="error", error=str(exc)))

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    return CreateBillsResponse(total=len(results), ok=ok, failed=len(results) - ok - skipped, results=results)


def _check_unicommerce_config() -> None:
    if not settings.unicommerce_username or not settings.unicommerce_password:
        raise HTTPException(
            status_code=503,
            detail="UNICOMMERCE_USERNAME / UNICOMMERCE_PASSWORD not configured in .env",
        )
