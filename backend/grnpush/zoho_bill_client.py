import logging
import time

import requests

from config import settings
from zoho_client import MAX_RETRIES, BACKOFF_BASE, MAX_WAIT_SECS, ZOHO_API_BASE, token_manager

logger = logging.getLogger("zoho_bill")

_ORG_STATE_CODE = "29"  # Karnataka


def _word_overlap(a: str, b: str) -> int:
    a_words = {w for w in a.lower().split() if len(w) > 3}
    b_words = {w for w in b.lower().split() if len(w) > 3}
    return len(a_words & b_words)


class ZohoBillClient:
    def __init__(self):
        self._session = requests.Session()
        self._vendor_cache: dict[str, str] = {}   # name_lower → contact_id
        self._vendor_gst: dict[str, str] = {}     # name_lower → gst_no
        self._item_cache: dict[str, dict | None] = {}

    def _get(self, url: str, params: dict) -> requests.Response:
        for attempt in range(MAX_RETRIES):
            headers = {"Authorization": f"Zoho-oauthtoken {token_manager.get_token()}"}
            resp = self._session.get(url, params=params, headers=headers, timeout=30)

            if resp.status_code == 401:
                logger.warning("401 — refreshing Zoho token")
                token_manager.force_refresh()
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", BACKOFF_BASE ** (attempt + 1)))
                if retry_after > MAX_WAIT_SECS:
                    logger.error("429 Retry-After=%s exceeds MAX_WAIT_SECS — aborting", retry_after)
                    return resp
                if attempt < MAX_RETRIES - 1:
                    logger.warning("429 — waiting %.0fs (attempt %d)", retry_after, attempt + 1)
                    time.sleep(retry_after)
                    continue

            return resp

        return resp

    def _post(self, url: str, params: dict, payload: dict) -> requests.Response:
        for attempt in range(MAX_RETRIES):
            headers = {
                "Authorization": f"Zoho-oauthtoken {token_manager.get_token()}",
                "Content-Type": "application/json",
            }
            resp = self._session.post(url, params=params, json=payload, headers=headers, timeout=30)

            if resp.status_code == 401:
                logger.warning("401 — refreshing Zoho token")
                token_manager.force_refresh()
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", BACKOFF_BASE ** (attempt + 1)))
                if retry_after > MAX_WAIT_SECS:
                    logger.error("429 Retry-After=%s exceeds MAX_WAIT_SECS — aborting", retry_after)
                    return resp
                if attempt < MAX_RETRIES - 1:
                    logger.warning("429 — waiting %.0fs (attempt %d)", retry_after, attempt + 1)
                    time.sleep(retry_after)
                    continue

            return resp

        return resp

    def _load_all_vendors(self) -> None:
        logger.info("Loading all Zoho vendors into cache...")
        page = 1
        while True:
            resp = self._get(
                f"{ZOHO_API_BASE}/contacts",
                params={"organization_id": settings.org_id, "contact_type": "vendor",
                        "page": page, "per_page": 200},
            )
            data = resp.json() if resp.ok else {}
            for c in data.get("contacts", []):
                name_lower = c["contact_name"].lower()
                self._vendor_cache[name_lower] = c["contact_id"]
                self._vendor_gst[name_lower] = c.get("gst_no") or ""
            if not data.get("page_context", {}).get("has_more_page"):
                break
            page += 1
        logger.info("Loaded %d vendors into cache", len(self._vendor_cache))

    def find_vendor_id(self, vendor_code: str, vendor_name: str = "") -> str | None:
        if not self._vendor_cache:
            self._load_all_vendors()

        key = vendor_name.lower()

        # exact match
        vendor_id = self._vendor_cache.get(key)

        # substring match
        if not vendor_id and vendor_name:
            vendor_id = next(
                (cid for name, cid in self._vendor_cache.items() if key in name or name in key),
                None,
            )

        # word-overlap match (handles "PVT.LTD" vs "PRIVATE LIMITED")
        if not vendor_id and vendor_name:
            best_name = max(
                self._vendor_cache.keys(),
                key=lambda name: _word_overlap(key, name),
                default=None,
            )
            if best_name and _word_overlap(key, best_name) >= 2:
                vendor_id = self._vendor_cache[best_name]
                logger.info("Vendor %r matched by word-overlap → %r", vendor_name, best_name)

        if vendor_id:
            logger.info("Vendor %r → %s", vendor_name or vendor_code, vendor_id)
        else:
            logger.warning("Vendor not found in Zoho: code=%r name=%r", vendor_code, vendor_name)
        return vendor_id

    def is_interstate_vendor(self, vendor_name: str) -> bool:
        if not self._vendor_cache:
            self._load_all_vendors()
        gst = self._vendor_gst.get(vendor_name.lower(), "")
        if not gst:
            return True  # no GST on file → assume interstate (safer default)
        return not gst.startswith(_ORG_STATE_CODE)

    def find_item_metadata(self, sku: str) -> dict | None:
        if sku in self._item_cache:
            return self._item_cache[sku]

        resp = self._get(
            f"{ZOHO_API_BASE}/items",
            params={"organization_id": settings.org_id, "search_text": sku},
        )
        items = resp.json().get("items", []) if resp.ok else []
        match = next((i for i in items if i.get("sku") == sku), items[0] if items else None)

        if match:
            tax_prefs = match.get("item_tax_preferences") or []
            intra_tax = next((p["tax_id"] for p in tax_prefs if p.get("tax_specification") == "intra"), None)
            inter_tax = next((p["tax_id"] for p in tax_prefs if p.get("tax_specification") == "inter"), None)
            meta = {
                "item_id": match.get("item_id"),
                "account_id": match.get("purchase_account_id") or match.get("account_id"),
                "intra_tax_id": intra_tax,
                "inter_tax_id": inter_tax,
            }
            logger.info("Item SKU %r → item_id=%s intra_tax=%s inter_tax=%s",
                        sku, meta["item_id"], intra_tax, inter_tax)
        else:
            meta = None
            logger.warning("Item SKU %r not found in Zoho", sku)

        self._item_cache[sku] = meta
        return meta

    def bill_exists(self, bill_number: str) -> bool:
        resp = self._get(
            f"{ZOHO_API_BASE}/bills",
            params={"organization_id": settings.org_id, "bill_number": bill_number},
        )
        bills = resp.json().get("bills", []) if resp.ok else []
        return any(b.get("bill_number") == bill_number for b in bills)

    def create_draft_bill(self, payload: dict) -> dict:
        grn_code = payload.get("bill_number", "?")
        logger.info("Creating draft bill for GRN %s", grn_code)
        resp = self._post(
            f"{ZOHO_API_BASE}/bills",
            params={"organization_id": settings.org_id},
            payload=payload,
        )
        data = resp.json()
        if not resp.ok or data.get("code", 0) != 0:
            raise RuntimeError(f"Zoho bill creation failed [{resp.status_code}]: {data}")
        bill_id = data["bill"]["bill_id"]
        logger.info("Draft bill created: %s → bill_id=%s", grn_code, bill_id)
        return data["bill"]

    def attach_pdf(self, bill_id: str, filename: str, pdf_bytes: bytes) -> None:
        for attempt in range(MAX_RETRIES):
            headers = {"Authorization": f"Zoho-oauthtoken {token_manager.get_token()}"}
            resp = self._session.post(
                f"{ZOHO_API_BASE}/bills/{bill_id}/documents",
                params={"organization_id": settings.org_id},
                headers=headers,
                files={"attachment": (filename, pdf_bytes, "application/pdf")},
                timeout=60,
            )
            if resp.status_code == 401:
                token_manager.force_refresh()
                continue
            if resp.status_code == 429:
                wait = min(BACKOFF_BASE * (2 ** attempt), MAX_WAIT_SECS)
                logger.warning("429 attaching PDF, waiting %ss", wait)
                time.sleep(wait)
                continue
            if not resp.ok:
                raise RuntimeError(f"Zoho attach_pdf failed [{resp.status_code}]: {resp.text}")
            logger.info("PDF %s attached to bill %s", filename, bill_id)
            return
        raise RuntimeError(f"Zoho attach_pdf exceeded retries for bill {bill_id}")


zoho_bill = ZohoBillClient()
