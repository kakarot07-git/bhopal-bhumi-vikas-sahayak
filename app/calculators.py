"""Deterministic calculators for the numbers clerks are asked about most.

Every number here comes from a table in the official PDF. Each table entry carries
the rule, the PDF page and a short verbatim quote of the table row. `self_check()`
verifies every quote against the rules text at start-up, so a typo in these tables
is caught before the clerk ever sees it.

Maths happens here, in code - never in the language model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .amendments import amendments_for_plot
from .rules import Rule, verify_quote


@dataclass
class Item:
    label: str
    value: str
    rule: str
    page: int
    quote: str  # verbatim row from the official text (checked by self_check)
    note: str = ""

    def to_dict(self):
        return asdict(self)


# ------------------------------------------------------------------ tables

# Rule 56(1)(a), PDF p.77 - front open space, residential buildings up to 12.5 m height
FRONT_OPEN_SPACE = [  # (road width upper bound inclusive, metres, quote)
    (9.0, 3.0, "Up to 9.0 meters 3.0 meters"),
    (12.0, 3.6, "More than 9.0 meters and up to 12 meters 3.6 meters"),
    (18.0, 4.5, "More than 12.0 meters and up to 18 meters 4.5 meters"),
    (math.inf, 6.0, "Above 18 meters 6.0 meters"),
]

# Rule 56(2)(a), PDF p.78 - rear open space, residential buildings up to 12.5 m height
REAR_OPEN_SPACE = [  # (plot area upper bound inclusive, metres, quote)
    (40.0, 0.0, "Up to 40.00 Nil"),
    (150.0, 1.5, "Above 40.00 and up to 150.00 1.50"),
    (225.0, 2.5, "Above 150 and up to 225.00 2.50"),
    (math.inf, 3.0, "Above 225.00 3.00"),
]

# Rule 42 Table 4, PDF p.58 - buildings above 12.5 m and up to 30 m
# (min road, min plot, min frontage, FAR, max height, front MOS, side/rear MOS, quote)
TABLE_4 = [
    (12.0, 1000, 18, 1.50, 18, 7.5, 6.0, "1000 sq. 18 m. 1:1.50"),
    (18.0, 1500, 21, 1.75, 24, 9.0, 6.0, "1500 sq. 21 m. 1:1.75"),
    (24.0, 2000, 30, 2.00, 30, 12.0, 7.5, "2000 sq. 30 m. 1:2.0"),
]

# Rule 42 Table 5, PDF p.59 - high rise buildings (ground coverage 30%)
TABLE_5 = [
    (30.0, 2500, 30, 2.25, "45", 15.0, 7.5, "2500 30 m. 1:2.25 30 Up to 45 15.00 m. 7.5 m."),
    (36.0, 3000, 40, 2.50, "60", 18.0, 9.0, "3000 40 m. 1:2.50 30 Up to 60 18.00 m. 9.0 m."),
    (45.0, 3500, 45, 2.75, "75", 21.0, 9.0, "3500 45 m. 1:2.75 30 Up to 75 21 m. 9 m."),
    (60.0, 4000, 50, 3.00, "90", 24.0, 10.0, "4000 50 m. 1:3.0 30 Up to 90 24.00 10 m."),
    (75.0, 4500, 60, 3.00, "above 90", 30.0, 12.0, "4500 60 m. 1:3.0 30 Above 30.00 12 m."),
]

# Rule 21(3)(b), PDF p.36 - building permission fee, residential (not high rise)
RESIDENTIAL_FEE_SLABS = [  # (built-up upper bound sq m, fee Rs, quote)
    (75, 750, "used 0 75 750"),
    (125, 1250, "76 125 1,250"),
    (200, 2000, "126 200 2,000"),
    (300, 3000, "201 300 3,000"),
    (400, 4000, "301 400 4,000"),
    (600, 6000, "401 600 6,000"),
    (750, 7500, "601 750 7,500"),
    (1000, 10000, "751 1,000 10,000"),
    (1250, 12500, "1,001 1,250 12,500"),
    (1500, 15000, "1,251 1,500 15,000"),
    (2000, 20000, "1,501 2,000 20,000"),
    (2500, 25000, "2,001 2,500 25,000"),
    (math.inf, 50000, "above 2500 50,000"),
]

# Use types for fees: multiplier on the residential slab fee (Rule 21(3)(b) items 1-6)
FEE_USES = {
    "residential": (1.0, "1", "exclusively as residence 76 125 1,250"),
    "commercial": (1.5, "2", "store house, factory or carrying on trade"),
    "shop_cum_residence": (1.5, "4", "cum residence purpose"),
    "factory_admin_block": (1.0, "3", "administrative block in a factory"),
    "social_educational": (1.0, "6", "Social, Charitable, culture, Educational"),
}
# Rule 21(3)(c), PDF p.37 - high rise: Rs 10 per sq m (residential); commercial +100%; shop-cum-residence +50%
HIGH_RISE_FEE = {
    "residential": (1.0, "Rs. 10.00 per square meter of the"),
    "commercial": (2.0, "with additional charges of 100% of"),
    "shop_cum_residence": (1.5, "together with additional charges of 50% of such amount of fees"),
    "factory_admin_block": (1.0, "administrative block in a factory"),
    "social_educational": (1.0, "educational purpose including hospital, school, club"),
}

# Short quotes used by calculators (also self-checked)
Q_FAR_RES = ("61", 83, "Resdential 1.25")  # sic - the PDF spells it "Resdential"
Q_FAR_DP = ("61", 83, "F.A.R and Density may be adopted as provided in the Development Plans of respective towns")
Q_PREMIUM = ("61", 84, "shall not exceed 25% of the Base FAR")
Q_TABLE4_SCOPE = ("42", 58, "Planning Norms for the buildings having height above 12.5 meters and up to 30 meters shall be as given in Table No 4")
Q_HEIGHT_RULE = ("65", 85, "The maximum height of a building shall be determined by the provision of Table No. 4 and 5 of Rule No. 42")
Q_CORNER = ("65", 86, "the building shall be deemed to face such street which has greater width")
Q_SIDE_DETACHED = ("56", 78, "For detached buildings there shall be minimum side open spaces of 3 meters on both the sides")
Q_SIDE_DETACHED_PROVISO = ("56", 78, "for detached residential building up to 7 meters in height on plots with a frontage less than 12 meters, one of the sides open space may be reduced to 1.5 meters")
Q_SIDE_SEMI = ("56", 78, "For semi-detached building there shall be a minimum side open space of 3.0 meters on one side")
Q_SIDE_SEMI_PROVISO = ("56", 78, "For Semi-detached building up to 10 meters in height on plots with a frontage up to 10 meters, the side open space may be reduced to 2.5 meters")
Q_SIDE_ROW = ("56", 78, "For row-type buildings, no side open space is required")
Q_NARROW_STREET = ("56", 77, "In existing developed areas with streets less than 6.0 meters in width, the distances of the building (building line) shall be at 6.0 meters from the center line of the street")
Q_PLOT_TYPES = ("53", 70, "Detached building above 225 above 12")
Q_PLOT_SEMI = ("53", 70, "Semi-detached building 125-225 8 to 12")
Q_PLOT_ROW = ("53", 70, "Row type building 50-225 4.5 to 12")
Q_APP_FEE = ("21", 35, "for the Building Permission Rs 1.00 per Square meter of the proposed built- up area")
Q_APP_FEE_DEV = ("21", 35, "for the Development Permission Rs. 5000 per hectare or part thereof")
Q_DEV_FEE_SCOPE = ("21", 35, "the permission fee for development of any land shall be as under")

# Rule 21(3)(a), PDF p.35 - development permission fee in Rs per hectare,
# by land use zone and population of the planning area (> 10 lakh, 5-10 lakh, < 5 lakh)
DEV_FEE_PER_HA = {
    "residential_psp_industrial_transport": ((75000, 50000, 25000), "Residential or Public and, 75,000 50,000 25,000"),
    "commercial": ((150000, 125000, 100000), "Commercial 1,50,000 1,25,000 1,00,000"),
    "recreational_agriculture_other": ((30000, 20000, 10000), "Recreational or agriculture 30,000 20,000 10,000"),
}
DEV_ZONE_LABELS = {
    "residential_psp_industrial_transport": "Residential / Public and semi-public / Industrial / Transportation",
    "commercial": "Commercial",
    "recreational_agriculture_other": "Recreational / Agriculture / Other",
}
POPULATION_BANDS = {"above_10_lakh": 0, "5_to_10_lakh": 1, "below_5_lakh": 2}
POPULATION_LABELS = {"above_10_lakh": "more than 10 lakh", "5_to_10_lakh": "5 to 10 lakh", "below_5_lakh": "less than 5 lakh"}
Q_POP_BANDS = ("21", 35, "More than 10 5 to 10 Less than 5")
Q_HIGH_RISE_DEF = ("2", 9, "which consists of more than ten stories; or")
Q_PARKING = ("61", 84, "Such area of parking shall not be counted towards Floor Area Ratio and permissible height calculations")


def _all_quotes():
    for _, _, q in FRONT_OPEN_SPACE:
        yield "56", q
    for _, _, q in REAR_OPEN_SPACE:
        yield "56", q
    for row in TABLE_4:
        yield "42", row[-1]
    for row in TABLE_5:
        yield "42", row[-1]
    for _, _, q in RESIDENTIAL_FEE_SLABS:
        yield "21", q
    for _, _, q in FEE_USES.values():
        yield "21", q
    for _, q in DEV_FEE_PER_HA.values():
        yield "21", q
    for _, q in HIGH_RISE_FEE.values():
        yield "21", q
    for name, val in globals().items():
        if name.startswith("Q_"):
            yield val[0], val[2]


def self_check(rules: dict[str, Rule]) -> list[str]:
    """Return a list of problems (empty = every encoded table row matches the official text)."""
    problems = []
    for rule_id, q in _all_quotes():
        chk = verify_quote(rules, rule_id, q)
        if not chk.verified or chk.rule != rule_id:
            problems.append(f"Rule {rule_id}: quote not found in official text: {q!r}")
    return problems


# ------------------------------------------------------------------ helpers

def _fmt_m(x: float) -> str:
    return "Nil" if x == 0 else f"{x:g} m"


def _rs(x: float) -> str:
    """Indian digit grouping: 125000 -> 'Rs 1,25,000'."""
    n = int(math.floor(x + 0.5))  # round half up (Python's round() would turn 312.5 into 312)
    s = str(n)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"Rs {s}"


def front_open_space(road_width: float) -> tuple[float, str]:
    for upper, metres, q in FRONT_OPEN_SPACE:
        if road_width <= upper:
            return metres, q
    raise AssertionError


def rear_open_space(plot_area: float) -> tuple[float, str]:
    for upper, metres, q in REAR_OPEN_SPACE:
        if plot_area <= upper:
            return metres, q
    raise AssertionError


def building_type_options(plot_area: float, frontage: float | None) -> list[str]:
    """Rule 53(1) table: which building types the plot size/frontage allows."""
    opts = []
    if plot_area > 225 and (frontage is None or frontage > 12):
        opts.append("detached")
    if 125 <= plot_area <= 225 and (frontage is None or 8 <= frontage <= 12):
        opts.append("semi_detached")
    if 50 <= plot_area <= 225 and (frontage is None or 4.5 <= frontage <= 12):
        opts.append("row")
    return opts


# ------------------------------------------------------------------ calculators

def residential_plot_norms(
    plot_area_sqm: float,
    road_width_m: float,
    frontage_m: float | None = None,
    building_type: str | None = None,
    proposed_height_m: float | None = None,
) -> dict:
    """Setbacks, FAR, maximum built-up area and height for a residential plot."""
    items: list[Item] = []
    warnings: list[str] = []
    if plot_area_sqm <= 0 or road_width_m <= 0:
        return {"error": "Plot area and road width must be positive numbers."}

    # Height regime -----------------------------------------------------------
    t4 = [r for r in TABLE_4 if road_width_m >= r[0] and plot_area_sqm >= r[1] and (frontage_m is None or frontage_m >= r[2])]
    t5 = [r for r in TABLE_5 if road_width_m >= r[0] and plot_area_sqm >= r[1] and (frontage_m is None or frontage_m >= r[2])]
    tall_allowed = bool(t4)
    wants_tall = proposed_height_m is not None and proposed_height_m > 12.5

    if wants_tall and not tall_allowed:
        warnings.append(
            f"A building above 12.5 m needs at least a 12 m road and a 1000 sq m plot with 18 m frontage "
            f"(Rule 42, Table 4). This plot ({plot_area_sqm:g} sq m, {road_width_m:g} m road) does not qualify, "
            f"so the height stays within 12.5 m."
        )

    if wants_tall and tall_allowed:
        if proposed_height_m > 30 and t5:
            r = t5[-1]
            items += [
                Item("Regime", "High-rise building (Rule 42, Table 5)", "42", 59, r[-1]),
                Item("Maximum FAR", f"{r[3]:g}", "42", 59, r[-1]),
                Item("Maximum building height", f"up to {r[4]} m" if r[4][0].isdigit() else f"{r[4]} m", "42", 59, r[-1]),
                Item("Ground coverage (max)", "30%", "42", 59, r[-1]),
                Item("Front open space (MOS)", _fmt_m(r[5]), "42", 59, r[-1]),
                Item("Side and rear open space (MOS)", _fmt_m(r[6]), "42", 59, r[-1]),
            ]
            far = r[3]
        else:
            if proposed_height_m > 30:
                warnings.append("Above 30 m needs Table 5 (road 30 m+, plot 2500 sq m+). Showing the best Table 4 row instead.")
            r = t4[-1]
            items += [
                Item("Regime", "Building above 12.5 m and up to 30 m (Rule 42, Table 4)", "42", 58, Q_TABLE4_SCOPE[2]),
                Item("Maximum FAR", f"{r[3]:g}", "42", 58, r[-1]),
                Item("Maximum building height", f"up to {r[4]} m", "42", 58, r[-1]),
                Item("Front open space (MOS)", _fmt_m(r[5]), "42", 58, r[-1]),
                Item("Side and rear open space (MOS)", _fmt_m(r[6]), "42", 58, r[-1]),
            ]
            far = r[3]
        max_height = None
    else:
        # Up to 12.5 m: Rule 56 setbacks, Rule 61 FAR
        front, fq = front_open_space(road_width_m)
        rear, rq = rear_open_space(plot_area_sqm)
        items.append(Item("Regime", "Residential building up to 12.5 m height (Rule 56 open spaces)", "56", 77,
                          "Every Residential Building having height up to 12.5 meters, facing street shall have a front open space"))
        items.append(Item("Front open space (min)", _fmt_m(front), "56", 77, fq,
                          note=f"Road width {road_width_m:g} m."))
        if road_width_m < 6:
            items.append(Item("Narrow street (< 6 m), existing developed area", "Building line 6 m from street centre line",
                              "56", 77, Q_NARROW_STREET[2]))
        items.append(Item("Rear open space (min)", _fmt_m(rear), "56", 78, rq, note=f"Plot area {plot_area_sqm:g} sq m."))

        # side open space by building type
        opts = building_type_options(plot_area_sqm, frontage_m)
        btype = building_type or (opts[0] if len(opts) == 1 else None)
        h = proposed_height_m
        if btype == "detached":
            if frontage_m is not None and frontage_m < 12 and h is not None and h <= 7:
                items.append(Item("Side open space (min)", "3 m on one side, 1.5 m on the other", "56", 78, Q_SIDE_DETACHED_PROVISO[2]))
            else:
                items.append(Item("Side open space (min)", "3 m on both sides", "56", 78, Q_SIDE_DETACHED[2],
                                  note="One side may be 1.5 m if height is up to 7 m and frontage is under 12 m."))
        elif btype == "semi_detached":
            if frontage_m is not None and frontage_m <= 10 and h is not None and h <= 10:
                items.append(Item("Side open space (min)", "2.5 m on one side", "56", 78, Q_SIDE_SEMI_PROVISO[2]))
            else:
                items.append(Item("Side open space (min)", "3 m on one side", "56", 78, Q_SIDE_SEMI[2],
                                  note="May be 2.5 m if height is up to 10 m and frontage is up to 10 m."))
        elif btype == "row":
            items.append(Item("Side open space (min)", "None required (row-type)", "56", 78, Q_SIDE_ROW[2]))
        else:
            names = {"detached": "detached", "semi_detached": "semi-detached", "row": "row-type"}
            allowed = ", ".join(names[o] for o in opts) or "none of the standard types (check Appendix-J for EWS/LIG)"
            items.append(Item("Side open space (min)", f"Depends on building type. Plot size allows: {allowed}. "
                              "Detached: 3 m both sides. Semi-detached: 3 m one side. Row-type: none.",
                              "56", 78, Q_SIDE_DETACHED[2]))
        if opts:
            items.append(Item("Building types allowed by plot size", ", ".join(o.replace("_", "-") for o in opts), "53", 70,
                              Q_PLOT_TYPES[2] if "detached" in opts else (Q_PLOT_SEMI[2] if "semi_detached" in opts else Q_PLOT_ROW[2])))

        far = 1.25
        items.append(Item("Maximum FAR (residential)", "1.25", "61", 83, Q_FAR_RES[2],
                          note="The Development Plan of the town may set a different FAR (Table 8 footnote)."))
        max_height = 12.5
        items.append(Item("Maximum building height", "12.5 m (taller needs Rule 42 Table 4: 12 m+ road, 1000 sq m+ plot)",
                          "42", 58, Q_TABLE4_SCOPE[2]))

    # Built-up area and indicative floors -------------------------------------
    max_built_up = far * plot_area_sqm
    items.append(Item("Maximum total built-up area (all floors)", f"{max_built_up:,.1f} sq m",
                      "61", 83, Q_FAR_RES[2] if far == 1.25 else Q_TABLE4_SCOPE[2],
                      note=f"= FAR {far:g} x plot area {plot_area_sqm:g} sq m. Covered parking (plots 200 sq m+) is not counted (Rule 61 note 4)."))

    floors = None
    if max_height is not None and frontage_m and frontage_m > 0:
        depth = plot_area_sqm / frontage_m
        front, _ = front_open_space(road_width_m)
        rear, _ = rear_open_space(plot_area_sqm)
        btype = building_type or (building_type_options(plot_area_sqm, frontage_m) or [None])[0]
        side_total = {"detached": 6.0, "semi_detached": 3.0, "row": 0.0}.get(btype or "", 3.0)
        fp_w, fp_d = frontage_m - side_total, depth - front - rear
        if fp_w > 0 and fp_d > 0:
            footprint = fp_w * fp_d
            by_far = max_built_up / footprint
            by_height = math.floor(max_height / 3.0)
            floors = {
                "footprint_sqm": round(footprint, 1),
                "floors_by_far": round(by_far, 2),
                "floors_by_height_at_3m": by_height,
                "assumptions": f"Rectangular plot {frontage_m:g} m x {depth:.1f} m, {btype or 'semi-detached'} layout, "
                               f"full footprint used on every floor, 3 m floor-to-floor height.",
            }
            n = min(math.floor(by_far + 1e-9), by_height)
            items.append(Item("Indicative number of floors (calculation, not a rule)",
                              f"about {n} full floor(s) at max footprint ({footprint:,.1f} sq m); "
                              f"FAR allows {by_far:.2f} footprints in total; height allows {by_height} floors of 3 m",
                              "61", 83, Q_FAR_RES[2],
                              note="The rules do not state a number of floors. Floors are limited by FAR and height. "
                                   "A smaller footprint per floor allows more floors within the same FAR."))
        else:
            warnings.append("The open spaces leave no buildable footprint for these dimensions. Check the inputs.")

    # Amendments that may apply ----------------------------------------------
    amendments = amendments_for_plot(plot_area_sqm)

    return {
        "inputs": {"plot_area_sqm": plot_area_sqm, "road_width_m": road_width_m, "frontage_m": frontage_m,
                   "building_type": building_type, "proposed_height_m": proposed_height_m},
        "items": [i.to_dict() for i in items],
        "floors": floors,
        "warnings": warnings,
        "amendments": amendments,
        "caveat": "FAR, density and setbacks may be modified by the Development Plan of the town (Rule 61 Table 8 footnote; Rule 103).",
    }


def building_permission_fee(built_up_area_sqm: float, use: str = "residential", high_rise: bool = False) -> dict:
    """Application fee (Rule 21(2)) + permission fee (Rule 21(3)(b) or (c))."""
    if built_up_area_sqm <= 0:
        return {"error": "Built-up area must be a positive number."}
    if use not in FEE_USES:
        return {"error": f"Unknown use '{use}'. Use one of: {', '.join(FEE_USES)}."}
    items: list[Item] = []

    app_fee = 1.0 * built_up_area_sqm
    items.append(Item("Application fee (paid with application, not refundable)", _rs(app_fee), "21", 35, Q_APP_FEE[2],
                      note=f"Rs 1 x {built_up_area_sqm:g} sq m proposed built-up area."))

    if high_rise:
        mult, q = HIGH_RISE_FEE[use]
        fee = 10.0 * built_up_area_sqm * mult
        items.append(Item("Permission fee (high-rise)", _rs(fee), "21", 37, q,
                          note=f"Rs 10 x {built_up_area_sqm:g} sq m" + (f" x {mult:g}" if mult != 1 else "") + "."))
    else:
        base, slab_q = None, None
        for upper, rs, q in RESIDENTIAL_FEE_SLABS:
            if built_up_area_sqm <= upper:
                base, slab_q = rs, q
                break
        mult, item_no, use_q = FEE_USES[use]
        fee = base * mult
        items.append(Item("Residential slab fee", _rs(base), "21", 36, slab_q,
                          note=f"Built-up area {built_up_area_sqm:g} sq m falls in this slab. "
                               "The table lists whole numbers (e.g. 0-75, 76-125); areas in between are read as 'above 75 up to 125'."))
        if mult != 1:
            items.append(Item(f"Permission fee for this use (item {item_no}: +50%)", _rs(fee), "21", 36, use_q,
                              note=f"{_rs(base)} + 50% = {_rs(fee)}."))
        else:
            items.append(Item(f"Permission fee (item {item_no})", _rs(fee), "21", 36, use_q))

    total = app_fee + fee
    items.append(Item("Total payable to the Authority (application + permission fee)", _rs(total), "21", 35, Q_APP_FEE[2]))
    return {
        "inputs": {"built_up_area_sqm": built_up_area_sqm, "use": use, "high_rise": high_rise},
        "items": [i.to_dict() for i in items],
        "application_fee_rs": app_fee,
        "permission_fee_rs": fee,
        "total_rs": total,
        "caveat": "Fees under Rule 21 only. Other charges levied by the Municipal Corporation (e.g. under municipal law) are not covered by these rules.",
    }


def development_permission_fee(land_area_sqm: float, zone: str = "residential_psp_industrial_transport",
                               population: str = "above_10_lakh") -> dict:
    """Application fee (Rule 21(2)(i)) + development permission fee (Rule 21(3)(a))."""
    if land_area_sqm <= 0:
        return {"error": "Land area must be a positive number."}
    if zone not in DEV_FEE_PER_HA:
        return {"error": f"Unknown land use zone '{zone}'. Use one of: {', '.join(DEV_FEE_PER_HA)}."}
    if population not in POPULATION_BANDS:
        return {"error": f"Unknown population band '{population}'. Use one of: {', '.join(POPULATION_BANDS)}."}
    hectares = land_area_sqm / 10000.0
    items: list[Item] = []

    billed_ha = math.ceil(hectares - 1e-9)  # "per hectare or part thereof"
    app_fee = 5000.0 * billed_ha
    items.append(Item("Land area", f"{land_area_sqm:,.0f} sq m = {hectares:.4g} hectare", "21", 35, Q_APP_FEE_DEV[2],
                      note="1 hectare = 10,000 sq m."))
    items.append(Item("Application fee (paid with application, not refundable)", _rs(app_fee), "21", 35, Q_APP_FEE_DEV[2],
                      note=f"Rs 5,000 x {billed_ha} hectare(s). Part of a hectare counts as a full hectare ('or part thereof')."))

    rates, q = DEV_FEE_PER_HA[zone]
    rate = rates[POPULATION_BANDS[population]]
    fee = rate * hectares
    items.append(Item("Permission fee rate", f"{_rs(rate)} per hectare", "21", 35, q,
                      note=f"Zone: {DEV_ZONE_LABELS[zone]}. Planning area population: {POPULATION_LABELS[population]}."))
    items.append(Item("Development permission fee", _rs(fee), "21", 35, q,
                      note=f"{_rs(rate)} x {hectares:.4g} ha. The table gives a rate per hectare without 'or part thereof', "
                           "so it is applied in proportion to the area. Check locally whether part-hectares are rounded up."))
    total = app_fee + fee
    items.append(Item("Total payable to the Authority (application + permission fee)", _rs(total), "21", 35, Q_DEV_FEE_SCOPE[2]))
    return {
        "inputs": {"land_area_sqm": land_area_sqm, "zone": zone, "population": population},
        "items": [i.to_dict() for i in items],
        "application_fee_rs": app_fee,
        "permission_fee_rs": fee,
        "total_rs": total,
        "caveat": "Rule 21(3)(a) applies to applications under section 29(1) of the Act (not section 29(3)). "
                  "Bhopal's planning area has a population above 10 lakh. Other charges outside Rule 21 are not included.",
    }


def case_summary(
    plot_area_sqm: float,
    road_width_m: float,
    frontage_m: float | None = None,
    building_type: str | None = None,
    proposed_height_m: float | None = None,
    use: str = "residential",
    built_up_area_sqm: float | None = None,
) -> dict:
    """One-click case summary: setbacks, FAR, height, built-up area and building permission fee
    for one plot, with every citation in one list. Nothing here is AI - all numbers come from the
    same table-checked calculators."""
    plot = residential_plot_norms(plot_area_sqm, road_width_m, frontage_m, building_type, proposed_height_m)
    if "error" in plot:
        return plot
    far_item = next((i for i in plot["items"] if i["label"].startswith("Maximum FAR")), None)
    far = float(far_item["value"]) if far_item else 1.25
    max_built_up = round(far * plot_area_sqm, 2)
    assumed = built_up_area_sqm is None
    area_for_fee = max_built_up if assumed else built_up_area_sqm
    high_rise = bool(proposed_height_m and proposed_height_m > 30)
    fee = building_permission_fee(area_for_fee, use, high_rise)
    if "error" in fee:
        return fee

    warnings = list(plot["warnings"])
    if not assumed and built_up_area_sqm > max_built_up + 1e-6:
        warnings.append(f"Proposed built-up area {built_up_area_sqm:g} sq m is more than the maximum "
                        f"{max_built_up:g} sq m allowed by FAR {far:g} (Rule 61).")

    def section(title, items):
        return {"title": title, "items": items}

    setback_items = [i for i in plot["items"] if "open space" in i["label"].lower() or i["label"].startswith(("Building types", "Narrow street"))]
    limit_items = [i for i in plot["items"] if i not in setback_items]
    fee_items = fee["items"]
    if assumed:
        fee_items = [dict(fee_items[0], note=fee_items[0]["note"] + f" Assumes the full permitted built-up area ({area_for_fee:g} sq m); enter the proposed area for the exact fee.")] + fee_items[1:]

    citations, seen = [], set()
    for i in plot["items"] + fee["items"]:
        key = (i["rule"], i["quote"])
        if key not in seen:
            seen.add(key)
            citations.append({"rule": i["rule"], "page": i["page"], "quote": i["quote"]})

    return {
        "inputs": {**plot["inputs"], "use": use, "built_up_area_sqm": built_up_area_sqm},
        "headline": {
            "front_open_space": next((i["value"] for i in plot["items"] if i["label"].startswith("Front open space")), None),
            "rear_open_space": next((i["value"] for i in plot["items"] if i["label"].startswith("Rear open space")), None),
            "far": far,
            "max_built_up_sqm": max_built_up,
            "max_height": next((i["value"] for i in plot["items"] if i["label"].startswith("Maximum building height")), None),
            "total_fee_rs": fee["total_rs"],
            "fee_built_up_sqm": area_for_fee,
            "fee_assumed_max": assumed,
        },
        "sections": [
            section("Open spaces (setbacks)", setback_items),
            section("FAR, height and built-up area", limit_items),
            section("Building permission fee (Rule 21)", fee_items),
        ],
        "citations": sorted(citations, key=lambda c: (int(c["rule"].split("-")[0]), c["page"])),
        "floors": plot["floors"],
        "warnings": warnings,
        "amendments": plot["amendments"],
        "caveat": plot["caveat"] + " " + fee["caveat"],
    }
