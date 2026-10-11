"""Offline tests for input extraction / routing (app/router.py) and the figure check (app/support.py)."""
from app.router import plan
from app.rules import load_rules
from app.support import evidence_for, unsupported_figures

RULES = load_rules()


def tools(p):
    return [c["tool"] for c in p.calculations]


def test_headline_question_is_precomputed_in_one_go():
    p = plan("My plot is 200 sq m on a 9 m road. How much gap do I leave at the front, how many floors can I build, and what fee do I pay?")
    assert p.precomputed and tools(p) == ["residential_plot_norms", "building_permission_fee"]
    assert p.inputs["plot_area_sqm"] == 200 and p.inputs["road_width_m"] == 9
    assert p.calculations[1]["input"]["built_up_area_sqm"] == 250  # fee at max FAR area, flagged as an assumption
    assert "assumption" in p.calculations[1]["output"]


def test_hindi_question():
    p = plan("मेरा प्लॉट 200 वर्ग मीटर का है और सामने 9 मीटर चौड़ी सड़क है। आगे कितनी जगह खाली छोड़नी होगी?")
    assert p.precomputed and p.inputs == {"plot_area_sqm": 200, "road_width_m": 9}


def test_numbers_go_to_the_nearest_keyword():
    p = plan("My house faces a 10 m wide street and will be 9 m tall. How much open space do I leave at the front?")
    assert p.inputs["road_width_m"] == 10 and p.inputs["height_m"] == 9
    assert p.precomputed and "plot area" in p.missing  # front computed; plot area never invented
    p = plan("Fee for 180 sq m built-up house on a 150 sq m plot?")
    assert p.inputs["built_up_area_sqm"] == 180 and p.inputs["plot_area_sqm"] == 150


def test_how_far_is_not_a_far_question():
    assert "far" not in plan("How far must my balcony stay from a low-voltage overhead electric line?").intents
    assert "far" in plan("What is the FAR for a 300 sq m plot on a 12 m road?").intents


def test_units_converted_in_code():
    p = plan("My plot is 1500 sq ft on a 30 feet road. What setbacks apply?")
    assert p.inputs["plot_area_sqm"] == 139.35 and p.inputs["road_width_m"] == 9.14 and p.precomputed


def test_ambiguous_inputs_are_not_guessed():
    p = plan("I have a 30x40 plot on a 9 m road, front gap?")
    assert not p.precomputed and "feet or metres" in p.ambiguous[0]
    p = plan("Development fee for 3 acres?")
    assert not p.precomputed and "zone" in p.ambiguous[0]


def test_non_residential_and_no_calculation_questions_use_the_model_path():
    assert not plan("Front setback for a shop on a 200 sq m plot on a 12 m road?").precomputed
    assert not plan("I want a farm house on agricultural land. What is the minimum plot size and the maximum FAR?").precomputed
    assert not plan("What is the fee for building permission for a residential house?").precomputed  # input missing
    assert not plan("How do I pay my property tax online?").calculations


def test_follow_up_keeps_earlier_inputs():
    hist = [{"question": "My plot is 200 sq m on a 9 m road. How much gap do I leave at the front?", "answer": "3 m"}]
    p = plan("And if the road were 12 m wide instead?", hist)
    assert p.precomputed and p.inputs["plot_area_sqm"] == 200 and p.inputs["road_width_m"] == 12
    front = next(i for i in p.calculations[0]["output"]["items"] if i["label"].startswith("Front"))
    assert front["value"] == "3.6 m"


def test_development_fee_precomputed():
    p = plan("What is the development permission fee for 2.5 hectares of commercial land?")
    assert p.precomputed and p.calculations[0]["output"]["total_rs"] == 390000


def test_unsupported_figures_are_caught():
    p = plan("My plot is 200 sq m on a 9 m road. How much gap at the front?")
    cites = [{"rule": "56", "quote": "Up to 9.0 meters 3.0 meters", "verified": True}]
    ev = evidence_for(RULES, cites, p.calculations, "200 sq m 9 m road", [], [])
    assert unsupported_figures("Leave 3.0 m at the front and 2.5 m at the rear.", ev) == []
    assert unsupported_figures("Leave 3.3 m at the front; the fee is Rs 7,777; coverage 60%.", ev) == ["7777", "3.3", "60"]
