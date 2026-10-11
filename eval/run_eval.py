"""Run the 17 sample questions through the assistant and score the answers.

    python -m eval.run_eval            # all questions
    python -m eval.run_eval 1 14 16    # only some ids
    python -m eval.run_eval --regrade  # re-score saved results.json after editing gold.json (no API calls)

A question passes when ALL of these hold:
  - status: "not_found" for out-of-scope questions; answered/partial for the rest
  - rule:   at least one expected rule is among the VERIFIED citations
  - facts:  every key number/term (regex) appears in the answer
  - lang:   Hindi questions get a Hindi (Devanagari) answer
  - quotes: every citation verified against the official text (reported, and required)
  - amendment: flagged when expected (Q11)
  - no_gap_filling: "not found" answers carry no citations and no outside advice (offices, portals, rates)

Writes eval/results.json and eval/REPORT.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("BVS_CACHE", "0")  # measure real answers, not the answer cache

from app.assistant import MAX_TOKENS, Assistant  # noqa: E402
from app.rules import load_rules

HERE = Path(__file__).resolve().parent
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
GAP_FILL = re.compile(r"\b(office|portal|department|website|section of|registr\w*|collector|guideline rate|contact|visit|please send|approach|helpline)\b", re.I)


def grade(g: dict, a: dict) -> dict:
    checks = {}
    answer = a.get("answer", "")
    if g["expect_status"] == "not_found":
        checks["status"] = a["status"] == "not_found"
        # no gap-filling: a "not found" answer must not point to offices, portals, procedures or rates
        checks["no_gap_filling"] = not GAP_FILL.search(answer) and not a.get("citations")
    else:
        checks["status"] = a["status"] in ("answered", "partial")
    if g["rules_any"]:
        cited = set(a.get("cited_rules", []))
        checks["rule"] = any(set(opt) <= cited for opt in g["rules_any"])
    checks["facts"] = all(re.search(p, answer, re.I) for p in g["facts"])
    if g["lang"] == "hi":
        checks["lang"] = bool(DEVANAGARI.search(answer))
    cites = a.get("citations", [])
    checks["quotes_verified"] = all(c["verified"] for c in cites)
    if g.get("expect_amendment"):
        checks["amendment"] = bool(a.get("amendment_note")) or any(x["id"].startswith("2026-08-28") for x in a.get("amendments", []))
    return {"pass": all(checks.values()), "checks": checks,
            "n_quotes": len(cites), "n_verified": sum(c["verified"] for c in cites)}


def main(ids: list[int], regrade: bool = False):
    gold = json.loads((HERE / "gold.json").read_text(encoding="utf-8"))
    if ids:
        gold = [g for g in gold if g["id"] in ids]
    if regrade:
        saved = {r["id"]: r["answer"] for r in json.loads((HERE / "results.json").read_text(encoding="utf-8"))["rows"]}
        score([(g, saved[g["id"]]) for g in gold if g["id"] in saved], gold)
        return
    asst = Assistant(load_rules())

    # warm the prompt cache with the first question, then run the rest in parallel
    def run(g):
        t = time.time()
        try:
            a = asst.ask(g["question"])
        except Exception as e:  # keep going; count as a failure
            a = {"status": "error", "answer": f"{type(e).__name__}: {e}", "citations": [], "cited_rules": [], "amendments": [], "meta": {}}
        a.setdefault("meta", {})["wall_seconds"] = round(time.time() - t, 1)
        return g, a

    results = [run(gold[0])]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results += list(ex.map(run, gold[1:]))
    score(results, gold)


def score(results: list, gold: list[dict]):
    rows = []
    for g, a in results:
        gr = grade(g, a)
        rows.append({"id": g["id"], "question": g["question"], "gold": g["gold"], "result": gr, "answer": a})
        mark = "PASS" if gr["pass"] else "FAIL"
        failed = [k for k, v in gr["checks"].items() if not v]
        m = a.get("meta", {})
        print(f"[{mark}] Q{g['id']:>2} status={a['status']:<10} path={m.get('path', '?'):<11} calls={m.get('api_calls', '?')} "
              f"rules={a.get('cited_rules')} quotes={gr['n_verified']}/{gr['n_quotes']} {m.get('wall_seconds', '?')}s "
              f"{('failed: ' + ','.join(failed)) if failed else ''}")

    rows.sort(key=lambda r: r["id"])
    n = len(rows)
    passed = sum(r["result"]["pass"] for r in rows)
    rule_ok = [r for r in rows if "rule" in r["result"]["checks"]]
    q_total = sum(r["result"]["n_quotes"] for r in rows)
    q_ver = sum(r["result"]["n_verified"] for r in rows)
    nf = [r for r in rows if r["answer"]["status"] == "not_found"]
    expected_nf = {g["id"] for g in gold if g["expect_status"] == "not_found"}
    false_nf = [r for r in nf if r["id"] not in expected_nf]
    secs = [r["answer"]["meta"].get("wall_seconds", 0) for r in rows]

    summary = {
        "questions": n, "passed": passed,
        "rule_correct": f"{sum(r['result']['checks']['rule'] for r in rule_ok)}/{len(rule_ok)}",
        "facts_correct": f"{sum(r['result']['checks']['facts'] for r in rows)}/{n}",
        "not_found_correct": f"{sum(r['id'] in expected_nf for r in nf)}/{len(expected_nf)}",
        "false_not_found": len(false_nf),
        "quotes_verified": f"{q_ver}/{q_total}",
        "median_seconds": sorted(secs)[len(secs) // 2] if secs else None,
        "api_calls_total": sum(r["answer"].get("meta", {}).get("api_calls", 0) for r in rows),
        "precomputed_questions": sum(r["answer"].get("meta", {}).get("path") == "precomputed" for r in rows),
        "max_output_tokens": max((r["answer"].get("meta", {}).get("usage", {}).get("output", 0) for r in rows), default=0),
        "answers_with_unsupported_figures": sum(bool(r["answer"].get("unsupported_figures")) for r in rows),
        "stopped_at_max_tokens": sum("cut off" in r["answer"].get("answer", "") for r in rows),
    }
    print("\nSUMMARY", json.dumps(summary, indent=2))

    (HERE / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(summary, rows)


def write_report(summary: dict, rows: list[dict]):
    L = ["# Evaluation on the 17 sample questions", "",
         f"Model: `{rows[0]['answer'].get('meta', {}).get('model', '?')}` · run {time.strftime('%Y-%m-%d %H:%M')}", "",
         "| Metric | Result |", "|---|---|",
         f"| Questions fully correct (all checks) | **{summary['passed']}/{summary['questions']}** |",
         f"| Correct rule cited (verified quote) | {summary['rule_correct']} |",
         f"| Key numbers/facts present in answer | {summary['facts_correct']} |",
         f"| Out-of-scope questions answered \"not found\" | {summary['not_found_correct']} |",
         f"| In-scope questions wrongly answered \"not found\" | {summary['false_not_found']} |",
         f"| Quotes verified verbatim against official text | {summary['quotes_verified']} |",
         f"| Median time per answer | {summary['median_seconds']} s |",
         f"| Claude API requests for 17 questions | {summary['api_calls_total']} ({summary['precomputed_questions']} questions precomputed in Python, one request each) |",
         f"| Answers with figures not found in the evidence | {summary['answers_with_unsupported_figures']} |",
         f"| Largest output (tokens, limit {MAX_TOKENS:,}) / answers cut off | {summary['max_output_tokens']} / {summary['stopped_at_max_tokens']} |", "",
         "Grading is automatic (see `eval/run_eval.py`); gold answers in `eval/gold.json` were checked by hand against the official PDF.", "",
         "| # | Question | Result | Path / requests | Rules cited | Answer (short) | Expected |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        a = r["answer"]
        failed = [k for k, v in r["result"]["checks"].items() if not v]
        res = "✅" if r["result"]["pass"] else "❌ " + ", ".join(failed)
        ans = a.get("answer", "").replace("\n", " ").replace("|", "/")
        if len(ans) > 260:
            ans = ans[:257] + "..."
        m = a.get("meta", {})
        L.append(f"| {r['id']} | {r['question'].replace('|', '/')} | {res} | {m.get('path', '?')} / {m.get('api_calls', '?')} | {', '.join(a.get('cited_rules', []))} | {ans} | {r['gold'].replace('|', '/')} |")
    (HERE / "REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    args = sys.argv[1:]
    main([int(x) for x in args if x.isdigit()], regrade="--regrade" in args)
