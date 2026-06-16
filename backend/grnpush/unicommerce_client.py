import logging
import threading
import time

import requests

from config import settings

logger = logging.getLogger("unicommerce")

_OAUTH_PATH = "/oauth/token"
_GRN_LIST_PATH = "/services/rest/v1/purchase/inflowReceipt/getInflowReceipts"
_GRN_DETAIL_PATH = "/services/rest/v1/purchase/inflowReceipt/getInflowReceipt"


class UnicommerceClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._session = requests.Session()

    def _get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - 60:
                return self._token
            self._refresh_token()
            return self._token

    def _refresh_token(self) -> None:
        logger.info("Refreshing Unicommerce token")
        resp = self._session.post(
            f"{settings.unicommerce_base_url}{_OAUTH_PATH}",
            params={
                "grant_type": "password",
                "client_id": settings.unicommerce_client_id,
                "username": settings.unicommerce_username,
                "password": settings.unicommerce_password,
            },
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"Unicommerce token refresh failed: {data}")
        self._token = data["access_token"]
        self._expires_at = time.time() + data.get("expires_in", 3600)
        logger.info("Unicommerce token refreshed OK")

    def _post(self, path: str, body: dict, facility: str) -> dict:
        token = self._get_token()
        resp = self._session.post(
            f"{settings.unicommerce_base_url}{path}",
            json=body,
            headers={
                "Authorization": f"bearer {token}",
                "Content-Type": "application/json",
                "Facility": facility,
            },
            timeout=30,
        )
        if not resp.ok:
            logger.error("Unicommerce %s error %s: %s", path, resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _to_iso_date(date_str: str) -> str:
        """Accept YYYY-MM-DD or DD/MM/YYYY, always return YYYY-MM-DD."""
        if "/" in date_str:
            d, m, y = date_str.split("/")
            return f"{y}-{m}-{d}"
        return date_str

    def get_inflow_receipts_range(self, start: str, end: str, facility: str) -> list[str]:
        """Return list of inflowReceiptCodes for the given date range and facility."""
        start = self._to_iso_date(start)
        end = self._to_iso_date(end)
        body = {
            "createdBetween": {
                "start": f"{start}T00:00:00.000Z",
                "end": f"{end}T23:59:59.999Z",
                "textRange": "TODAY",
            }
        }
        data = self._post(_GRN_LIST_PATH, body, facility)
        codes = data.get("inflowReceiptCodes") or []
        logger.info("Facility %s from %s to %s: %d GRN(s) found", facility, start, end, len(codes))
        return codes

    def get_inflow_receipt(self, code: str, facility: str) -> dict:
        """Return full GRN detail dict for the given inflowReceiptCode."""
        data = self._post(_GRN_DETAIL_PATH, {"inflowReceiptCode": code}, facility)
        receipt = data.get("inflowReceiptResponse") or data.get("inflowReceipt") or data
        logger.info("Fetched GRN detail: %s", code)
        return receipt


unicommerce = UnicommerceClient()
