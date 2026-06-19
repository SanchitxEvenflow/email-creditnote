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


def read_log() -> list[LogEntry]:
    with _lock:
        if not LOG_PATH.exists():
            return []
        data = json.loads(LOG_PATH.read_text())
        return [LogEntry(**e) for e in data]


def append_entries(entries: list[LogEntry]) -> None:
    with _lock:
        existing: list[dict] = []
        if LOG_PATH.exists():
            existing = json.loads(LOG_PATH.read_text())
        existing_codes = {e["grn_code"] for e in existing}
        for entry in entries:
            if entry.grn_code not in existing_codes:
                existing.append(entry.model_dump())
        LOG_PATH.write_text(json.dumps(existing, indent=2))


def mark_pdf_attached(grn_code: str) -> bool:
    with _lock:
        if not LOG_PATH.exists():
            return False
        data = json.loads(LOG_PATH.read_text())
        found = False
        for e in data:
            if e["grn_code"] == grn_code:
                e["pdf_attached"] = True
                found = True
        if found:
            LOG_PATH.write_text(json.dumps(data, indent=2))
        return found
