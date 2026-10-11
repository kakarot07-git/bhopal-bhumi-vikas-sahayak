"""Offline tests (no API key needed): rules loading, quote verification, calculators."""
from app.calculators import building_permission_fee, residential_plot_norms, self_check
from app.rules import load_rules, normalise_rule_id, verify_quote

RULES = load_rules()


def item(out, label_start):
    return next(i for i in out["items"] if i["label"].startswith(label_start))


def test_all_rules_loaded_and_headers_stripped():
    assert len(RULES) == 106 and "26-B" in RULES
    assert RULES["56"].page_at(RULES["56"].text.find("Rear Open Space")) == 78


def test_calculator_tables_match_official_text():
    assert self_check(RULES) == []


def test_quote_verification():
    ok = verify_quote(RULES, "Rule 52(1)", "Low and Medium voltage 2.5 1.2")
    assert ok.verified and ok.rule == "52" and ok.page == 69
    assert not verify_quote(RULES, "12", "plots up to 300 sq m need no permission at all").verified
    moved = verify_quote(RULES, "23", "Low and Medium voltage 2.5 1.2")  # right text, wrong rule number
    assert moved.verified and moved.rule == "52"
    # PDF hyphenates "built-\n up area" across a line break; a quote that rejoins it must still verify
    joined = verify_quote(RULES, "21", "for the Building Permission Rs 1.00 per Square meter of the proposed built-up area.")
    assert joined.verified and joined.rule == "21" and joined.page == 35


def test_rule_id_normalisation():
    assert normalise_rule_id("Rule 56(1)(a)") == "56"
    assert normalise_rule_id("26-B") == "26-B"
    assert normalise_rule_id("17-a") == "17"


def test_front_open_space_boundaries():
    for road, want in [(6, "3 m"), (9, "3 m"), (10, "3.6 m"), (12, "3.6 m"), (12.5, "4.5 m"), (18, "4.5 m"), (24, "6 m")]:
        assert item(residential_plot_norms(200, road), "Front open space")["value"] == want, road


def test_rear_open_space_boundaries():
    for area, want in [(40, "Nil"), (41, "1.5 m"), (150, "1.5 m"), (151, "2.5 m"), (225, "2.5 m"), (300, "3 m")]:
        assert item(residential_plot_norms(area, 9), "Rear open space")["value"] == want, area


def test_far_and_height_for_200sqm_9m_road():
    out = residential_plot_norms(200, 9, frontage_m=10)
    assert item(out, "Maximum FAR")["value"] == "1.25"
    assert item(out, "Maximum total built-up")["value"].startswith("250.0")
    assert any(a["clause"] == "2(5)(c)" for a in out["amendments"])  # plot <= 500 sq m


def test_tall_building_needs_table_4():
    small = residential_plot_norms(200, 9, proposed_height_m=15)
    assert small["warnings"] and "Table 4" in small["warnings"][0]
    big = residential_plot_norms(1200, 15, frontage_m=20, proposed_height_m=18)
    assert item(big, "Maximum FAR")["value"] == "1.5"
    assert item(big, "Front open space")["value"] == "7.5 m"


def test_fees():
    f = building_permission_fee(250)
    assert (f["application_fee_rs"], f["permission_fee_rs"], f["total_rs"]) == (250, 3000, 3250)
    assert building_permission_fee(75)["permission_fee_rs"] == 750
    assert building_permission_fee(75.5)["permission_fee_rs"] == 1250
    assert building_permission_fee(2600)["permission_fee_rs"] == 50000
    assert building_permission_fee(250, "commercial")["permission_fee_rs"] == 4500
    assert building_permission_fee(3000, high_rise=True)["permission_fee_rs"] == 30000
    assert building_permission_fee(3000, "commercial", high_rise=True)["permission_fee_rs"] == 60000


def test_development_fee():
    from app.calculators import development_permission_fee as dev
    f = dev(12000)  # 1.2 ha, residential zone, Bhopal (> 10 lakh)
    assert (f["application_fee_rs"], f["permission_fee_rs"], f["total_rs"]) == (10000, 90000, 100000)
    assert dev(10000)["application_fee_rs"] == 5000            # exactly 1 ha
    assert dev(10001)["application_fee_rs"] == 10000           # part of a hectare counts as a full hectare
    assert dev(10000, "commercial")["permission_fee_rs"] == 150000
    assert dev(10000, "commercial", "5_to_10_lakh")["permission_fee_rs"] == 125000
    assert dev(20000, "recreational_agriculture_other", "below_5_lakh")["permission_fee_rs"] == 20000
    assert "error" in dev(1000, "industrial_zone")
