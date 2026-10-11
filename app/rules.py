"""Load the MP Bhumi Vikas Rules, clean them, and verify quotes against them.

The rules file has running PDF page headers inside the text, e.g.
    "Rule 56        M.P. Bhumi Vikas Rules, 2012        78"
We strip those lines (they are not rule content) but remember where each page
starts, so a verified quote can be mapped back to its exact PDF page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_FILE = ROOT / "data" / "bhumi_vikas_rules.jsonl"

RULES_VERSION = "MP Bhumi Vikas Rules, 2012 - consolidated up to 6 March 2025 (official English PDF)"

# A running header line: "Rule 56   M.P. Bhumi Vikas Rules, 2012   78" (also "Rule 62-65", "Rules 1-2").
_HEADER_RE = re.compile(r"^\s*Rules?\s+[0-9A-Za-z\-\s,()]*?\s+M\.P\.\s+Bhumi\s+Vikas\s+Rules,\s+2012\s+(\d+)\s*$")


@dataclass
class Rule:
    rule: str
    title: str
    part: str
    page_start: int
    page_end: int
    text: str  # cleaned text (running headers removed)
    # (char offset in cleaned text, pdf page that starts there)
    page_marks: list[tuple[int, int]] = field(default_factory=list)

    def page_at(self, offset: int) -> int:
        page = self.page_start
        for pos, p in self.page_marks:
            if pos <= offset:
                page = p
            else:
                break
        return page


def _clean(raw: str, page_start: int) -> tuple[str, list[tuple[int, int]]]:
    out: list[str] = []
    marks: list[tuple[int, int]] = []
    length = 0
    for line in raw.split("\n"):
        m = _HEADER_RE.match(line)
        if m:
            marks.append((length, int(m.group(1))))
            continue
        out.append(line)
        length += len(line) + 1
    return "\n".join(out), marks


def load_rules(path: Path = RULES_FILE) -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            text, marks = _clean(d["text"], d["page_start"])
            rules[d["rule"]] = Rule(d["rule"], d["title"], d["part"], d["page_start"], d["page_end"], text, marks)
    return rules


# ---------------------------------------------------------------- quote verification

_DASHES = str.maketrans({"—": "-", "–": "-", "‘": "'", "’": "'", "“": '"', "”": '"'})


def _normalise(s: str) -> tuple[str, list[int]]:
    """Lower-case, unify dashes/quotes, collapse whitespace. Returns the string and,
    for each output char, its index in the input (to map matches back to offsets)."""
    s = s.translate(_DASHES)
    chars: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(s):
        if ch.isspace():
            # "built-\n   up" (PDF line-break hyphenation) must match "built-up": drop space after a hyphen
            if chars and chars[-1] == "-":
                prev_space = True
                continue
            if not prev_space:
                chars.append(" ")
                index.append(i)
            prev_space = True
        else:
            chars.append(ch.lower())
            index.append(i)
            prev_space = False
    if chars and chars[-1] == " ":
        chars.pop()
        index.pop()
    return "".join(chars), index


def normalise_rule_id(rule_id: str) -> str:
    """'Rule 56(1)(a)' -> '56'; '26-B' -> '26-B'; '17-a' -> '17' (inserted rules live in their parent)."""
    s = rule_id.strip()
    s = re.sub(r"(?i)^rules?\s*", "", s)
    m = re.match(r"(\d+)(?:\s*-\s*([A-Za-z]))?", s)
    if not m:
        return s
    num, letter = m.group(1), m.group(2)
    if num == "26" and letter and letter.upper() == "B":
        return "26-B"
    return num


@dataclass
class QuoteCheck:
    verified: bool
    rule: str | None
    page: int | None
    exact_text: str | None  # the matching span from the official text


def verify_quote(rules: dict[str, Rule], rule_id: str, quote: str) -> QuoteCheck:
    """A quote is verified only if it appears (whitespace/case-insensitively) in the cited
    rule's text. If it is found in a different rule we report that rule instead."""
    q = quote.strip().strip('"').strip("'").strip()
    q = re.sub(r"^\.\.\.|\.\.\.$|^…|…$", "", q).strip()
    nq, _ = _normalise(q)
    if len(nq) < 12:
        return QuoteCheck(False, None, None, None)
    key = normalise_rule_id(rule_id)
    order = ([key] if key in rules else []) + [k for k in rules if k != key]
    for k in order:
        r = rules[k]
        nt, idx = _normalise(r.text)
        pos = nt.find(nq)
        if pos >= 0:
            start, end = idx[pos], idx[pos + len(nq) - 1] + 1
            return QuoteCheck(True, k, r.page_at(start), r.text[start:end])
    return QuoteCheck(False, None, None, None)


def rulebook_prompt_text(rules: dict[str, Rule]) -> str:
    """The whole rulebook as one block for the model's (cached) system prompt."""
    parts = []
    for r in rules.values():
        parts.append(
            f'<rule number="{r.rule}" title="{r.title}" part="{r.part}" pdf_pages="{r.page_start}-{r.page_end}">\n'
            f"{r.text.strip()}\n</rule>"
        )
    return "\n\n".join(parts)


def search_rules(rules: dict[str, Rule], query: str, limit: int = 20) -> list[dict]:
    """Offline keyword search: every word must appear in the rule's title or text.
    Ranked by title matches, then number of hits. Returns a short snippet around the first hit."""
    words = [w for w in re.findall(r"[\w\-\.]+", query.lower()) if len(w) > 1]
    if not words:
        return []
    out = []
    for r in rules.values():
        hay, title = r.text.lower(), r.title.lower()
        if not all(w in hay or w in title for w in words):
            continue
        hits = sum(hay.count(w) for w in words)
        title_hits = sum(w in title for w in words)
        first = min((hay.find(w) for w in words if w in hay), default=0)
        start = max(0, first - 120)
        snippet = re.sub(r"\s+", " ", r.text[start:first + 220]).strip()
        out.append({"rule": r.rule, "title": r.title, "part": r.part, "page_start": r.page_start,
                    "page": r.page_at(first), "snippet": ("..." if start else "") + snippet + "...",
                    "score": title_hits * 100 + hits})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
