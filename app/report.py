"""One PDF with everything the clerk did in this session: questions and answers, Setback & FAR
(and a scenario comparison), building and development fees, and every rule passage used.

Integrity: the browser sends only the inputs and the answers it showed. Calculator results are
recomputed here from the inputs, and every quote in an answer is re-checked against the official
text - a quote that does not verify is left out of the PDF.

Hindi needs a font with Devanagari and text shaping (fpdf2 + uharfbuzz). On Windows the built-in
Nirmala UI font is used; elsewhere set BVS_PDF_FONT / BVS_PDF_FONT_BOLD to TTF files (e.g. Noto Sans
Devanagari). Without such a font the PDF is still produced, with Hindi text replaced by a notice.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from .amendments import AMENDMENTS
from .calculators import _rs, building_permission_fee, case_summary, development_permission_fee, residential_plot_norms
from .rules import RULES_VERSION, Rule, verify_quote

L = {
    "en": {
        "title": "Case report", "sub": "Building Permission Counter · Bhopal Municipal Corporation",
        "generated": "Generated", "version": "Rules version", "amend": "Later amendment",
        "check": "Secondary source - check against the official gazette.",
        "s_summary": "Case summary", "s_qa": "Questions and answers", "s_plot": "Setback & FAR",
        "s_compare": "Scenario comparison", "s_fee": "Building permission fee", "s_dev": "Development permission fee",
        "s_rules": "Rule text used in this report", "q": "Question", "ask": "Ask the citizen",
        "item": "Item", "value": "Value", "source": "Rule / PDF page", "a": "Scenario A", "b": "Scenario B",
        "changed": "changed", "nothing": "Nothing was calculated or asked yet in this session.",
        "front": "Front open space", "rear": "Rear open space", "far": "FAR", "bua": "Max built-up area",
        "height": "Max height", "fee": "Building permission fee (total)", "devfee": "Development permission fee (total)",
        "assumed": "assumes the full permitted built-up area",
        "status": {"answered": "Answered from the rules", "partial": "Partly covered by the rules",
                   "not_found": "Not found in the rules", "unverified": "Could not verify", "error": "Error"},
        "foot": "This report points to the rules. The clerk decides. It is not legal advice.", "page": "Page",
        "inputs": "Inputs", "caveat": "Note",
    },
    "hi": {
        "title": "केस रिपोर्ट", "sub": "भवन अनुज्ञा काउंटर · भोपाल नगर पालिक निगम",
        "generated": "तैयार", "version": "नियम संस्करण", "amend": "बाद का संशोधन",
        "check": "द्वितीयक स्रोत - आधिकारिक राजपत्र से जाँचें।",
        "s_summary": "केस सारांश", "s_qa": "प्रश्न और उत्तर", "s_plot": "सेटबैक व FAR",
        "s_compare": "स्थितियों की तुलना", "s_fee": "भवन अनुज्ञा शुल्क", "s_dev": "विकास अनुज्ञा शुल्क",
        "s_rules": "इस रिपोर्ट में उपयोग हुआ नियम-पाठ", "q": "प्रश्न", "ask": "नागरिक से पूछें",
        "item": "मद", "value": "मान", "source": "नियम / PDF पृष्ठ", "a": "स्थिति A", "b": "स्थिति B",
        "changed": "बदला", "nothing": "इस सत्र में अभी कुछ गणना या पूछा नहीं गया।",
        "front": "सामने की खुली जगह", "rear": "पीछे की खुली जगह", "far": "FAR", "bua": "अधिकतम निर्मित क्षेत्रफल",
        "height": "अधिकतम ऊँचाई", "fee": "भवन अनुज्ञा शुल्क (कुल)", "devfee": "विकास अनुज्ञा शुल्क (कुल)",
        "assumed": "पूरे अनुमत निर्मित क्षेत्रफल पर",
        "status": {"answered": "नियमों से उत्तर", "partial": "नियमों में आंशिक उत्तर",
                   "not_found": "नियमों में नहीं मिला", "unverified": "सत्यापित नहीं हो सका", "error": "त्रुटि"},
        "foot": "यह रिपोर्ट नियम बताती है। निर्णय लिपिक का है। यह कानूनी सलाह नहीं है।", "page": "पृष्ठ",
        "inputs": "इनपुट", "caveat": "नोट",
    },
}

IST = timezone(timedelta(hours=5, minutes=30))  # Bhopal time, regardless of the server's clock
INK, MUTED, ACCENT, LINE = (24, 34, 47), (85, 99, 118), (18, 49, 92), (205, 214, 226)


FONT_DIR = Path(__file__).resolve().parent / "fonts"


def _fonts() -> dict | None:
    """Font for English + Hindi. The bundled Hind font (SIL Open Font Licence, app/fonts) has both Latin and
    Devanagari, so the PDF looks the same on any server, including Vercel/Linux. BVS_PDF_FONT overrides it;
    Windows' Nirmala UI is the last resort."""
    env_r, env_b = os.environ.get("BVS_PDF_FONT"), os.environ.get("BVS_PDF_FONT_BOLD")
    if env_r and Path(env_r).exists():
        b = env_b if env_b and Path(env_b).exists() else env_r
        return {"main": ((env_r, 0), (b, 0)), "fallback": None}
    hind_r, hind_b = FONT_DIR / "Hind-Regular.ttf", FONT_DIR / "Hind-Bold.ttf"
    if hind_r.exists() and hind_b.exists():  # one font with both Latin and Devanagari
        return {"main": ((str(hind_r), 0), (str(hind_b), 0)), "fallback": None}
    win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "Nirmala.ttc"
    if win.exists():
        return {"main": ((str(win), 0), (str(win), 1)), "fallback": None}  # Nirmala UI has Latin + Devanagari
    return None


def _plain(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")


class _PDF(FPDF):
    def __init__(self, lang: str):
        super().__init__(format="A4")
        self.t = L[lang]
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(True, margin=18)
        fonts = _fonts()
        self.unicode = fonts is not None
        if fonts:
            (r, ri), (b, bi) = fonts["main"]
            self.add_font("Body", "", r, collection_font_number=ri)
            self.add_font("Body", "B", b, collection_font_number=bi)
            if fonts["fallback"]:  # Devanagari glyphs come from the fallback font
                (dr, dri), (db, dbi) = fonts["fallback"]
                self.add_font("Deva", "", dr, collection_font_number=dri)
                self.add_font("Deva", "B", db, collection_font_number=dbi)
                self.set_fallback_fonts(["Deva"], exact_match=False)
            self.set_text_shaping(True)
            self.face = "Body"
        else:
            self.face = "helvetica"
        self.alias_nb_pages()

    def txt(self, s: str) -> str:
        s = str(s if s is not None else "")
        if self.unicode:
            return s
        s = s.replace("·", "-").replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
        return s.encode("latin-1", "replace").decode("latin-1").replace("?", "?")

    def footer(self):
        self.set_y(-13)
        self.set_font(self.face, "", 7.5)
        self.set_text_color(*MUTED)
        self.cell(0, 5, self.txt(f'{self.t["foot"]}   {self.t["page"]} {self.page_no()}/{{nb}}'), align="C")

    def h1(self, s):
        self.set_font(self.face, "B", 17)
        self.set_text_color(*ACCENT)
        self.multi_cell(0, 8, self.txt(s), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def h2(self, s):
        if self.get_y() > self.h - 50:
            self.add_page()
        self.ln(3)
        self.set_font(self.face, "B", 12.5)
        self.set_text_color(*ACCENT)
        self.cell(0, 7, self.txt(s), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*ACCENT)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def para(self, s, size=10, bold=False, color=INK, h=5.2, indent=0):
        self.set_font(self.face, "B" if bold else "", size)
        self.set_text_color(*color)
        self.set_x(self.l_margin + indent)
        self.multi_cell(self.w - self.l_margin - self.r_margin - indent, h, self.txt(s), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def answer_text(self, s):
        for line in _plain(s).split("\n"):
            line = line.rstrip()
            if not line.strip():
                self.ln(1.5)
                continue
            m = re.match(r"^\s*[-•*]\s+(.*)$", line)
            if m:
                self.para("•  " + m.group(1), indent=4)
            else:
                self.para(line)

    def box(self, s, fill=(255, 241, 222)):
        self.set_fill_color(*fill)
        self.set_font(self.face, "", 9)
        self.set_text_color(*INK)
        self.multi_cell(0, 4.8, self.txt(s), fill=True, padding=2.5, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def table(self, header, rows, widths, highlight=None):
        self.set_font(self.face, "", 8.8)
        self.set_draw_color(*LINE)
        self.set_fill_color(255, 255, 255)  # don't inherit the tint of the last note box
        head = FontFace(emphasis="BOLD", color=ACCENT, fill_color=(230, 237, 247))
        with super().table(col_widths=widths, line_height=4.8, padding=1.6, first_row_as_headings=True,
                           headings_style=head, text_align="LEFT") as tb:
            hr = tb.row()
            for h in header:
                hr.cell(self.txt(h))
            for i, r in enumerate(rows):
                row = tb.row()
                for c in r:
                    row.cell(self.txt(c))
        self.ln(2)


def _items_rows(items):
    return [[i["label"] + (f"\n{i['note']}" if i.get("note") else ""), i["value"], f"Rule {i['rule']} · p.{i['page']}"] for i in items]


def build_report(data: dict, rules: dict[str, Rule]) -> bytes:
    lang = "hi" if data.get("lang") == "hi" else "en"
    pdf = _PDF(lang)
    t = pdf.t
    pdf.add_page()
    cites: dict[tuple, dict] = {}

    # ---- header
    pdf.h1(f"Bhumi Vikas Sahayak · भूमि विकास सहायक - {t['title']}" if pdf.unicode else f"Bhumi Vikas Sahayak - {t['title']}")
    pdf.para(t["sub"], size=10, color=MUTED)
    pdf.para(f"{t['generated']}: {datetime.now(IST).strftime('%d %b %Y, %H:%M')} IST   ·   {t['version']}: {RULES_VERSION}", size=8.5, color=MUTED)
    for a in AMENDMENTS:
        pdf.ln(1)
        pdf.box(f"{t['amend']} ({a['date']}, Rule {a['clause']}): {a['summary_hi'] if lang == 'hi' else a['summary_en']} {t['check']}")

    plot_in, fee_in, dev_in, cmp_in = data.get("plot"), data.get("fee"), data.get("devfee"), data.get("compare")
    convs = [c for c in data.get("conversations") or [] if c]
    if not (plot_in or fee_in or dev_in or convs):
        pdf.ln(4)
        pdf.para(t["nothing"])
        return bytes(pdf.output())

    # ---- recompute every calculation from the inputs
    plot = residential_plot_norms(**_pick(plot_in, ["plot_area_sqm", "road_width_m", "frontage_m", "building_type", "proposed_height_m"])) if plot_in else None
    plot_b = residential_plot_norms(**_pick(cmp_in, ["plot_area_sqm", "road_width_m", "frontage_m", "building_type", "proposed_height_m"])) if (plot_in and cmp_in) else None
    fee = building_permission_fee(**_pick(fee_in, ["built_up_area_sqm", "use", "high_rise"])) if fee_in else None
    dev = development_permission_fee(**_pick(dev_in, ["land_area_sqm", "zone", "population"])) if dev_in else None
    summ = None
    if plot and "error" not in plot:
        summ = case_summary(**_pick(plot_in, ["plot_area_sqm", "road_width_m", "frontage_m", "building_type", "proposed_height_m"]),
                            use=(fee_in or {}).get("use", "residential"), built_up_area_sqm=(fee_in or {}).get("built_up_area_sqm"))

    # ---- 1. case summary
    if summ or fee or dev:
        pdf.h2("1. " + t["s_summary"])
        rows = []
        if summ and "error" not in summ:
            h = summ["headline"]
            rows += [[t["front"], h["front_open_space"] or "-"], [t["rear"], h["rear_open_space"] or "-"],
                     [t["far"], f'{h["far"]:g}'], [t["bua"], f'{h["max_built_up_sqm"]:g} sq m'],
                     [t["height"], str(h["max_height"] or "-").split(" (")[0]]]
        if fee and "error" not in fee:
            rows.append([t["fee"], _rs(fee["total_rs"]) + f"  ({fee_in['built_up_area_sqm']:g} sq m)"])
        elif summ and "error" not in summ:
            h = summ["headline"]
            rows.append([t["fee"], _rs(h["total_fee_rs"]) + f"  ({t['assumed']}, {h['fee_built_up_sqm']:g} sq m)"])
        if dev and "error" not in dev:
            rows.append([t["devfee"], _rs(dev["total_rs"])])
        pdf.table([t["item"], t["value"]], rows, (55, 45))
        if summ and summ.get("warnings"):
            for w in summ["warnings"]:
                pdf.box(w)

    # ---- 2. questions and answers
    n = 2
    if convs:
        pdf.h2(f"{n}. {t['s_qa']}")
        n += 1
        for conv in convs:
            for turn in conv:
                a = turn.get("answer") or {}
                pdf.para(f"{t['q']}: {turn.get('question', '')}", bold=True, color=ACCENT)
                pdf.para(t["status"].get(a.get("status", ""), a.get("status", "")), size=8.5, color=MUTED)
                pdf.answer_text(a.get("answer", ""))
                if a.get("ask_citizen"):
                    pdf.box(f"{t['ask']}: {a['ask_citizen']}", fill=(230, 237, 247))
                if a.get("amendment_note"):
                    pdf.box(a["amendment_note"])
                for c in a.get("citations") or []:
                    chk = verify_quote(rules, str(c.get("rule", "")), c.get("quote", ""))
                    if not chk.verified:  # only re-verified quotes go into the report
                        continue
                    r = rules[chk.rule]
                    pdf.para(f"Rule {chk.rule} · {r.title} · PDF p.{chk.page}", size=8.5, bold=True, color=ACCENT, indent=4)
                    pdf.para(re.sub(r"\s+", " ", chk.exact_text), size=8.5, color=MUTED, indent=4, h=4.4)
                    cites[(chk.rule, chk.page, re.sub(r"\s+", " ", chk.exact_text))] = r.title
                pdf.ln(3)

    # ---- 3. setback & FAR (+ comparison)
    if plot and "error" not in plot:
        pdf.h2(f"{n}. {t['s_plot']}")
        n += 1
        pdf.para(f"{t['inputs']}: " + _inputs_text(plot["inputs"]), size=9, color=MUTED)
        pdf.table([t["item"], t["value"], t["source"]], _items_rows(plot["items"]), (78, 62, 38))
        for w in plot.get("warnings", []):
            pdf.box(w)
        if plot_b and "error" not in plot_b:
            pdf.para(t["s_compare"], bold=True, color=ACCENT)
            pdf.para(f"{t['a']}: {_inputs_text(plot['inputs'])}\n{t['b']}: {_inputs_text(plot_b['inputs'])}", size=9, color=MUTED)
            labels = list(dict.fromkeys([i["label"] for i in plot["items"]] + [i["label"] for i in plot_b["items"]]))
            rows = []
            for lb in labels:
                va = next((i["value"] for i in plot["items"] if i["label"] == lb), "-")
                vb = next((i["value"] for i in plot_b["items"] if i["label"] == lb), "-")
                rows.append([lb + (f"  ({t['changed']})" if va != vb else ""), va, vb])
            pdf.table([t["item"], t["a"], t["b"]], rows, (64, 57, 57))
        for i in plot["items"] + (plot_b["items"] if plot_b and "error" not in plot_b else []):
            cites[(i["rule"], i["page"], i["quote"])] = rules[i["rule"]].title

    # ---- 4. fees
    for res, key in ((fee, "s_fee"), (dev, "s_dev")):
        if res and "error" not in res:
            pdf.h2(f"{n}. {t[key]}")
            n += 1
            pdf.para(f"{t['inputs']}: " + _inputs_text(res["inputs"]), size=9, color=MUTED)
            pdf.table([t["item"], t["value"], t["source"]], _items_rows(res["items"]), (78, 62, 38))
            if res.get("caveat"):
                pdf.para(f"{t['caveat']}: {res['caveat']}", size=8.5, color=MUTED)
            for i in res["items"]:
                cites[(i["rule"], i["page"], i["quote"])] = rules[i["rule"]].title

    # ---- 5. every rule passage used
    if cites:
        pdf.h2(f"{n}. {t['s_rules']}")
        for k, (rule, page, quote) in enumerate(sorted(cites, key=lambda c: (int(re.match(r"\d+", c[0]).group()), c[1])), 1):
            pdf.para(f"{k}. Rule {rule} · {cites[(rule, page, quote)]} · PDF p.{page}", size=8.8, bold=True, color=ACCENT)
            pdf.para(quote, size=8.5, color=MUTED, indent=5, h=4.4)
    return bytes(pdf.output())


def _pick(d: dict | None, keys: list[str]) -> dict:
    d = d or {}
    out = {}
    for k in keys:
        v = d.get(k)
        if v in ("", None):
            continue
        out[k] = v
    return out


def _inputs_text(inp: dict) -> str:
    names = {"plot_area_sqm": "plot {} sq m", "road_width_m": "road {} m", "frontage_m": "frontage {} m",
             "building_type": "{}", "proposed_height_m": "height {} m", "built_up_area_sqm": "built-up {} sq m",
             "use": "{}", "high_rise": "high-rise", "land_area_sqm": "land {} sq m", "zone": "{}", "population": "population {}"}
    parts = []
    for k, v in inp.items():
        if v in (None, "", False):
            continue
        fmt = names.get(k)
        if fmt:
            parts.append(fmt.format(f"{v:g}" if isinstance(v, float) else str(v).replace("_", " ")))
    return ", ".join(parts)
