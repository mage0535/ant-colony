import imaplib
import smtplib
import email
import logging
import os
import re
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)


class EmailTool:
    def __init__(self):
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._smtp: Optional[smtplib.SMTP_SSL] = None

    # ------------------------------------------------------------------ #
    #  Config helpers
    # ------------------------------------------------------------------ #
    REQUIRED_VARS = ("EMAIL_IMAP_SERVER", "EMAIL_IMAP_PORT", "EMAIL_SMTP_SERVER",
                     "EMAIL_SMTP_PORT", "EMAIL_ADDRESS", "EMAIL_PASSWORD")

    @staticmethod
    def _getenv(key: str) -> str | None:
        return os.environ.get(key) or None

    def _configured(self) -> bool:
        return all(self._getenv(k) for k in self.REQUIRED_VARS)

    def _missing_config(self) -> str:
        missing = [k for k in self.REQUIRED_VARS if not self._getenv(k)]
        return f"Email not configured: missing env var(s) {', '.join(missing)}"

    # ------------------------------------------------------------------ #
    #  Lazy connections
    # ------------------------------------------------------------------ #
    def _ensure_imap(self):
        if self._imap is not None:
            return
        if not self._configured():
            raise RuntimeError(self._missing_config())
        host = self._getenv("EMAIL_IMAP_SERVER")
        port = int(self._getenv("EMAIL_IMAP_PORT"))
        logger.info("Connecting to IMAP %s:%s", host, port)
        self._imap = imaplib.IMAP4_SSL(host, port)
        self._imap.login(self._getenv("EMAIL_ADDRESS"), self._getenv("EMAIL_PASSWORD"))
        logger.info("IMAP connected")

    def _ensure_smtp(self):
        if self._smtp is not None:
            return
        if not self._configured():
            raise RuntimeError(self._missing_config())
        host = self._getenv("EMAIL_SMTP_SERVER")
        port = int(self._getenv("EMAIL_SMTP_PORT"))
        logger.info("Connecting to SMTP %s:%s", host, port)
        self._smtp = smtplib.SMTP_SSL(host, port)
        self._smtp.login(self._getenv("EMAIL_ADDRESS"), self._getenv("EMAIL_PASSWORD"))
        logger.info("SMTP connected")

    # ------------------------------------------------------------------ #
    #  Close connections
    # ------------------------------------------------------------------ #
    def close(self):
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
        if self._smtp:
            try:
                self._smtp.quit()
            except Exception:
                pass
            self._smtp = None

    # ------------------------------------------------------------------ #
    #  Email helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _decode_str(raw: bytes | str) -> str:
        parts = decode_header(raw)
        out = []
        for data, charset in parts:
            if isinstance(data, bytes):
                out.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                out.append(data)
        return "".join(out)

    @staticmethod
    def _get_body(msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                        return EmailTool._html_to_text(text)
            return "(no text body)"
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        ct = msg.get_content_type()
        if ct == "text/html":
            text = str(msg.get_payload())
            return EmailTool._html_to_text(text)
        return "(no text body)"

    @staticmethod
    def _html_to_text(html: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _extract_uid(data: bytes) -> str:
        return data.decode() if isinstance(data, bytes) else data

    # ------------------------------------------------------------------ #
    #  API
    # ------------------------------------------------------------------ #
    def send_email(self, to: str, subject: str, body: str, cc: Optional[str] = None) -> str:
        if not self._configured():
            return self._missing_config()
        try:
            self._ensure_smtp()
            msg = MIMEMultipart()
            sender = self._getenv("EMAIL_ADDRESS")
            msg["From"] = sender
            msg["To"] = to
            msg["Subject"] = subject
            if cc:
                msg["Cc"] = cc
            msg.attach(MIMEText(body, "plain", "utf-8"))

            recipients = [to]
            if cc:
                recipients.append(cc)
            self._smtp.sendmail(sender, recipients, msg.as_string())
            logger.info("Email sent to %s: %s", to, subject)
            return f"Email sent to {to}"
        except Exception as e:
            logger.warning("Failed to send email: %s", e)
            return f"Failed to send email: {e}"

    def list_inbox(self, limit: int = 10, folder: str = "INBOX") -> str:
        if not self._configured():
            return self._missing_config()
        try:
            self._ensure_imap()
            self._imap.select(folder)
            _, data = self._imap.search(None, "ALL")
            uids = data[0].split() if data[0] else []
            if not uids:
                return "Inbox is empty."

            recent = uids[-limit:]
            lines = []
            for uid in recent:
                _, msg_data = self._imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                raw = msg_data[0][1] if msg_data and msg_data[0] and len(msg_data[0]) > 1 else None
                if not raw:
                    continue
                hdr = email.message_from_bytes(raw)
                frm = self._decode_str(hdr.get("From", "(unknown)"))
                subj = self._decode_str(hdr.get("Subject", "(no subject)"))
                date = self._decode_str(hdr.get("Date", "(no date)"))
                uid_str = uid.decode() if isinstance(uid, bytes) else uid
                lines.append(f"[{uid_str}] From: {frm} | {subj} | {date}")

            return "\n".join(lines) if lines else "No messages found."
        except Exception as e:
            logger.warning("Failed to list inbox: %s", e)
            return f"Failed to list inbox: {e}"

    def search_emails(self, query: str, folder: str = "INBOX") -> str:
        if not self._configured():
            return self._missing_config()
        try:
            self._ensure_imap()
            self._imap.select(folder)

            criteria = f'(OR SUBJECT "{query}" FROM "{query}")'
            _, data = self._imap.search(None, criteria)
            uids = data[0].split() if data[0] else []
            if not uids:
                return f'No emails found matching "{query}".'

            lines = []
            for uid in uids[-30:]:
                _, msg_data = self._imap.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                raw = msg_data[0][1] if msg_data and msg_data[0] and len(msg_data[0]) > 1 else None
                if not raw:
                    continue
                hdr = email.message_from_bytes(raw)
                frm = self._decode_str(hdr.get("From", "(unknown)"))
                subj = self._decode_str(hdr.get("Subject", "(no subject)"))
                date = self._decode_str(hdr.get("Date", "(no date)"))
                uid_str = uid.decode() if isinstance(uid, bytes) else uid
                lines.append(f"[{uid_str}] From: {frm} | {subj} | {date}")

            return "\n".join(lines) if lines else "No matches."
        except Exception as e:
            logger.warning("Failed to search emails: %s", e)
            return f"Failed to search emails: {e}"

    def get_email(self, uid: str) -> str:
        if not self._configured():
            return self._missing_config()
        try:
            self._ensure_imap()
            self._imap.select("INBOX")
            uid_bytes = uid.encode() if isinstance(uid, str) else uid
            _, msg_data = self._imap.uid("fetch", uid_bytes, "(RFC822)")
            if not msg_data or not msg_data[0]:
                return f"Email UID {uid} not found."

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            frm = self._decode_str(msg.get("From", "(unknown)"))
            subj = self._decode_str(msg.get("Subject", "(no subject)"))
            date = self._decode_str(msg.get("Date", "(no date)"))
            body = self._get_body(msg)

            return f"From: {frm}\nSubject: {subj}\nDate: {date}\n\n{body}"
        except Exception as e:
            logger.warning("Failed to fetch email: %s", e)
            return f"Failed to fetch email: {e}"


# ------------------------------------------------------------------ #
#  Module-level convenience: one shared instance
# ------------------------------------------------------------------ #
_tool = EmailTool()

send_email = _tool.send_email
list_inbox = _tool.list_inbox
search_emails = _tool.search_emails
get_email = _tool.get_email
close = _tool.close
