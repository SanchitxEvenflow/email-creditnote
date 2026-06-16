import logging
import smtplib
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from backend.email.config import settings

logger = logging.getLogger("email")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

# Increased to 18 MB raw as requested
# (≈24 MB after base64 encoding — safely under Gmail's 25 MB limit)
MAX_ATTACHMENT_RAW_BYTES = 18 * 1024 * 1024


def _chunk_by_size(
    pdfs: list[tuple[str, bytes]],
    max_bytes: int = MAX_ATTACHMENT_RAW_BYTES,
) -> list[list[tuple[str, bytes]]]:
    """Split PDFs into chunks so total raw size stays under max_bytes."""
    chunks: list[list[tuple[str, bytes]]] = []
    current: list[tuple[str, bytes]] = []
    current_size = 0

    for name, data in pdfs:
        data_size = len(data)
        
        # If a single PDF is bigger than limit, send it alone
        if data_size > max_bytes:
            if current:
                chunks.append(current)
            chunks.append([(name, data)])
            current = []
            current_size = 0
            continue

        if current and current_size + data_size > max_bytes:
            chunks.append(current)
            current = [(name, data)]
            current_size = data_size
        else:
            current.append((name, data))
            current_size += data_size

    if current:
        chunks.append(current)

    return chunks


def _build_message(
    to_email: str,
    subject: str,
    pdfs: list[tuple[str, bytes]],
    body: str,
) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["From"] = settings.gmail_user
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    for name, data in pdfs:
        part = MIMEApplication(data, _subtype="pdf")
        part.add_header(
            "Content-Disposition", 
            "attachment", 
            filename=f"{name}.pdf"
        )
        msg.attach(part)

    return msg


def send_email_with_pdfs(
    to_email: str,
    subject: str,
    pdfs: list[tuple[str, bytes]],
    body: str = "Please find the credit note PDFs attached.",
) -> int:
    """
    Send credit note PDFs as attachments with proper chunking and timeouts.
    Returns the number of emails sent.
    """
    if not pdfs:
        logger.info("No PDFs to send")
        return 0

    chunks = _chunk_by_size(pdfs)
    total_emails = len(chunks)
    total_mb = sum(len(data) for _, data in pdfs) / (1024 * 1024)

    logger.info(
        "Sending %d PDF(s) (%.1f MB raw) in %d email(s) to %s",
        len(pdfs), total_mb, total_emails, to_email,
    )

    # High timeout because Gmail can be slow with many attachments
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=240) as smtp:
        logger.info("SMTP login as %s", settings.gmail_user)
        smtp.login(settings.gmail_user, settings.gmail_app_password)

        for i, chunk in enumerate(chunks, start=1):
            chunk_mb = sum(len(data) for _, data in chunk) / (1024 * 1024)
            chunk_subject = (
                subject if total_emails == 1 
                else f"{subject} (Part {i} of {total_emails})"
            )

            logger.info(
                "  Sending email %d/%d — %d attachment(s), %.1f MB",
                i, total_emails, len(chunk), chunk_mb,
            )

            msg = _build_message(to_email, chunk_subject, chunk, body)
            
            # Send the email
            smtp.sendmail(settings.gmail_user, to_email, msg.as_string())
            
            logger.info("  Email %d/%d sent successfully", i, total_emails)

            # Small delay between emails to reduce Gmail pressure
            if i < total_emails:
                time.sleep(4)

    logger.info("All %d email(s) delivered successfully to %s", total_emails, to_email)
    return total_emails