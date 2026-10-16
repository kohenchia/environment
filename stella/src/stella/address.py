"""Is a message addressed to Stella? A fixed rule, so it can be tested.

Addressed: the message starts with "Stella" or "S" (any case, after optional
whitespace) followed by punctuation or a space ("S, do x", "S: do x", "S do x"),
starts with a greeting or filler plus her name ("hey Stella"), ends with her name
("... thanks, Stella"), or contains "ask Stella" / "tell Stella". A mid-sentence
"s", or "Stella" in the middle of a sentence, never counts.
"""

from __future__ import annotations

import re

_START = re.compile(
    r"^\s*(?:(?:hey|hi|hello|ok|okay|and|also|please)[\s,]+)?(?:@?stella\b[\s,:;.!?-]*|s\s*[,:]|s\s+(?=\w))",
    re.IGNORECASE,
)
_ASK = re.compile(r"\b(?:ask|tell)\s+stella\b", re.IGNORECASE)
_END = re.compile(r"[,\s]stella[\s.!?]*$", re.IGNORECASE)
_QUESTION_START = re.compile(
    r"^(what|whats|what's|how|is|are|was|were|did|does|do|can|could|should|would|who|"
    r"when|where|why|which|any|anything|status|am i|have i|has)\b",
    re.IGNORECASE,
)


def is_addressed(prompt: str) -> bool:
    return bool(_START.match(prompt) or _ASK.search(prompt) or _END.search(prompt))


def strip_address(prompt: str) -> str:
    return _START.sub("", prompt, count=1).strip()


def kind(prompt: str) -> str:
    """'question' or 'instruction'. Questions don't become open orders."""
    body = strip_address(prompt).strip()
    if body.endswith("?") and _QUESTION_START.match(body):
        return "question"
    if _QUESTION_START.match(body) and "\n" not in body and len(body) < 120 and body.endswith("?"):
        return "question"
    return "instruction"


_AFFIRM = re.compile(
    r"^\s*(?:(?:@?stella|s)\s*[,:]?\s*)?(yes|y|yep|yes,? push(?: it)?|push it)\s*[.!]*\s*$",
    re.IGNORECASE,
)


def is_affirmative(prompt: str) -> bool:
    return bool(_AFFIRM.match(prompt))
