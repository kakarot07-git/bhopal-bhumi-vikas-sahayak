"""Input validation for the Setback & FAR and Fee tabs.

Limits come from the rulebook where it states them:
  - building type vs plot size / frontage   (Rule 53(1) table, PDF p.70)
  - building height vs road width / plot / frontage   (Rule 56: up to 12.5 m; Rule 42 Tables 4 and 5)
Everything else is basic validity (a positive number; a frontage that leaves a plot at least 1 m deep).
Messages are returned in English and Hindi. The page calls /api/validate while the clerk types and
will not submit while any field is invalid; the calculators run the same checks.
"""

from __future__ import annotations

import math

from .calculators import TABLE_4, TABLE_5

# (min road, min plot, min frontage, max height in m) - Rule 42 Table 4 and Table 5, PDF p.58-59
_HEIGHT_STEPS = [(r[0], r[1], r[2], float(r[4])) for r in TABLE_4] + \
                [(r[0], r[1], r[2], float(r[4]) if r[4][0].isdigit() else math.inf) for r in TABLE_5]


def max_height(road_width_m: float, plot_area_sqm: float, frontage_m: float | None) -> tuple[float, str, tuple | None]:
    """Tallest building the rules allow for this road/plot/frontage, the rule that sets it,
    and the requirements of the next step up (road, plot, frontage, height) if there is one."""
    best, src = 12.5, "Rule 56"
    for road, plot, front, h in _HEIGHT_STEPS:
        if road_width_m >= road and plot_area_sqm >= plot and (frontage_m is None or frontage_m >= front):
            if h > best:
                best, src = h, f"Rule 42, Table {'4' if h <= 30 else '5'}"
    nxt = next(((r, p, f, h) for r, p, f, h in _HEIGHT_STEPS if h > best), None)
    return best, src, nxt


def _num(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "nan"
    return x if math.isfinite(x) else "nan"


def _need_positive(errors, field, value, required=True):
    if value is None:
        if required:
            errors[field] = ("Required.", "आवश्यक है।")
        return None
    if value == "nan" or value <= 0:
        errors[field] = ("Enter a number greater than 0.", "0 से बड़ी संख्या लिखें।")
        return None
    return value


def validate_plot(data: dict) -> dict:
    e: dict = {}
    area = _need_positive(e, "plot_area_sqm", _num(data.get("plot_area_sqm")))
    road = _need_positive(e, "road_width_m", _num(data.get("road_width_m")))
    front = _need_positive(e, "frontage_m", _num(data.get("frontage_m")), required=False)
    height = _need_positive(e, "proposed_height_m", _num(data.get("proposed_height_m")), required=False)
    btype = data.get("building_type") or None

    if area and front and area / front < 1:
        e["frontage_m"] = (f"Frontage {front:g} m is too large for a {area:g} sq m plot (plot depth would be under 1 m).",
                           f"{area:g} वर्ग मी के प्लॉट के लिए {front:g} मी फ्रंटेज बहुत अधिक है (गहराई 1 मी से कम होगी)।")

    if area and btype in ("detached", "semi_detached", "row"):
        # Rule 53(1) table: detached > 225 sq m & frontage > 12 m; semi-detached 125-225 & 8-12; row 50-225 & 4.5-12
        rng = {"detached": ((225, math.inf, False), (12, math.inf, False), "above 225 sq m, frontage above 12 m",
                            "225 वर्ग मी से अधिक, फ्रंटेज 12 मी से अधिक"),
               "semi_detached": ((125, 225, True), (8, 12, True), "125-225 sq m, frontage 8-12 m", "125-225 वर्ग मी, फ्रंटेज 8-12 मी"),
               "row": ((50, 225, True), (4.5, 12, True), "50-225 sq m, frontage 4.5-12 m", "50-225 वर्ग मी, फ्रंटेज 4.5-12 मी")}[btype]
        (alo, ahi, aincl), (flo, fhi, fincl), en, hi = rng
        area_ok = (alo <= area <= ahi) if aincl else (area > alo)
        front_ok = front is None or ((flo <= front <= fhi) if fincl else (front > flo))
        if not (area_ok and front_ok):
            name = {"detached": ("Detached", "डिटैच्ड"), "semi_detached": ("Semi-detached", "सेमी-डिटैच्ड"), "row": ("Row-type", "रो-टाइप")}[btype]
            e["building_type"] = (f"{name[0]} buildings need a plot of {en} (Rule 53).",
                                  f"{name[1]} भवन के लिए प्लॉट {hi} चाहिए (नियम 53)।")

    if height and area and road:
        hmax, src, nxt = max_height(road, area, front)
        if height > hmax:
            en = f"Maximum {hmax:g} m for this road, plot and frontage ({src})."
            hi = f"इस सड़क, प्लॉट और फ्रंटेज पर अधिकतम {hmax:g} मी ({src.replace('Rule', 'नियम')})।"
            if nxt:
                r, p, f, h = nxt
                hs = "Above 90 m" if math.isinf(h) else f"Up to {h:g} m"
                hh = "90 मी से अधिक" if math.isinf(h) else f"{h:g} मी तक"
                en += f" {hs} needs road {r:g} m+, plot {p:g} sq m+, frontage {f:g} m+ (Rule 42)."
                hi += f" {hh} के लिए सड़क {r:g} मी+, प्लॉट {p:g} वर्ग मी+, फ्रंटेज {f:g} मी+ चाहिए (नियम 42)।"
            e["proposed_height_m"] = (en, hi)
    return _result(e)


def validate_fee(data: dict) -> dict:
    e: dict = {}
    _need_positive(e, "built_up_area_sqm", _num(data.get("built_up_area_sqm")))
    if data.get("use") not in (None, "", "residential", "commercial", "shop_cum_residence", "social_educational", "factory_admin_block"):
        e["use"] = ("Choose a use from the list.", "सूची से उपयोग चुनें।")
    return _result(e)


def validate_devfee(data: dict) -> dict:
    e: dict = {}
    _need_positive(e, "land_area_sqm", _num(data.get("land_area_sqm")))
    return _result(e)


def _result(errors: dict) -> dict:
    return {"valid": not errors,
            "errors": {k: {"en": v[0], "hi": v[1]} for k, v in errors.items()}}
