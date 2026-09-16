"""Separate what a prospect actually wrote from the mail they quoted back.

A four-word reply — "Thanks, No need any Service" — arrived buried under forty
lines of our own email, complete with tracking-link footnotes. That is unreadable
in the inbox, and it also poisons the classifier and the suggested reply, which
were being handed our own marketing copy as if the prospect had written it.

Mail clients mark quoted text in a handful of well-known ways, so this is
pattern work rather than anything clever:

  * "On <date>, <person> wrote:" then every following line prefixed with ">"
  * A separator line: "-----Original Message-----", "________________"
  * Outlook's header block: "From: ... Sent: ... To: ... Subject: ..."
  * A signature delimiter: a line of exactly "-- "

The rule throughout is to keep text when unsure. Hiding a real sentence is far
worse than leaving a quoted line visible, so every pattern must be unambiguous.
"""

from __future__ import annotations

import re

# "On Mon, 15 Sep 2026 at 05:20, Kashif Rehman <k@x.com> wrote:" and the many
# variations of it. Kept strict: it must end in "wrote:" or "sent:".
_ATTRIBUTION = re.compile(
    r"^\s*(?:On\b.{0,200}?|El\b.{0,200}?|Le\b.{0,200}?)\bwrote\s*:\s*$"
    r"|^\s*On\b.{0,200}?\bwrote\s*:\s*$"
    r"|^\s*.{0,120}\bwrote\s*:\s*$",
    re.I,
)

# Hard separators inserted by mail clients before quoted content.
_SEPARATORS = (
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*_{10,}\s*$"),
    re.compile(r"^\s*-{10,}\s*$"),
    re.compile(r"^\s*={10,}\s*$"),
    # Outlook drops a bare header block in place of an attribution line.
    re.compile(r"^\s*From:\s*.+$", re.I),
    re.compile(r"^\s*Sent:\s*.+$", re.I),
)

# "-- " on its own line is the RFC-recommended signature delimiter.
_SIG_DELIM = re.compile(r"^--\s*$")

# The link footnotes some clients append when they flatten anchors to text.
_LINK_FOOTER = re.compile(r"^\s*Links:\s*$", re.I)
_FOOTNOTE_RULE = re.compile(r"^\s*-{4,}\s*$")

# Our own outreach footer. If it survives quote stripping, everything from it
# onwards is ours, not theirs.
_OUR_FOOTER = re.compile(
    r"Reply\s+[“\"']?no thanks[”\"']?|Sent to\s+\S+@\S+\.", re.I)


def strip_quoted(body: str) -> str:
    """Return only the text the sender typed. Falls back to the original."""
    if not body:
        return ""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cut = len(lines)

    for i, line in enumerate(lines):
        stripped = line.strip()

        # A run of quoted lines that continues to the end is quoted material.
        if stripped.startswith(">"):
            cut = i
            break
        if _ATTRIBUTION.match(line) and _has_quote_after(lines, i):
            cut = i
            break
        if any(p.match(line) for p in _SEPARATORS):
            cut = i
            break
        if _SIG_DELIM.match(line):
            cut = i
            break
        if _LINK_FOOTER.match(line) and i + 1 < len(lines) and _FOOTNOTE_RULE.match(lines[i + 1]):
            cut = i
            break
        if _OUR_FOOTER.search(line):
            cut = i
            break

    kept = "\n".join(lines[:cut]).strip()
    if kept:
        return _collapse(kept)

    # Nothing above the quote. Many people — and most webmail on phones —
    # bottom-post: the quoted mail comes first and the actual reply sits
    # underneath it. "Thanks, No need any Service" arrived exactly that way.
    trailing = _text_after_quote(lines)
    if trailing:
        return _collapse(trailing)

    # Genuinely nothing but quoted text. Showing it in full beats showing blank.
    return _collapse(text)


def _text_after_quote(lines: list[str]) -> str:
    """Unquoted text that follows the quoted block, for bottom-posted replies."""
    # Walk back from the end over anything that is quoted, a link footnote, or
    # blank, and keep whatever real text is left at the bottom.
    end = len(lines)
    tail: list[str] = []
    for line in reversed(lines[:end]):
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if _FOOTNOTE_RULE.match(line) or _LINK_FOOTER.match(line):
            break
        # A bare footnote reference like "[1] https://..." is client furniture.
        if re.match(r"^\s*\[\d+\]\s", line):
            break
        tail.append(line)
    tail.reverse()
    candidate = "\n".join(tail).strip()
    # Require something sentence-like, so a stray bracket or date is not
    # mistaken for the reply.
    if len(candidate) >= 2 and re.search(r"[A-Za-z]{2,}", candidate):
        return candidate
    return ""


def _has_quote_after(lines: list[str], idx: int) -> bool:
    """True when quoted lines follow, so an attribution really starts a quote."""
    for line in lines[idx + 1: idx + 6]:
        if line.strip().startswith(">"):
            return True
    return False


def _collapse(text: str) -> str:
    """Tidy whitespace without touching the wording."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def summarise(body: str, limit: int = 220) -> str:
    """A one-line gist for list views, taken from the real reply only."""
    clean = strip_quoted(body)
    one = re.sub(r"\s+", " ", clean).strip()
    return one[:limit] + ("…" if len(one) > limit else "")


# Sentiment cues for an instant read in the inbox, before the model classifies.
# These are hints for display, never the basis for sending anything.
_NEGATIVE = re.compile(
    r"\bno\s+(?:need|thanks|thank you|interest)\b|\bnot interested\b|\bunsubscribe\b"
    r"|\bremove me\b|\bstop (?:emailing|contacting)\b|\bdo not contact\b|\bno thanks\b",
    re.I,
)
_POSITIVE = re.compile(
    r"\binterested\b|\bsounds good\b|\blet'?s (?:talk|discuss|connect)\b|\bplease (?:send|share|call)\b"
    r"|\bhow much\b|\bwhat (?:is|are) (?:your|the) (?:price|rate|cost|charges)\b"
    r"|\bcall me\b|\bschedule\b|\bmeeting\b|\bquote\b|\bproposal\b",
    re.I,
)
_QUESTION = re.compile(r"\?")


def quick_read(body: str) -> str:
    """negative | interested | question | neutral — a fast display hint."""
    clean = strip_quoted(body)
    if _NEGATIVE.search(clean):
        return "negative"
    if _POSITIVE.search(clean):
        return "interested"
    if _QUESTION.search(clean):
        return "question"
    return "neutral"
