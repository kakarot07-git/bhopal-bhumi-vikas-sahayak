"""Decide, in plain Python, which calculations a question needs and whether every input is known.

    question (+ earlier turns) -> extract inputs -> run applicable calculators -> evidence for ONE Claude call

If the inputs are known, the numbers are computed here and Claude only explains and cites them
(no tool round trips). If a number in the question cannot be attributed safely (e.g. "30x40 plot",
two different plot areas), the plan is marked ambiguous and the tool-calling path is used, with an
instruction to ask the clerk rather than guess. Unit conversions (feet, sq ft, gaj, acre) happen here,
in code, and are shown to the clerk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .calculators import (building_permission_fee, development_permission_fee, front_open_space,
                          rear_open_space, residential_plot_norms)

SQFT, SQYD, ACRE, FT = 0.09290304, 0.83612736, 4046.8564224, 0.3048  # exact conversion factors to metric

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
NUM = r"(\d+(?:\.\d+)?)"

AREA_SQM = r"(?:sq\.?\s*m(?:t?rs?|eters?|etres?)?\b|sqm\b|square\s*met(?:er|re)s?|m2\b|m²|वर्ग\s*मी(?:टर)?|वर्गमीटर)"
AREA_SQFT = r"(?:sq\.?\s*f(?:ee)?t\b|sqft\b|square\s*f(?:ee|oo)t|वर्ग\s*(?:फ़ीट|फीट|फुट))"
AREA_SQYD = r"(?:sq\.?\s*y(?:ar)?ds?\b|square\s*yards?|गज)"
AREA_HA = r"(?:hectares?\b|ha\b|हेक्टेयर)"
AREA_ACRE = r"(?:acres?\b|एकड़)"
LEN_M = r"(?:m\b|mtrs?\b|meters?\b|metres?\b|मीटर|मी\b)"
LEN_FT = r"(?:ft\b|feet\b|foot\b|फ़ीट|फीट|फुट)"

INTENTS = {
    "front": r"\bfront\b|आगे|सेटबैक|setback|open\s*space|\bgap\b|margin|\bmos\b|खाली\s*जगह|जगह\s*छोड़",
    "rear": r"\brear\b|\bback\b|पीछे|setback|open\s*space|\bmos\b",
    "side": r"\bside\b|बगल|साइड",
    "far": r"floor\s*area\s*ratio|\bfloors?\b|stor(?:e)?y|storeys|मंज़िल|मंजिल|how\s*much\s*can\s*i\s*build|built-?\s*up\s*area\s*allowed",
    "height": r"\bheight\b|how\s*(?:tall|high)|ऊँचाई|ऊंचाई",
    "fee": r"\bfees?\b|\bcharges?\b|शुल्क|फीस|फ़ीस",
    "devfee": r"development\s*(?:permission\s*)?fee|fee\s*for\s*development|विकास\s*(?:अनुज्ञा|अनुमति)\s*(?:का\s*)?(?:शुल्क|फीस)",
}
# Contexts where the residential Rule 56 / Rule 61 tables do not apply - leave these to Claude.
NON_RESIDENTIAL = r"farm\s*house|farmhouse|cinema|theatre|theater|multiplex|\bmall\b|marriage\s*garden|petrol|fuel|filling\s*station|hospital|school|group\s*housing|high[-\s]*rise|industrial|factory|\bshops?\b|commercial|दुकान|व्यावसायिक"
BUILT_UP_CTX = r"built[-\s]*up|builtup|construction\s*area|covered\s*area|निर्मित|बिल्ट[-\s]*अप"
ROAD_CTX = r"road|street|lane|सड़क|सडक|रोड|रास्ता|गली"
HEIGHT_CTX = r"tall|high\b|height|ऊँच|ऊंच"
FRONTAGE_CTX = r"frontage|फ्रंटेज"
PLOT_CTX = r"plot|site|land|प्लॉट|प्लाट|ज़मीन|जमीन"


@dataclass
class Plan:
    inputs: dict = field(default_factory=dict)        # plot_area_sqm, road_width_m, height_m, frontage_m, built_up_area_sqm, land_area_sqm, use, zone
    notes: list[str] = field(default_factory=list)    # how each input was read (shown to Claude and the clerk)
    intents: set[str] = field(default_factory=set)
    calculations: list[dict] = field(default_factory=list)  # [{tool, input, output}]
    missing: list[str] = field(default_factory=list)   # inputs needed for a detected intent but not given
    ambiguous: list[str] = field(default_factory=list) # reasons the inputs could not be read safely

    @property
    def precomputed(self) -> bool:
        """True when Python already ran every calculation it could and nothing is ambiguous -> one Claude call, no tools."""
        return bool(self.calculations) and not self.ambiguous


def _norm(text: str) -> str:
    return text.translate(_DEV_DIGITS).replace(",", "").lower()


def _context(text: str, start: int, end: int, before: int = 45, after: int = 30) -> str:
    return text[max(0, start - before):min(len(text), end + after)]


def _nearest(t: str, start: int, end: int, kinds: dict[str, str], window: int = 45) -> str | None:
    """Attribute a number to the closest context keyword, e.g. '10 m wide street and will be 9 m tall':
    10 -> road width, 9 -> height. A keyword right after the number ('9 m road') counts as closest."""
    best, best_d = None, window + 1
    lo = max(0, start - window)
    for kind, pat in kinds.items():
        for m in re.finditer(pat, t[lo:min(len(t), end + window)]):
            pos = lo + m.start()
            d = (start - (lo + m.end())) if pos < start else (pos - end) * 0.8
            if d < best_d:
                best, best_d = kind, d
    return best


def extract(text: str) -> tuple[dict, list[str], list[str]]:
    """Return (inputs, notes, ambiguities) for one piece of text."""
    t = _norm(text)
    inputs: dict = {}
    notes: list[str] = []
    amb: list[str] = []
    used: list[tuple[int, int]] = []

    def put(key, value, note):
        if key in inputs and abs(inputs[key] - value) > 1e-6:
            amb.append(f"two different values for {key.replace('_', ' ')} ({inputs[key]:g} and {value:g})")
        inputs[key] = value
        notes.append(note)

    # dimensions like "30x40" or "30 x 40 feet" - unit is usually unstated, so never guess
    for m in re.finditer(NUM + r"\s*[x×*]\s*" + NUM + r"(\s*" + LEN_FT + r"|\s*" + LEN_M + r")?", t):
        unit = (m.group(3) or "").strip()
        if not unit:
            amb.append(f"plot dimensions '{m.group(0).strip()}' without a unit (feet or metres?)")
        else:
            a, b = float(m.group(1)), float(m.group(2))
            factor = FT if re.match(LEN_FT, unit) else 1.0
            area = a * factor * b * factor
            put("plot_area_sqm", round(area, 2), f"plot {m.group(0).strip()} = {area:.2f} sq m" + (" (1 ft = 0.3048 m)" if factor != 1 else ""))
        used.append(m.span())

    def free(span):
        return not any(s <= span[0] < e or s < span[1] <= e for s, e in used)

    # areas
    for unit_re, factor, label in [(AREA_HA, 10000.0, "hectare"), (AREA_ACRE, ACRE, "acre"),
                                   (AREA_SQFT, SQFT, "sq ft"), (AREA_SQYD, SQYD, "sq yd/gaj"), (AREA_SQM, 1.0, "sq m")]:
        for m in re.finditer(NUM + r"\s*" + unit_re, t):
            if not free(m.span()):
                continue
            used.append(m.span())
            value = round(float(m.group(1)) * factor, 2)
            ctx = _context(t, *m.span())
            conv = "" if factor == 1.0 else f" = {value:,.2f} sq m (converted in code)"
            if label in ("hectare", "acre"):
                put("land_area_sqm", value, f"land area {m.group(1)} {label}{conv}")
            elif _nearest(t, *m.span(), {"built_up": BUILT_UP_CTX, "plot": PLOT_CTX}) == "built_up":
                put("built_up_area_sqm", value, f"built-up area {m.group(1)} {label}{conv}")
            else:
                put("plot_area_sqm", value, f"plot area {m.group(1)} {label}{conv}")

    # lengths: road width, height, frontage
    for unit_re, factor, label in [(LEN_FT, FT, "ft"), (LEN_M, 1.0, "m")]:
        for m in re.finditer(NUM + r"\s*" + unit_re, t):
            if not free(m.span()):
                continue
            used.append(m.span())
            value = float(m.group(1)) * factor
            conv = "" if factor == 1.0 else f" = {value:.2f} m (converted in code)"
            kind = _nearest(t, *m.span(), {"frontage_m": FRONTAGE_CTX, "road_width_m": ROAD_CTX, "height_m": HEIGHT_CTX})
            names = {"frontage_m": "frontage", "road_width_m": "road width", "height_m": "building height"}
            if kind:
                put(kind, round(value, 2), f"{names[kind]} {m.group(1)} {label}{conv}")
            # other lengths (e.g. distances in a rule question) are simply not inputs

    if re.search(r"commercial|\bshops?\b|दुकान|व्यावसायिक", t):
        inputs["use"] = "commercial"
    if re.search(r"agricultur|recreation|कृषि", t):
        inputs["zone"] = "recreational_agriculture_other"
    elif re.search(r"commercial|व्यावसायिक", t):
        inputs["zone"] = "commercial"
    elif re.search(r"residential|housing|colony|आवासीय", t):
        inputs["zone"] = "residential_psp_industrial_transport"
    return inputs, notes, amb


def detect_intents(text: str) -> set[str]:
    t = _norm(text)
    found = {k for k, pat in INTENTS.items() if re.search(pat, t)}
    if re.search(r"\bF\.?A\.?R\b", text):  # "FAR" in capitals only - "how far" is not a FAR question
        found.add("far")
    if "devfee" in found:
        found.discard("fee")
    return found


def plan(question: str, history: list[dict] | None = None) -> Plan:
    p = Plan()
    # Earlier turns first, so the new question overrides them ("and if the road were 12 m?")
    for turn in history or []:
        inp, _, _ = extract(turn.get("question", ""))
        p.inputs.update(inp)
    prev_intents = detect_intents((history or [{}])[-1].get("question", "")) if history else set()
    inp, notes, amb = extract(question)
    p.inputs.update(inp)
    p.notes = notes + ([f"from earlier in the conversation: {', '.join(k.replace('_', ' ') for k in p.inputs if k not in inp)}"]
                       if history and any(k not in inp for k in p.inputs) else [])
    p.ambiguous = amb
    p.intents = detect_intents(question) or prev_intents
    whole = " ".join([*(h.get("question", "") for h in history or []), question])
    non_res = bool(re.search(NON_RESIDENTIAL, _norm(whole))) and p.inputs.get("use") != "commercial"
    commercial = p.inputs.get("use") == "commercial"
    i = p.inputs

    plot_intent = p.intents & {"front", "rear", "side", "far", "height"}
    if plot_intent and not (non_res or commercial):
        if "plot_area_sqm" in i and "road_width_m" in i:
            args = {"plot_area_sqm": i["plot_area_sqm"], "road_width_m": i["road_width_m"], "frontage_m": i.get("frontage_m"),
                    "building_type": None, "proposed_height_m": i.get("height_m")}
            p.calculations.append({"tool": "residential_plot_norms", "input": args, "output": residential_plot_norms(**args)})
        else:
            partial = _partial_norms(i, plot_intent)
            if partial:
                p.calculations.append(partial)
            if "road_width_m" not in i and ("front" in plot_intent or "far" in plot_intent):
                p.missing.append("road width")
            if "plot_area_sqm" not in i and (plot_intent & {"rear", "far", "side"}):
                p.missing.append("plot area")
    elif plot_intent and commercial:
        p.notes.append("commercial building: Rule 56 residential tables not applied (Rule 57 governs other occupancies)")

    if "fee" in p.intents:
        use = "commercial" if commercial else "residential"
        if "built_up_area_sqm" in i:
            args = {"built_up_area_sqm": i["built_up_area_sqm"], "use": use, "high_rise": bool(i.get("height_m", 0) > 30)}
            p.calculations.append({"tool": "building_permission_fee", "input": args, "output": building_permission_fee(**args)})
        elif "plot_area_sqm" in i and not non_res and not commercial:
            far = _far_from(p.calculations) or 1.25
            bua = round(far * i["plot_area_sqm"], 2)
            args = {"built_up_area_sqm": bua, "use": use, "high_rise": False}
            out = building_permission_fee(**args)
            out["assumption"] = (f"Built-up area not given: fee shown for the maximum permitted built-up area "
                                 f"{bua:g} sq m (FAR {far:g} x {i['plot_area_sqm']:g} sq m). Ask for the proposed built-up area for the exact fee.")
            p.calculations.append({"tool": "building_permission_fee", "input": args, "output": out})
            p.missing.append("proposed built-up area (for the exact fee)")
        else:
            p.missing.append("proposed built-up area")

    if "devfee" in p.intents:
        if "land_area_sqm" in i and "zone" in i:
            args = {"land_area_sqm": i["land_area_sqm"], "zone": i["zone"], "population": "above_10_lakh"}
            p.calculations.append({"tool": "development_permission_fee", "input": args, "output": development_permission_fee(**args)})
        elif "land_area_sqm" in i:
            p.ambiguous.append("land use zone for the development fee not stated (residential, commercial or agriculture?)")
        else:
            p.missing.append("land area")
    return p


def _far_from(calcs: list[dict]) -> float | None:
    for c in calcs:
        for it in c["output"].get("items", []):
            if it["label"].startswith("Maximum FAR"):
                try:
                    return float(it["value"])
                except ValueError:
                    return None
    return None


def _partial_norms(i: dict, intents: set[str]) -> dict | None:
    """Only one of plot area / road width is known: compute just the open space that input decides."""
    from .calculators import Item
    items = []
    if "road_width_m" in i and "front" in intents:
        metres, q = front_open_space(i["road_width_m"])
        items.append(Item("Front open space (min)", f"{metres:g} m", "56", 77, q,
                          note=f"Road width {i['road_width_m']:g} m; residential building up to 12.5 m height.").to_dict())
    if "plot_area_sqm" in i and "rear" in intents:
        metres, q = rear_open_space(i["plot_area_sqm"])
        items.append(Item("Rear open space (min)", "Nil" if metres == 0 else f"{metres:g} m", "56", 78, q,
                          note=f"Plot area {i['plot_area_sqm']:g} sq m; residential building up to 12.5 m height.").to_dict())
    if not items:
        return None
    warnings = []
    if i.get("height_m", 0) > 12.5:
        warnings.append("Proposed height is above 12.5 m: Rule 56 open spaces apply only up to 12.5 m; Rule 42 Table 4/5 apply above.")
    return {"tool": "residential_open_space", "input": {k: i[k] for k in ("road_width_m", "plot_area_sqm", "height_m") if k in i},
            "output": {"items": items, "warnings": warnings,
                       "caveat": "Only the open space that the given input decides is shown. The Development Plan may differ (Rule 103)."}}


def evidence_text(p: Plan) -> str:
    """The block appended to the clerk's question for the single Claude call."""
    import json
    calcs = [{"calculator": c["tool"], "input": c["input"],
              "results": [{k: it[k] for k in ("label", "value", "rule", "page", "quote", "note")} for it in c["output"].get("items", [])],
              **{k: c["output"][k] for k in ("warnings", "assumption", "floors") if c["output"].get(k)}}
             for c in p.calculations]
    lines = ["<computed_evidence>",
             "The application read these inputs from the question and ran its calculators on the official tables. "
             "Use these numbers exactly; do not recompute or add numbers of your own. Cite the rule rows they come from.",
             "Inputs read: " + ("; ".join(p.notes) or "none"),
             "Inputs still missing: " + (", ".join(p.missing) or "none") + ". If a missing input matters, say so in ask_citizen; do not assume it.",
             json.dumps(calcs, ensure_ascii=False),
             "</computed_evidence>"]
    return "\n".join(lines)


def ambiguity_text(p: Plan) -> str:
    return ("<input_check>The application could not read the inputs safely: " + "; ".join(p.ambiguous)
            + ". Do not guess units or values. Ask the clerk to confirm them in ask_citizen; "
            "answer only what the rules say without those numbers.</input_check>")
