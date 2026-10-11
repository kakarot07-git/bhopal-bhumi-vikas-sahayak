"""Offline tests: input limits (app/validate.py), answer cache (app/cache.py), PDF report (app/report.py)."""
from app.cache import AnswerCache
from app.report import build_report
from app.rules import load_rules
from app.validate import max_height, validate_devfee, validate_fee, validate_plot

RULES = load_rules()


def test_basic_validity():
    assert validate_plot({"plot_area_sqm": 200, "road_width_m": 9})["valid"]
    bad = validate_plot({"plot_area_sqm": -5, "road_width_m": "abc", "frontage_m": 0})
    assert set(bad["errors"]) == {"plot_area_sqm", "road_width_m", "frontage_m"}
    assert not validate_plot({"plot_area_sqm": 200})["valid"]                       # road width required
    assert "under 1 m" in validate_plot({"plot_area_sqm": 200, "road_width_m": 9, "frontage_m": 300})["errors"]["frontage_m"]["en"]
    assert not validate_fee({"built_up_area_sqm": 0})["valid"]
    assert not validate_devfee({"land_area_sqm": None})["valid"]


def test_height_limits_from_rule_42():
    assert max_height(9, 200, None)[0] == 12.5          # Rule 56: up to 12.5 m
    assert max_height(12, 1000, 18)[0] == 18            # Table 4 row 1
    assert max_height(12, 1000, 10)[0] == 12.5          # frontage too small for Table 4
    assert max_height(30, 2500, 30)[0] == 45            # Table 5 row 1
    e = validate_plot({"plot_area_sqm": 200, "road_width_m": 9, "proposed_height_m": 15})["errors"]["proposed_height_m"]
    assert "12.5" in e["en"] and "Rule 42" in e["en"] and "नियम" in e["hi"]
    assert validate_plot({"plot_area_sqm": 1200, "road_width_m": 15, "frontage_m": 20, "proposed_height_m": 18})["valid"]


def test_building_type_limits_from_rule_53():
    assert "Rule 53" in validate_plot({"plot_area_sqm": 200, "road_width_m": 9, "building_type": "detached"})["errors"]["building_type"]["en"]
    assert validate_plot({"plot_area_sqm": 200, "road_width_m": 9, "building_type": "semi_detached"})["valid"]
    assert not validate_plot({"plot_area_sqm": 200, "road_width_m": 9, "frontage_m": 15, "building_type": "semi_detached"})["valid"]
    assert not validate_plot({"plot_area_sqm": 40, "road_width_m": 9, "building_type": "row"})["valid"]


def test_answer_cache(tmp_path):
    c = AnswerCache("fp1", path=tmp_path / "a.jsonl")
    good = {"status": "answered", "answer": "3 m", "meta": {}}
    c.put("Front gap for 200 sq m?", [], good)
    assert c.get("  front gap for 200 SQ M  ", []) == good                  # normalised question
    assert c.get("Front gap for 200 sq m?", [{"question": "x", "answer": "y"}]) is None   # different conversation
    c.put("bad one", [], {"status": "unverified"})
    assert c.get("bad one", []) is None                                       # unverified answers never cached
    assert AnswerCache("fp1", path=tmp_path / "a.jsonl").get("Front gap for 200 sq m?", []) == good   # survives restart
    assert AnswerCache("fp2", path=tmp_path / "a.jsonl").get("Front gap for 200 sq m?", []) is None   # rules/model changed


def test_report_pdf_recomputes_and_reverifies():
    turn = {"question": "Front gap on a 9 m road?", "answer": {"status": "answered", "answer": "3.0 m (Rule 56).",
            "citations": [{"rule": "56", "quote": "Up to 9.0 meters 3.0 meters"}, {"rule": "56", "quote": "invented text that is not in the rules"}]}}
    data = {"lang": "en", "conversations": [[turn]], "plot": {"plot_area_sqm": 200, "road_width_m": 9},
            "fee": {"built_up_area_sqm": 250, "use": "residential", "high_rise": False}}
    pdf = build_report(data, RULES)
    assert pdf[:5] == b"%PDF-" and len(pdf) > 10000
    assert build_report({"lang": "hi"}, RULES)[:5] == b"%PDF-"   # empty session still gives a valid PDF
