"""Turns written copy into a designed, email-client-safe HTML message.

Rendered in the Eldian Core brand: near-black page, charcoal glass panel, parrot
green accents, HUD/terminal labels. A calm "diagnostic readout" poster version of
the website's dark/green identity — no motion, because email clients strip
animation and JS.

Every visible detail is merged per recipient from the CRM (business, city,
industry, issue count, issue previews) plus the company profile, so each send is
individually specific rather than a mail-merge blast.

IMPORTANT: the issue PREVIEWS are short titles only. The measurements, tag names
and fixes stay private — that detail is what the reply is for. See
agent3_routes._CONSEQUENCE.

Email HTML rules followed here (Gmail/Outlook strip most modern CSS):
  - tables for layout, inline styles only, no <style> blocks, no flex/grid
  - no external CSS or JS, web-safe font fallbacks, max ~600px wide
  - inline SVG line icons (Feather/Lucide style), never emoji
"""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

# Brand wordmark shipped with the app. Embedded as a CID attachment (see
# mailer.send_email) because Gmail and Outlook block base64 data: URIs, and a
# remote URL is blocked until the reader clicks "show images".
LOGO_FILE = Path(__file__).resolve().parents[2] / "wordmark.png"
LOGO_CID = "eldiancore-wordmark"

# ---- Eldian Core brand tokens ---------------------------------------------
PAGE_BG = "#0A0B0D"        # near-black outer background
PANEL_BG = "#1A1B1E"       # charcoal content card
PANEL_BG_ALT = "#151619"   # deeper inset block (scan card)
GREEN = "#8FE000"          # parrot green accent
GREEN_DIM = "#5f9600"      # darker green for gradient fades
BORDER = "rgba(143,224,0,0.18)"   # subtle green glow border (glass-panel look)
TEXT = "#F5F5F5"           # off-white headings
MUTED = "#A0A3A8"          # muted gray body copy
MUTED_DIM = "#6E7278"      # dimmer gray for footer/legal

HEAD_FONT = "'Space Grotesk','Poppins',Arial,Helvetica,sans-serif"
BODY_FONT = "'Inter','General Sans',Arial,Helvetica,sans-serif"
MONO_FONT = "'Courier New',Courier,monospace"


def _esc(value) -> str:
    return html_lib.escape(str(value or ""), quote=True)


# ---- icons ----------------------------------------------------------------
# Gmail blocks SVG and data: URIs entirely, so icons must be text glyphs styled
# with CSS. These are widely-supported Unicode symbols, not emoji — they render
# in the accent colour and never show as a broken image.
def _icon(glyph: str, size: int = 14, colour: str = GREEN) -> str:
    return (f'<span style="display:inline-block;color:{colour};font-size:{size}px;'
            f'line-height:1;vertical-align:middle;">{glyph}</span>')


ICON_ALERT = _icon("&#9888;", size=26)     # warning triangle
ICON_FLAG = _icon("&#9656;", size=12)      # small solid arrow, used as a bullet
ICON_MAIL = _icon("&#9993;", size=14)      # envelope
ICON_CHAT = _icon("&#9990;", size=14)      # phone/WhatsApp
ICON_GLOBE = _icon("&#9673;", size=13)     # globe-ish circle
ICON_PHONE = _icon("&#9742;", size=14)     # telephone


def _paragraphs(body: str) -> list[str]:
    """Split the written copy into paragraphs, dropping any sign-off block —
    the signature is rendered from real company data instead."""
    text = (body or "").strip()
    cut = re.split(r"\n\s*(?:best regards|kind regards|warm regards|sincerely|thanks|thank you)\s*,?\s*\n",
                   text, maxsplit=1, flags=re.I)
    return [p.strip() for p in cut[0].split("\n\n") if p.strip()]


def _highlight_last_word(text: str) -> str:
    """Accent the final word of the headline in parrot green — the site's
    'one accent word' headline treatment."""
    words = _esc(text).split()
    if len(words) < 2:
        return _esc(text)
    return " ".join(words[:-1]) + f' <span style="color:{GREEN};">{words[-1]}</span>'


def _divider(pad: str = "0 34px") -> str:
    """Thin green rule between sections. Flat colour rather than a gradient —
    gradients are a Gmail "Promotions" signal and several clients drop them."""
    return (
        f'<tr><td style="padding:{pad};">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td style="height:1px;line-height:1px;font-size:0;background:{GREEN_DIM};">&nbsp;</td>'
        f'</tr></table></td></tr>'
    )


def _greeting_name(raw: str) -> str:
    """Tidy a scraped business name so it reads naturally in a greeting.

    Listings are messy: emoji, ALL CAPS, branch suffixes and trailing legal
    forms. "SHAHZAIB TRADERS | Lahore Branch" -> "Shahzaib Traders".
    """
    name = str(raw or "").strip()
    # Drop anything after a separator (branch/location suffixes).
    name = re.split(r"\s*[|–—\-]\s{1,}|\s*[,/]\s*", name)[0].strip()
    # Strip emoji / symbols, keep letters, digits, spaces and & . '
    name = re.sub(r"[^\w\s&.'-]", " ", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip(" .-'&")
    # Shouty listings read as spam; title-case them but keep real acronyms.
    if name and (name.isupper() or name.islower()):
        name = " ".join(w if (len(w) <= 3 and w.isupper()) else w.capitalize()
                        for w in name.split())
    # Keep it short enough for a greeting line.
    words = name.split()
    if len(words) > 4:
        name = " ".join(words[:4])
    return name.strip()


def _first_name(lead: dict) -> str:
    """Real contact first name only — never invent one. Empty means the greeting
    falls back to a natural 'Hi there', which is honest and still reads human."""
    raw = (lead.get("contact_first_name") or lead.get("contact_name") or "").strip()
    if not raw:
        return ""
    first = raw.split()[0]
    return first if first.isalpha() and len(first) > 1 else ""


def render_email_html(body: str, lead: dict, profile: dict) -> str:
    """Build the designed HTML version of one outreach email.

    Every {{merge field}} in the brief maps to a value pulled from the lead
    document or the company profile — nothing about the recipient is hardcoded.
    """
    # ---- merge fields: sender (company profile) ----
    company = _esc(profile.get("company_name") or "")
    website = (profile.get("website") or "").strip()
    sender = _esc(profile.get("sender_name") or "")
    title = _esc(profile.get("sender_title") or "")
    email_addr = (profile.get("contact_email") or "").strip()
    whatsapp = (profile.get("whatsapp") or "").strip()
    phone = (profile.get("phone") or "").strip()
    tagline = _esc(profile.get("tagline") or "")
    photo_url = (profile.get("sender_photo_url") or "").strip()
    address = _esc(profile.get("address") or "")
    services = profile.get("services_offered") or []
    services_line = _esc(" · ".join(services[:4])) if services else ""

    # ---- merge fields: recipient (lead) ----
    business = _esc(lead.get("business_name") or "your business")
    city = _esc(lead.get("city") or "")
    industry = _esc(lead.get("niche") or "")
    first_name = _esc(_first_name(lead))
    findings = (lead.get("site_audit") or {}).get("findings") or []
    issue_count = len(findings)
    serious = sum(1 for f in findings if f.get("severity") in ("critical", "high"))

    cta_link = f"mailto:{email_addr}?subject=Send%20me%20the%20details" if email_addr else "#"

    # ---- logo mark + wordmark (top-left per spec) ----
    logo_url = (profile.get("logo_url") or "").strip()
    # The wordmark image already contains the company name, so when it is used
    # the text wordmark beside it is suppressed (see `wordmark_is_image`).
    #
    # A hosted logo_url is PREFERRED: Gmail blocks data: URIs, and Brevo's HTTPS
    # API cannot carry cid: attachments (those only work over SMTP). A public
    # https:// URL is the only form that renders in every client and transport.
    wordmark_is_image = bool(logo_url) or LOGO_FILE.exists()
    if logo_url:
        mark = (f'<img src="{_esc(logo_url)}" height="34" alt="{company}" '
                f'style="display:block;height:34px;border:0;">')
    elif LOGO_FILE.exists():
        # SMTP-only fallback; over Brevo this is swapped for a text wordmark.
        mark = (f'<img src="cid:{LOGO_CID}" height="34" alt="{company}" '
                f'style="display:block;height:34px;border:0;">')
    elif False:
        mark = (f'<img src="{_esc(logo_url)}" width="40" height="40" alt="{company}" '
                f'style="display:block;width:40px;height:40px;border-radius:10px;border:0;">')
    else:
        initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", company or sender or "?")[:2]).upper() or "EC"
        mark = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
                f'<td align="center" valign="middle" style="width:40px;height:40px;border-radius:10px;'
                f'background:{GREEN};font-family:{HEAD_FONT};font-size:16px;font-weight:bold;'
                f'color:{PAGE_BG};letter-spacing:.5px;">{_esc(initials)}</td></tr></table>')

    # ---- greeting + copy ----
    # Prefer a real contact name; otherwise greet the BUSINESS by name. Never
    # invent a personal name — a wrong one destroys trust instantly.
    clean_name = _greeting_name(lead.get("business_name") or "")
    if first_name:
        greeting = f"Hi {first_name},"
    elif clean_name:
        greeting = f"Hi {clean_name} team,"
    else:
        greeting = "Hi there,"
    para_list = _paragraphs(body)
    headline_html = ""
    rest_html = ""
    if para_list:
        headline_html = (
            f'<p style="margin:0 0 16px;font-family:{HEAD_FONT};font-size:22px;line-height:1.38;'
            f'font-weight:bold;color:{TEXT};letter-spacing:-.5px;">'
            f'{_highlight_last_word(para_list[0])}</p>'
        )
        rest_html = "".join(
            f'<p style="margin:0 0 15px;font-family:{BODY_FONT};font-size:15px;line-height:1.75;'
            f'color:{MUTED};">{_esc(t)}</p>'
            for t in para_list[1:]
        )

    # ---- SITE SCAN card: the visual centerpiece ----
    findings_block = ""
    if findings:
        shown = issue_count if not serious else serious
        # 2-3 short titles only: enough to prove specificity, not enough to fix.
        previews = "".join(
            f'<tr><td valign="top" style="padding:0 9px 9px 0;line-height:1;">{ICON_FLAG}</td>'
            f'<td style="padding:0 0 9px;font-family:{BODY_FONT};font-size:13.5px;line-height:1.5;'
            f'color:{TEXT};">{_esc(f.get("title", ""))}</td></tr>'
            for f in findings[:3]
        )
        more = issue_count - min(3, issue_count)
        more_line = (f'<p style="margin:10px 0 0;font-family:{MONO_FONT};font-size:11px;'
                     f'letter-spacing:1px;text-transform:uppercase;color:{MUTED_DIM};">'
                     f'+ {more} more in the full breakdown</p>') if more > 0 else ""

        findings_block = (
            f'<tr><td style="padding:8px 34px 26px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="background:{PANEL_BG_ALT};border:1px solid {BORDER};border-radius:12px;">'
            f'<tr><td style="padding:22px 24px;">'
            f'<p style="margin:0 0 16px;font-family:{MONO_FONT};font-size:10.5px;letter-spacing:2px;'
            f'text-transform:uppercase;color:{GREEN};">SITE SCAN // {business[:28]}</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
            f'<td valign="middle" style="width:36px;line-height:1;">{ICON_ALERT}</td>'
            f'<td valign="middle" style="width:54px;font-family:{HEAD_FONT};font-size:44px;'
            f'font-weight:bold;color:{GREEN};line-height:1;">{shown}</td>'
            f'<td valign="middle" style="padding-left:8px;font-family:{HEAD_FONT};font-size:16px;'
            f'font-weight:bold;color:{TEXT};line-height:1.35;">'
            f'issue{"s" if shown != 1 else ""} we&rsquo;d flag as urgent</td>'
            f'</tr></table>'
            f'<p style="margin:16px 0 14px;font-family:{BODY_FONT};font-size:13.5px;line-height:1.65;'
            f'color:{MUTED};">These are quietly costing you enquiries. I&rsquo;m happy to share the '
            f'full breakdown &mdash; free, no obligation.</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">'
            f'{previews}</table>{more_line}'
            f'</td></tr></table></td></tr>'
        )

    # ---- CTA ----
    # A large graphical button is one of Gmail's strongest "Promotions" signals.
    # A plain accent-coloured text link reads as a personal email while keeping
    # the same action, so this lands in Primary far more often.
    # Solid green pill button, per the brand spec. Note: a large graphical CTA
    # is one of Gmail's "Promotions" signals, so the plain-text reply line below
    # it is kept as the low-friction primary action.
    cta_block = (
        f'<tr><td align="center" style="padding:6px 34px 6px;">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td align="center" style="background:{GREEN};border-radius:999px;">'
        f'<a href="{_esc(cta_link)}" style="display:inline-block;padding:14px 36px;'
        f'font-family:{HEAD_FONT};font-size:15px;font-weight:bold;color:{PAGE_BG};'
        f'text-decoration:none;letter-spacing:.2px;">Show me what you found</a>'
        f'</td></tr></table>'
        f'<p style="margin:11px 0 0;font-family:{BODY_FONT};font-size:12.5px;color:{MUTED_DIM};">'
        f'or just hit reply &mdash; takes ten seconds</p>'
        f'</td></tr>'
    )

    # A quiet line naming what else we build. The email is about THEIR website
    # problem, so this stays small and secondary — it exists so a reader who
    # needs a CRM/ERP rather than a site knows to ask, without turning the
    # message into a services brochure.
    services_strip = ''
    if services:
        listed = ' &middot; '.join(_esc(x) for x in services[:5])
        services_strip = (
            f'<tr><td style="padding:0 34px 18px;">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
            f'style="background:{PANEL_BG_ALT};border-left:2px solid {GREEN};border-radius:6px;">'
            f'<tr><td style="padding:13px 16px;">'
            f'<p style="margin:0 0 5px;font-family:{MONO_FONT};font-size:9.5px;letter-spacing:1.6px;'
            f'text-transform:uppercase;color:{GREEN};">Also built in-house</p>'
            f'<p style="margin:0;font-family:{BODY_FONT};font-size:12.5px;line-height:1.6;color:{MUTED};">'
            f'{listed}. If any of that is on your list, just say so when you reply.</p>'
            f'</td></tr></table></td></tr>'
        )

    # ---- signature: the trust-building close ----
    if photo_url:
        avatar = (f'<img src="{_esc(photo_url)}" width="46" height="46" alt="{sender}" '
                  f'style="display:block;width:46px;height:46px;border-radius:23px;'
                  f'border:2px solid {GREEN};">')
    else:
        si = "".join(w[0] for w in re.findall(r"[A-Za-z]+", sender or company or "?")[:2]).upper() or "?"
        avatar = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
                  f'<td align="center" valign="middle" style="width:46px;height:46px;border-radius:23px;'
                  f'background:{PANEL_BG_ALT};border:2px solid {GREEN};font-family:{HEAD_FONT};'
                  f'font-size:15px;font-weight:bold;color:{GREEN};">{_esc(si)}</td></tr></table>')

    contact_cells = []
    if email_addr:
        contact_cells.append(f'<a href="mailto:{_esc(email_addr)}" style="color:{GREEN};text-decoration:none;">'
                             f'{ICON_MAIL} <span style="color:{MUTED};">{_esc(email_addr)}</span></a>')
    if whatsapp:
        wa = re.sub(r"[^\d+]", "", whatsapp).lstrip("+")
        contact_cells.append(f'<a href="https://wa.me/{_esc(wa)}" style="color:{GREEN};text-decoration:none;">'
                             f'{ICON_CHAT} <span style="color:{MUTED};">WhatsApp</span></a>')
    if phone:
        contact_cells.append(f'<span>{ICON_PHONE} <span style="color:{MUTED};">{_esc(phone)}</span></span>')
    if website:
        url = website if "://" in website else f"https://{website}"
        contact_cells.append(f'<a href="{_esc(url)}" style="color:{GREEN};text-decoration:none;">'
                             f'{ICON_GLOBE} <span style="color:{MUTED};">{_esc(website)}</span></a>')
    contact_line = ' &nbsp;&nbsp; '.join(contact_cells)

    signer = sender or company or "The team"
    signer_sub = " · ".join(x for x in (title, company) if x)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(profile.get('company_name') or 'Message')}</title></head>
<body style="margin:0;padding:0;background:{PAGE_BG};">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
  style="background:{PAGE_BG};padding:34px 12px;">
<tr><td align="center">

<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
  style="max-width:600px;width:100%;background:{PANEL_BG};border:1px solid {BORDER};
  border-radius:16px;overflow:hidden;">

  <!-- header: logo mark + wordmark, tagline in mono green -->
  <tr><td style="background:{PANEL_BG};border-top:3px solid {GREEN};padding:26px 34px 22px;">
    {f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td>{mark}</td></tr>
      {f'<tr><td style="padding-top:10px;"><p style="margin:0;font-family:{MONO_FONT};font-size:10px;letter-spacing:1.8px;text-transform:uppercase;color:{GREEN};">{tagline}</p></td></tr>' if tagline else ''}
    </table>''' if wordmark_is_image else f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
      <td valign="middle">{mark}</td>
      <td valign="middle" style="padding-left:13px;">
        <p style="margin:0;font-family:{HEAD_FONT};font-size:19px;font-weight:bold;color:{TEXT};letter-spacing:-.3px;">{company}</p>
        {f'<p style="margin:4px 0 0;font-family:{MONO_FONT};font-size:10px;letter-spacing:1.8px;text-transform:uppercase;color:{GREEN};">{tagline}</p>' if tagline else ''}
      </td>
    </tr></table>'''}
  </td></tr>

  {_divider("0 34px 24px")}

  <!-- opening: greeting + specific observation -->
  <tr><td style="padding:0 34px 6px;">
    <p style="margin:0 0 14px;font-family:{BODY_FONT};font-size:15px;color:{MUTED};">{_esc(greeting)}</p>
    {headline_html}{rest_html}
  </td></tr>

  {findings_block}
  {cta_block}
  {services_strip}

  {_divider("22px 34px 0")}

  <!-- signature -->
  <tr><td style="padding:22px 34px 24px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
      <tr>
        <td valign="middle" style="width:48px;">{avatar}</td>
        <td valign="middle" style="padding-left:14px;">
          <p style="margin:0;font-family:{HEAD_FONT};font-size:15px;font-weight:bold;color:{TEXT};">{signer}</p>
          {f'<p style="margin:3px 0 0;font-family:{BODY_FONT};font-size:12.5px;color:{MUTED};">{signer_sub}</p>' if signer_sub else ''}
        </td>
      </tr>
      {f'<tr><td colspan="2" style="padding-top:14px;"><p style="margin:0;font-family:{BODY_FONT};font-size:12.5px;line-height:2;">{contact_line}</p></td></tr>' if contact_line else ''}
      <tr><td colspan="2" style="padding-top:12px;">
        <p style="margin:0;font-family:{BODY_FONT};font-size:12.5px;line-height:1.6;color:{MUTED};font-style:italic;">
          Happy to just talk it through &mdash; no pitch, no pressure.</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- footer -->
  <tr><td style="background:{PAGE_BG};padding:16px 34px;">
    {f'<p style="margin:0 0 6px;font-family:{MONO_FONT};font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:{MUTED_DIM};line-height:1.8;">{services_line}</p>' if services_line else ''}
    {f'<p style="margin:0 0 6px;font-family:{BODY_FONT};font-size:11px;color:{MUTED_DIM};">{address}</p>' if address else ''}
    <p style="margin:0;font-family:{BODY_FONT};font-size:11px;color:{MUTED_DIM};">
      Sent to {_esc(lead.get('email') or '')} &nbsp;·&nbsp;
      <a href="mailto:{_esc(email_addr)}?subject=Unsubscribe" style="color:{MUTED_DIM};text-decoration:underline;">Unsubscribe</a>
    </p>
  </td></tr>

</table>

</td></tr></table>
</body></html>"""
