from __future__ import annotations

import base64
import logging
import re

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import settings
from grnpush.mapper import GmailAttachmentRef

logger = logging.getLogger("gmail_pdf")

TRUSTED_SENDER = "bangalorewh@evenflowbrands.com"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_INVOICE_PATTERN = re.compile(r"[A-Z]{2,}/\d{2}-\d{2}/\d+", re.IGNORECASE)
_PO_PATTERN = re.compile(r"PO[/\s\-]\w+", re.IGNORECASE)


def _get_service():
    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
    )
    return build("gmail", "v1", credentials=creds)


def _get_header(msg: dict, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _extract_body(msg: dict) -> str:
    payload = msg.get("payload", {})
    parts = payload.get("parts", [payload])
    text = ""
    for part in parts:
        if part.get("mimeType", "").startswith("text/"):
            data = part.get("body", {}).get("data", "")
            if data:
                try:
                    text += base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
                except Exception:
                    pass
    return text


def _score_message(msg: dict) -> int:
    subject = _get_header(msg, "Subject")
    body = _extract_body(msg)
    combined = subject + " " + body

    score = 0
    if "GRN DONE" in combined.upper():
        score += 10

    invoice_hits = len(_INVOICE_PATTERN.findall(body))
    po_hits = len(_PO_PATTERN.findall(body))
    if invoice_hits + po_hits >= 3:
        score += 5

    return score


def _find_pdf_part(msg: dict) -> tuple[str, str] | None:
    """Return (attachment_id, filename) for first PDF part, or None."""
    parts = msg.get("payload", {}).get("parts", [])
    for part in parts:
        filename = part.get("filename", "")
        mime = part.get("mimeType", "")
        attachment_id = part.get("body", {}).get("attachmentId")
        if attachment_id and (mime == "application/pdf" or filename.lower().endswith(".pdf")):
            return attachment_id, filename or f"attachment.pdf"
    return None


def fetch_grn_pdfs(grn_codes: list[str]) -> dict[str, GmailAttachmentRef]:
    """Search Gmail for each GRN code and return the best attachment reference per GRN."""
    if not settings.gmail_client_id or not settings.gmail_refresh_token:
        logger.warning("Gmail OAuth not configured — skipping PDF fetch")
        return {}

    service = _get_service()
    result: dict[str, GmailAttachmentRef] = {}

    for grn_code in grn_codes:
        try:
            q = f"from:{TRUSTED_SENDER} {grn_code} has:attachment"
            resp = service.users().messages().list(userId="me", q=q).execute()
            messages = resp.get("messages", [])
            if not messages:
                logger.info("No email found for GRN %s", grn_code)
                continue

            # Fetch full messages to score them
            candidates = []
            for m in messages:
                full = service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()
                candidates.append(full)

            # Sort: highest score first, then latest date
            candidates.sort(
                key=lambda m: (_score_message(m), int(m.get("internalDate", 0))),
                reverse=True,
            )

            for candidate in candidates:
                pdf_part = _find_pdf_part(candidate)
                if pdf_part:
                    attachment_id, filename = pdf_part
                    result[grn_code] = GmailAttachmentRef(
                        message_id=candidate["id"],
                        attachment_id=attachment_id,
                        filename=filename,
                    )
                    logger.info("GRN %s → email %s, file %s", grn_code, candidate["id"][:12], filename)
                    break
            else:
                logger.warning("GRN %s: emails found but no PDF attachment", grn_code)

        except Exception as exc:
            logger.warning("Gmail fetch failed for GRN %s: %s", grn_code, exc)

    return result


def download_attachment(message_id: str, attachment_id: str) -> bytes:
    """Download and decode a Gmail attachment."""
    service = _get_service()
    resp = service.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    data = resp.get("data", "")
    return base64.urlsafe_b64decode(data + "==")
