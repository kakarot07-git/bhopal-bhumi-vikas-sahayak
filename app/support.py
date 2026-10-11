"""Programmatic check that the figures in an answer are supported by evidence.

Every number that carries a unit in the answer (m, sq m, Rs, %, hectare, years, days, storeys ...) must
appear in the verified rule quotes, the full text of the cited rules, the calculator results, the
question, or a tracked amendment. Figures that appear nowhere are reported as unsupported - the
answer is then not shown as a confident "answered" result.
"""

from __future__ import annotations

import json
import re

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
          "fifty": 50, "sixty": 60, "ninety": 90, "hundred": 100, "twice": 2, "once": 1, "half": 0.5}
_DEV = str.maketrans("०१२३४५६७८९", "0123456789")
_UNIT_AFTER = (r"\s*(?:sq\.?\s*m|square\s*met|m\b|mt?rs?\b|met(?:er|re)s?|मीटर|मी\b|वर्ग|%|per\s*cent|percent|प्रतिशत|"
               r"ha\b|hectares?|हेक्टेयर|years?|वर्ष|साल|days?|दिन|months?|महीन|storeys?|stor(?:e)?ies|floors?|मंज़िल|मंजिल|"
               r"seats?|trees?|kv|volts?|lakh|लाख)")
_RS_BEFORE = r"(?:rs\.?|₹|रु\.?|rupees?)\s*"


def _canon(num: str) -> str:
    """'1,250' -> '1250', '3.0' -> '3', '1.50' -> '1.5'."""
    n = num.replace(",", "")
    if "." in n:
        n = n.rstrip("0").rstrip(".")
    return n or "0"


def numbers_in(text: str) -> set[str]:
    t = text.translate(_DEV).lower()
    found = {_canon(m.group(0)) for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", t)}
    for w, v in _WORDS.items():
        if re.search(r"\b" + w + r"\b", t):
            found.add(_canon(str(v)))
    return found


def figures_in_answer(answer: str) -> list[str]:
    """Numbers with a unit or a rupee sign - the figures a citizen would act on."""
    t = answer.translate(_DEV).lower()
    figs = []
    for m in re.finditer(_RS_BEFORE + r"(\d[\d,]*(?:\.\d+)?)", t):
        figs.append(_canon(m.group(1)))
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)" + _UNIT_AFTER, t):
        figs.append(_canon(m.group(1)))
    return list(dict.fromkeys(figs))


def figures_in_rule_text(text: str) -> set[str]:
    """From a whole rule, keep only real figures: numbers with a unit or Rs, decimals (table values
    like 1.50) and amounts with commas. Bare list numbers like '4.' or '(2)' are ignored."""
    t = text.translate(_DEV).lower()
    found = set(figures_in_answer(text))
    found |= {_canon(m.group(0)) for m in re.finditer(r"\d+\.\d+", t)}
    found |= {_canon(m.group(0)) for m in re.finditer(r"\d{1,3}(?:,\d{2,3})+", t)}
    found |= {_canon(str(v)) for w, v in _WORDS.items() if re.search(r"\b" + w + r"\b", t)}
    for line in t.splitlines():  # table rows such as "126   200   2,000" carry figures without units
        nums = re.findall(r"\d[\d,]*(?:\.\d+)?", line)
        if len(nums) >= 2 and re.search(r"\d\s{2,}\d", line):
            found |= {_canon(n) for n in nums}
    return found


def _calc_texts(calculations: list[dict]) -> list[str]:
    """Only what the calculators actually concluded - values, notes, assumptions, warnings."""
    out = []
    for c in calculations:
        o = c.get("output", {}) or {}
        out += [f'{it.get("value", "")} {it.get("note", "")} {it.get("quote", "")}' for it in o.get("items", [])]
        out += [str(o.get(k, "")) for k in ("assumption", "caveat")] + [str(w) for w in o.get("warnings", [])]
        out += [json.dumps(c.get("input", {}))]
        if o.get("floors"):
            out.append(str(o["floors"].get("assumptions", "")))
    return out


def unsupported_figures(answer: str, evidence: dict) -> list[str]:
    """evidence = {"direct": [texts: quotes, calculator output, question, amendments], "rules": [full rule texts]}"""
    corpus = numbers_in("\n".join(evidence["direct"]))
    for text in evidence["rules"]:
        corpus |= figures_in_rule_text(text)
    return [f for f in figures_in_answer(answer) if f not in corpus]


def evidence_for(rules: dict, citations: list[dict], calculations: list[dict], question: str,
                 history: list[dict] | None, amendments: list[dict]) -> dict:
    direct = [question] + [h.get("question", "") for h in history or []]
    direct += [c["quote"] for c in citations if c.get("verified")]
    direct += _calc_texts(calculations)
    direct += [a.get("summary_en", "") + " " + a.get("quoted_words", "") + " " + a.get("date", "") for a in amendments]
    cited = {c["rule"] for c in citations if c.get("verified") and c["rule"] in rules}
    return {"direct": direct, "rules": [rules[r].text for r in cited]}
