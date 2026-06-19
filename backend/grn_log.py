from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

LOG_PATH = Path(__file__).parent / "grn_log.json"
_lock = threading.Lock()


class LogEntry(BaseModel):
    grn_code: str
    bill_number: str
    bill_id: str
    pdf_attached: bool = False
    created_at: str


def _load_raw() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    text = LOG_PATH.read_text().strip()
    return json.loads(text) if text else []


def read_log() -> list[LogEntry]:
    with _lock:
        return [LogEntry(**e) for e in _load_raw()]


def append_entries(entries: list[LogEntry]) -> None:
    with _lock:
        existing: list[dict] = _load_raw()
        existing_codes = {e["grn_code"] for e in existing}
        for entry in entries:
            if entry.grn_code not in existing_codes:
                existing.append(entry.model_dump())
        LOG_PATH.write_text(json.dumps(existing, indent=2))


def mark_pdf_attached(grn_code: str, bill_number: str = "", bill_id: str = "") -> None:
    """Mark a GRN's PDF as attached. Upserts if the GRN is not yet in the log."""
    with _lock:
        data = _load_raw()
        found = False
        for e in data:
            if e["grn_code"] == grn_code:
                e["pdf_attached"] = True
                found = True
        if not found and bill_number:
            data.append({
                "grn_code": grn_code,
                "bill_number": bill_number,
                "bill_id": bill_id,
                "pdf_attached": True,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
        LOG_PATH.write_text(json.dumps(data, indent=2))
