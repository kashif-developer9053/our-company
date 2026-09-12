"""Email transport for Agent 3 — SMTP sending + IMAP reply reading (Gmail).

Credentials come from the encrypted Settings store (decrypted in-memory only).
Everything returns a clean result dict; nothing raises. If credentials are
missing, callers get a clear "no_creds" result so Agent 3 can show an error
instead of attempting to connect.
"""

from __future__ import annotations

import email
import imaplib
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr

from shared.logger import get_logger
from shared.settings_store import get_setting_value

log = get_logger("agent3.mailer")

# Defaults are Gmail; any provider (Hostinger, Workspace, Zoho…) can be used by
# setting smtp_host / smtp_port / imap_host / imap_port in Settings.
DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT = "smtp.gmail.com", 587
DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT = "imap.gmail.com", 993


def _mail_host(key: str, default: str) -> str:
    return (get_setting_value(key) or "").strip() or default


def _mail_port(key: str, default: int) -> int:
    raw = (get_setting_value(key) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def smtp_server() -> tuple[str, int]:
    return _mail_host("smtp_host", DEFAULT_SMTP_HOST), _mail_port("smtp_port", DEFAULT_SMTP_PORT)


def imap_server() -> tuple[str, int]:
    return _mail_host("imap_host", DEFAULT_IMAP_HOST), _mail_port("imap_port", DEFAULT_IMAP_PORT)


# ---- send-safety gate ------------------------------------------------------
# The model sometimes leaks its own planning, template placeholders, or gets cut
# off mid-sentence. None of that may ever reach a real prospect.
_META_ANALYSIS_PATTERNS = (
    r"^\s*(?:we|i)\s+(?:need|must|should)\s+to\s+(?:write|produce|create|select|count|ensure)\b",
    r"\bthe user (?:said|asked|didn't|did not|earlier)\b",
    r"\b(?:original|earlier|system|developer|role) instruction\b",
    r"\bword count requirement\b",
    r"\bmust start with ['\"]?subject\s*:",
    r"\bwe should aim (?:for|at)\b",
    r"<\/?think>",
    # Announcing what the message IS. A real person never opens by telling
    # you they are cold-emailing you; it reads as automated and kills the reply.
    r"\bthis is a cold (?:email|outreach|message)\b",
    r"\bi am (?:sending|writing) (?:you )?a cold\b",
    r"\bas (?:an? )?(?:ai|language model|assistant)\b",
    r"\b(?:a|this) business like theirs\b",   # third person leaking from the brief
    # The model narrating its own process — this reached a real draft once.
    r"\bsystem prompt\b",
    r"\bcompany profile\b",
    r"\buser angle\b",
    r"\bconflict resolution\b",
    r"\bcrucial check\b",
    r"\bpersona\b",
    r"\baudit findings:\b",
    r"^\s*\*?\s*\*?(?:wait|actually|looking closer|looking at the prompt|note:)\b",
    r"^\s*\*\s*\*?(?:subject|opening|the gap|the pitch|the cta|sign-off)\*?:",
    r"\b(?:i|we) need to (?:reconcile|bridge|stick to|focus on)\b",
    r"\bchecked\.\s*$",
    r"\b\d{2,3}-\d{2,3} words\b",
    r"\bcta\b",
    r"\bsoft cta\b",
    r"\bbanned (?:opening )?phrases?\b",
    r"\ball-caps\b",
)

_TEMPLATE_LEAK_PATTERNS = (
    r"\[[^\]\r\n]{1,120}\]",          # [Your Name]
    r"\{\{[^}\r\n]{1,120}\}\}",       # {{company}}
    r"^\s*(?:blank line\.?|body:|email body:|draft:|email:)\s*$",
)


def _body_looks_complete(body: str) -> bool:
    """True unless the text was clearly cut off mid-sentence.

    Note: the designer renders the signature separately, so a body legitimately
    ends right after the last sentence — sometimes on a question or a closing
    line with no full stop. Only obvious truncation should fail.
    """
    lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
    if not lines:
        return False
    last = lines[-1]
    if last.endswith((".", "!", "?", ":", '"', "”")):
        return True
    signoff = re.compile(r"^(?:best|kind|warm) regards,?$|^sincerely,?$|^thanks,?$|^cheers,?$", re.I)
    if any(signoff.fullmatch(line) for line in lines[-4:]):
        return True
    # A short trailing fragment (a stripped name/title) is fine; a long unfinished
    # sentence is not. "Kashif Rehman" = complete-ish; 12+ words = truncated.
    return len(last.split()) <= 6


def outbound_content_issues(subject: str, body: str) -> list[str]:
    """Reject malformed or model-internal content BEFORE it reaches SMTP.
    Returns a list of human-readable problems ([] means safe to send)."""
    issues: list[str] = []
    subject = str(subject or "").strip()
    body = str(body or "").strip()
    combined = f"{subject}\n{body}"
    if not subject:
        issues.append("subject is empty")
    if "\r" in subject or "\n" in subject:
        issues.append("subject contains a line break")
    if not body:
        issues.append("body is empty")
    if any(re.search(p, combined, re.I | re.M) for p in _META_ANALYSIS_PATTERNS):
        issues.append("contains model planning or instruction commentary")
    if any(re.search(p, combined, re.I | re.M) for p in _TEMPLATE_LEAK_PATTERNS):
        issues.append("contains a placeholder or formatting label")
    if body and not _body_looks_complete(body):
        issues.append("body appears incomplete or cut off")
    return issues


def _smtp_connect(timeout: int = 45):
    """Open an SMTP connection, handling both common styles:
    port 465 = implicit SSL (Hostinger default), anything else = STARTTLS."""
    host, port = smtp_server()
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=timeout)
    return smtplib.SMTP(host, port, timeout=timeout)


def _start_tls(s) -> None:
    """Upgrade to TLS unless the socket is already SSL (port 465)."""
    if isinstance(s, smtplib.SMTP_SSL):
        return
    s.starttls()


def _smtp_creds() -> tuple[str | None, str | None]:
    return get_setting_value("smtp_email"), get_setting_value("smtp_app_password")


def _imap_creds() -> tuple[str | None, str | None]:
    return get_setting_value("imap_email"), get_setting_value("imap_app_password")


# ---- Test Connection -------------------------------------------------------
def test_smtp() -> dict:
    # Brevo takes priority when configured — verify that instead of SMTP.
    brevo = (get_setting_value("brevo_api_key") or "").strip()
    if brevo:
        try:
            import httpx

            r = httpx.get("https://api.brevo.com/v3/account", timeout=30,
                          headers={"api-key": brevo})
            if r.status_code == 200:
                d = r.json()
                plan = ""
                try:
                    p = (d.get("plan") or [{}])[0]
                    plan = f" · {p.get('type', '')} {p.get('credits', '')}".rstrip()
                except Exception:  # noqa: BLE001
                    pass
                sender = (get_setting_value("smtp_email") or "").strip()
                # A connected account is useless if the from-address isn't verified.
                ok_sender, why = _brevo_sender_ok(sender, brevo)
                if not ok_sender:
                    return {"ok": False, "message": f"Brevo is connected{plan}, but {why}"}
                return {"ok": True, "message": f"Brevo (HTTPS) connected{plan} — sending as {sender}. "
                                               f"Bypasses SMTP port blocks."}
            if r.status_code in (401, 403):
                return {"ok": False, "message": "Brevo rejected the API key — check it in Settings."}
            return {"ok": False, "message": f"Brevo error {r.status_code}: {r.text[:150]}"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"Brevo connection failed: {exc}"}

    user, pw = _smtp_creds()
    if not user or not pw:
        return {"ok": False, "message": "No SMTP credentials configured — add them in Settings."}
    try:
        with _smtp_connect(timeout=30) as s:
            s.ehlo()
            _start_tls(s)
            s.login(user, pw)
        return {"ok": True, "message": f"SMTP connection + auth OK for {user}."}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "message": "SMTP auth failed — check the email + app password."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"SMTP connection failed: {exc}"}


# Phrases a mail server uses when the CREDENTIALS are genuinely rejected, as
# opposed to the many transient faults imaplib reports through the same class.
_AUTH_FAIL_MARKERS = (
    "authentication failed", "authenticationfailed", "invalid credentials",
    "login failed", "auth failed", "password", "not authenticated",
    "invalid user", "no login", "authorization failed",
)


def _is_auth_failure(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _AUTH_FAIL_MARKERS)


def test_imap() -> dict:
    user, pw = _imap_creds()
    if not user or not pw:
        return {"ok": False, "message": "No IMAP credentials configured — add them in Settings."}
    try:
        _ih,_ip = imap_server()
        m = imaplib.IMAP4_SSL(_ih, _ip)
        m.login(user, pw)
        typ, folders = m.list()
        m.logout()
        return {"ok": True, "message": f"IMAP connection + auth OK ({len(folders or [])} folders)."}
    except imaplib.IMAP4.error as exc:
        if _is_auth_failure(str(exc)):
            return {"ok": False,
                    "message": f"IMAP sign-in rejected — check the email + password. ({exc})"}
        return {"ok": False,
                "message": f"IMAP server error (usually temporary, try again): {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"IMAP connection failed: {exc}"}


def _attach_logo(msg: EmailMessage) -> None:
    """Embed the brand wordmark as an inline CID image on the HTML part.

    Gmail/Outlook block base64 data: URIs and hide remote images until the reader
    opts in; a cid: attachment renders immediately. Never raises — a missing logo
    must not stop a send.
    """
    try:
        from .email_designer import LOGO_CID, LOGO_FILE

        if not LOGO_FILE.exists():
            return
        html_part = None
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html_part = part
        if html_part is None or f"cid:{LOGO_CID}" not in html_part.get_content():
            return
        html_part.add_related(LOGO_FILE.read_bytes(), maintype="image", subtype="png",
                              cid=f"<{LOGO_CID}>", filename=LOGO_FILE.name)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not embed logo (isolated): %s", exc)


# ---- Sending ---------------------------------------------------------------
_brevo_sender_cache: dict[str, tuple[float, bool, str]] = {}


def _brevo_sender_ok(sender: str, key: str) -> tuple[bool, str]:
    """Confirm the from-address is a verified Brevo sender (cached 5 min).

    Without this a whole batch can be marked 'sent' while Brevo quietly rejects
    every message for an unverified sender.
    """
    import time

    import httpx

    hit = _brevo_sender_cache.get(sender)
    if hit and time.time() - hit[0] < 300:
        return hit[1], hit[2]
    try:
        r = httpx.get("https://api.brevo.com/v3/senders", headers={"api-key": key}, timeout=25)
        if r.status_code != 200:
            return True, ""   # can't verify — don't block the send
        emails = [(s.get("email") or "").lower() for s in r.json().get("senders", []) if s.get("active")]
        ok = sender.lower() in emails
        why = "" if ok else (
            f"'{sender}' is not a verified sender in Brevo, so Brevo will reject the message. "
            f"Add and confirm it at Brevo → Senders & Domains. "
            f"Currently verified: {', '.join(emails) or 'none'}.")
        _brevo_sender_cache[sender] = (time.time(), ok, why)
        return ok, why
    except Exception:  # noqa: BLE001 - never block a send on a check failure
        return True, ""


def _brevo_send(to_addr: str, subject: str, body: str, html: str) -> dict:
    """Send via Brevo's HTTPS API instead of SMTP.

    Many consumer ISPs block outbound SMTP ports (25/465/587) to curb spam, which
    makes normal sending impossible from a home connection. This goes over HTTPS
    (443), which cannot be blocked without breaking the whole internet.
    """
    import base64

    import httpx

    key = (get_setting_value("brevo_api_key") or "").strip()
    sender = (get_setting_value("smtp_email") or "").strip()
    if not sender:
        return {"ok": False, "error": "Set your sending email address in Settings.", "kind": "no_creds"}

    # Brevo returns 201 "accepted" even for an UNVERIFIED sender, then silently
    # rejects the message — so the app would wrongly report success. Check first.
    ok, why = _brevo_sender_ok(sender, key)
    if not ok:
        return {"ok": False, "error": why, "kind": "sender_unverified"}

    payload: dict = {
        "sender": {"email": sender, "name": (get_setting_value("sender_display_name") or "").strip() or sender},
        "to": [{"email": to_addr}],
        "subject": subject,
        "textContent": body or " ",
    }
    if html:
        payload["htmlContent"] = html
        # Brevo's API cannot carry cid: attachments (SMTP-only), and Gmail blocks
        # data: URIs — so a cid: logo would render as a broken image. Replace it
        # with a styled text wordmark unless a hosted logo URL is configured.
        try:
            from .email_designer import GREEN, HEAD_FONT, LOGO_CID

            if f"cid:{LOGO_CID}" in html:
                name = (get_setting_value("sender_display_name") or "").strip()
                from shared import company_profile

                brand = (company_profile.get_profile().get("company_name") or name or "").strip()
                wordmark = (f'<span style="font-family:{HEAD_FONT};font-size:21px;font-weight:bold;'
                            f'color:{GREEN};letter-spacing:-.4px;">{brand}</span>')
                payload["htmlContent"] = re.sub(
                    r'<img[^>]*src="cid:' + re.escape(LOGO_CID) + r'"[^>]*>', wordmark, html)
        except Exception:  # noqa: BLE001
            pass
    try:
        r = httpx.post("https://api.brevo.com/v3/smtp/email", timeout=45,
                       headers={"api-key": key, "content-type": "application/json"},
                       json=payload)
        if r.status_code in (200, 201, 202):
            return {"ok": True, "via": "brevo"}
        if r.status_code in (401, 403):
            return {"ok": False, "error": "Brevo rejected the API key.", "kind": "smtp_auth"}
        detail = r.text[:200]
        return {"ok": False, "error": f"Brevo error {r.status_code}: {detail}", "kind": "smtp_error"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Brevo send failed: {exc}", "kind": "smtp_error"}


def send_email(to_addr: str, subject: str, body: str, html: str = "") -> dict:
    """Send one email. Returns {ok} or {ok:False, error, kind}.

    Uses the Brevo HTTPS API when a key is configured (works even where the ISP
    blocks SMTP ports); otherwise falls back to direct SMTP. When `html` is
    supplied the message is multipart/alternative — plain text as the fallback.
    """
    if not to_addr:
        return {"ok": False, "error": "Lead has no email address.", "kind": "no_recipient"}
    if (get_setting_value("brevo_api_key") or "").strip():
        return _brevo_send(to_addr, subject, body, html)

    user, pw = _smtp_creds()
    if not user or not pw:
        return {"ok": False, "error": "No email credentials configured — add them in Settings.", "kind": "no_creds"}
    if not to_addr:
        return {"ok": False, "error": "Lead has no email address.", "kind": "no_recipient"}
    try:
        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
            _attach_logo(msg)
        with _smtp_connect(timeout=20) as s:
            s.ehlo()
            _start_tls(s)
            s.login(user, pw)
            s.send_message(msg)
        return {"ok": True}
    except smtplib.SMTPAuthenticationError:
        return {"ok": False, "error": "SMTP auth failed — check the email + app password.", "kind": "smtp_auth"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"SMTP send failed: {exc}", "kind": "smtp_error"}


# ---- Reading replies -------------------------------------------------------
def _decode(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:  # noqa: BLE001
        return s or ""


def _plain_body(msg) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                    return part.get_payload(decode=True).decode(errors="replace")
            return ""
        return msg.get_payload(decode=True).decode(errors="replace")
    except Exception:  # noqa: BLE001
        return ""


def fetch_replies(since_days: int = 14) -> dict:
    """Fetch recent inbox messages. Returns {ok, replies:[{from_email, subject,
    body, received_at, message_id}]} or {ok:False, error, kind}."""
    user, pw = _imap_creds()
    if not user or not pw:
        return {"ok": False, "error": "No email credentials configured — add them in Settings.", "kind": "no_creds", "replies": []}
    replies = []
    try:
        _ih,_ip = imap_server()
        m = imaplib.IMAP4_SSL(_ih, _ip)
        m.login(user, pw)
        m.select("INBOX")
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        typ, data = m.search(None, f'(SINCE {since})')
        ids = (data[0].split() if data and data[0] else [])[-60:]  # cap scan
        for num in ids:
            typ, raw = m.fetch(num, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            from_email = parseaddr(msg.get("From", ""))[1].lower()
            replies.append({
                "from_email": from_email,
                "subject": _decode(msg.get("Subject", "")),
                "body": _plain_body(msg).strip()[:4000],
                "received_at": msg.get("Date", ""),
                "message_id": msg.get("Message-ID", ""),
            })
        m.logout()
        return {"ok": True, "replies": replies}
    except imaplib.IMAP4.error as exc:
        # imaplib raises this one class for EVERYTHING: bad credentials, a
        # dropped connection, a server-side lookup failure. Reporting all of
        # them as an auth failure sent people off to regenerate a password that
        # was never wrong. Only treat it as auth when the server actually says so.
        text = str(exc)
        if _is_auth_failure(text):
            return {"ok": False, "error": f"IMAP sign-in rejected: {text}",
                    "kind": "imap_auth", "replies": []}
        return {"ok": False, "error": f"IMAP server error (usually temporary): {text}",
                "kind": "imap_temp", "replies": []}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not check inbox: {exc}", "kind": "imap_error", "replies": []}
