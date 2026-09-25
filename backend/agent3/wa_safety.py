"""Keep model planning out of a WhatsApp message.

The email path has had a send-safety gate for a long time; the WhatsApp path
had none and stored whatever came back. A message reached the panel looking
like this:

    WhatsApp message for an IT company contacting a business owner...
        *   Line 1: Greeting + Who I am.
        *   Line 2: The problem (lost customers/patients).
        *   *Line 1:* Salam, I'm Kashif Rehman from Eldian Core.
        *   *Length:* 42 words. (Within 35-55 range).

The model had written its plan, the message, and a word count, and all of it
was saved. Two defences here: spot that shape, and where the real message is
recoverable from inside it, pull it out rather than throwing the whole
generation away.
"""

from __future__ import annotations

import re

from shared.logger import get_logger

log = get_logger("agent3.wa_safety")

# Planning tells. Each has appeared in a real generation.
_PLANNING = (
    r"^\s*\*\s",                                   # markdown bullet list
    r"^\s*\d+\.\s",                                # numbered plan
    r"\*line\s*\d\s*:?\*?",                        # "*Line 1:*"
    r"\bline\s*\d\s*:",                            # "Line 1: Greeting"
    r"\*length\*?\s*:",                            # "*Length:*"
    r"\btotal\s*:?\s*\d+\s*words\b",
    r"\(\s*\d+\s*words?\s*\)",                     # "(7 words)"
    r"\bwithin\s+\d+\s*-\s*\d+\s*range\b",
    r"\b\d+\s*-\s*\d+\s*words?\b",                 # the brief's own "35-55 words"
    r"\bmax(?:imum)?\s+\d+\s+short\s+lines?\b",
    r"\bwhatsapp message for\b",                   # restating the task
    r"\bgreeting\s*\+\s*who\b",
    r"\bthe problem\s*\(",
    r"\bwebsite\s*\(exact\)",
    r"<\/?think>",
    r"\bhere(?:'s| is) (?:the|your) (?:message|draft)\b",
)
_PLANNING_RE = re.compile("|".join(_PLANNING), re.I | re.M)

# A real message opens with a greeting. Used to find the message inside a plan.
_GREETING_RE = re.compile(
    r"^\s*\**\s*(?:\*?line\s*\d\s*:?\*?\s*)?"
    r"(salam|assalam|as-salam|hello|hi)\b", re.I)

# Strip the markdown scaffolding a planned line carries.
_LINE_LABEL = re.compile(r"^\s*\*+\s*|^\s*\d+\.\s*|\*?line\s*\d\s*:\*?\s*|\*+\s*$", re.I)


def _clean_line(line: str) -> str:
    out = _LINE_LABEL.sub("", line).strip()
    out = re.sub(r"\s*\(\d+\s*words?\)\s*$", "", out, flags=re.I)   # trailing count
    return out.strip(" *_")


def extract_message(raw: str) -> str:
    """Pull the actual message out of a reply that may carry planning with it.

    Returns "" when nothing message-shaped can be found, so the caller can
    regenerate rather than send a plan to a prospect.
    """
    text = (raw or "").strip().strip('"')
    if not text:
        return ""

    # Clean already? Take it as-is.
    if not _PLANNING_RE.search(text):
        return text

    # Otherwise find the greeting and read the message lines that follow it.
    # Search from the END: a plan restates the greeting when listing its
    # structure, and the real message is the last occurrence, not the first.
    lines = text.splitlines()
    start = next((i for i in range(len(lines) - 1, -1, -1)
                  if _GREETING_RE.search(lines[i])), None)
    if start is None:
        return ""

    kept: list[str] = []
    for line in lines[start:]:
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        # The word-count commentary that usually follows the message.
        if re.search(r"\blength\b|\btotal\b|\bwords?\b\s*[.)]?$|\blines?\s*:", cleaned, re.I):
            break
        kept.append(cleaned)
        # The website is always the final line of a well-formed message.
        if re.search(r"\b[\w.-]+\.(?:com|pk|pro|io|net|org)\b", cleaned):
            break

    message = "\n".join(kept).strip()
    if not message or _PLANNING_RE.search(message):
        return ""
    return message


def message_issues(message: str) -> list[str]:
    """Reasons this must not be sent. Empty list means it is fine."""
    issues: list[str] = []
    text = (message or "").strip()
    if not text:
        return ["empty message"]
    if _PLANNING_RE.search(text):
        issues.append("contains the model's planning or a word count")
    words = len(text.split())
    if words < 12:
        issues.append(f"too short ({words} words)")
    if words > 110:
        issues.append(f"too long for WhatsApp ({words} words)")
    if re.search(r"\[(?:name|business|company|city|niche)\]|\{\{", text, re.I):
        issues.append("contains an unfilled placeholder")
    if text.count("*") >= 4:
        issues.append("contains markdown formatting")
    return issues
