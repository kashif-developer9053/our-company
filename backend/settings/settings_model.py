"""Settings data model. Secret values (keys/passwords) are stored ENCRYPTED and
never returned in full. Non-secret values (email addresses) may be shown."""

from __future__ import annotations

from pydantic import BaseModel, Field

# The keys the Settings UI manages. `secret` = mask entirely (passwords/keys);
# non-secret (email addresses) may be shown in full. `group` ties SMTP/IMAP
# fields together for their Test Connection buttons.
SUPPORTED_KEYS = [
    {"key_name": "claude_api_key", "label": "Claude API Key", "prefix": "sk-ant-", "secret": True, "group": "claude", "testable": True},
    {"key_name": "smtp_email", "label": "Sending Email (SMTP)", "prefix": "", "secret": False, "group": "smtp", "testable": False},
    {"key_name": "smtp_app_password", "label": "SMTP App Password", "prefix": "", "secret": True, "group": "smtp", "testable": False},
    {"key_name": "imap_email", "label": "Inbox Email (IMAP)", "prefix": "", "secret": False, "group": "imap", "testable": False},
    {"key_name": "imap_app_password", "label": "IMAP App Password", "prefix": "", "secret": True, "group": "imap", "testable": False},
    # Mail server overrides — leave blank for Gmail defaults, set for Hostinger/
    # Workspace/Zoho etc. (e.g. smtp.hostinger.com : 465, imap.hostinger.com : 993)
    # Brevo HTTPS API — used INSTEAD of SMTP when set. Works on networks where
    # the ISP blocks outbound SMTP ports (very common on home connections).
    {"key_name": "brevo_api_key", "label": "Brevo API Key (sends over HTTPS)", "prefix": "xkeysib-", "secret": True, "group": "smtp", "testable": True},
    {"key_name": "sender_display_name", "label": "Sender Display Name", "prefix": "", "secret": False, "group": "smtp", "testable": False},
    {"key_name": "smtp_host", "label": "SMTP Host", "prefix": "", "secret": False, "group": "smtp", "testable": False},
    {"key_name": "smtp_port", "label": "SMTP Port", "prefix": "", "secret": False, "group": "smtp", "testable": False},
    {"key_name": "imap_host", "label": "IMAP Host", "prefix": "", "secret": False, "group": "imap", "testable": False},
    {"key_name": "imap_port", "label": "IMAP Port", "prefix": "", "secret": False, "group": "imap", "testable": False},
]

SUPPORTED_KEY_NAMES = [k["key_name"] for k in SUPPORTED_KEYS]


class SettingWrite(BaseModel):
    key_name: str
    value: str = Field(min_length=1)


class ConfigWrite(BaseModel):
    daily_send_cap: int = Field(ge=1, le=500)
