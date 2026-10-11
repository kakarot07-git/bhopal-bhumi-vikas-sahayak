"""Answer a clerk's question with Claude, grounded in the full rulebook.

Flow:
  1. The whole English rulebook sits in a cached system prompt, so nothing is
     missed by a search step.
  2. Claude may call the calculators (setbacks/FAR, fees) - numbers come from code.
  3. Claude returns JSON: answer + citations (rule number + verbatim quote).
  4. We verify every quote against the official text. Unverified quotes are
     flagged; an answer with no verified quote is never shown as a confident answer.
"""

from __future__ import annotations

import copy
import json
import os
import time

import anthropic

from .amendments import amendments_for_rules, amendments_prompt_text
from .cache import AnswerCache, fingerprint
from .calculators import building_permission_fee, development_permission_fee, residential_plot_norms
from .router import ambiguity_text, evidence_text, plan as route
from .rules import RULES_VERSION, Rule, normalise_rule_id, rulebook_prompt_text, verify_quote
from .support import evidence_for, unsupported_figures

MODEL = os.environ.get("BVS_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("BVS_EFFORT", "medium")  # low | medium | high
MAX_TOOL_ROUNDS = 4


def make_client(**kw) -> anthropic.Anthropic:
    """Anthropic client; trims a key pasted with stray spaces or a line break (a common slip in host settings)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.strip() and key != key.strip():
        kw["api_key"] = key.strip()
    return anthropic.Anthropic(**kw)
MAX_TOKENS = 6000  # longest answer in the eval used ~2,100-2,500 output tokens (incl. thinking)
MAX_HISTORY_TURNS = 4  # earlier Q&A pairs kept for follow-up questions

INSTRUCTIONS = """You are Bhumi Vikas Sahayak, an assistant for a building-permission clerk at the Bhopal Municipal Corporation.
A citizen is standing at the counter. The clerk types the citizen's question in English or Hindi and needs a correct, short answer within a minute, with the rule number to show the citizen.

Your only source is the text of the Madhya Pradesh Bhumi Vikas Rules, 2012 (consolidated up to 6 March 2025) given below, plus the listed later amendments.

How to answer:
- Answer in the same language as the question. If the question is in Hindi (Devanagari or Hinglish), write the answer in simple Hindi (Devanagari). Keep rule numbers, numbers and units as digits (e.g. 3.0 मीटर, नियम 56).
- Be short: 1-5 sentences or a few bullet points. Lead with the direct answer (the number, yes/no, or the list). The clerk decides; you point to the rule. Do not give legal advice or opinions.
- Every factual statement must be backed by a citation: the rule number and a VERBATIM quote copied exactly from that rule's text below (English, character-for-character, 8-60 words, a single contiguous passage - do not join pieces, do not paraphrase, do not fix typos, do not include text from running page headers). Quotes are checked by a program; a quote that is not found verbatim is shown to the clerk as unverified.
- For tables, quote the exact row (e.g. "More than 9.0 meters and up to 12 meters                    3.6 meters" is fine; whitespace does not matter).
- Inserted rules (12-A, 17-a, 25(A), 26-A, 42-A, 93(a)) are inside their parent rule's text: cite the parent number (e.g. 17-a is cited as rule "17").
- For setbacks/open spaces, FAR, maximum built-up area, height or floors of a residential plot, call the residential_plot_norms tool. For building permission fees, call the building_permission_fee tool. For development permission fees (development of land, per hectare), call the development_permission_fee tool (Bhopal's planning area population is above 10 lakh). Do not do arithmetic yourself; use the tool's numbers. Still cite the rule rows the numbers come from. Never invent an input (plot area, road width, built-up area, units): if it is not in the question or the conversation, do not call a tool with a made-up value - name the missing input in ask_citizen.
- Computed evidence: when the message contains <computed_evidence>, the application has already read the inputs and run the calculators on the official tables. Use those numbers exactly, explain them briefly, and cite the rule rows given there (their quotes are verbatim). Tools are not available then. When it contains <input_check>, the inputs could not be read safely: ask the clerk to confirm them instead of guessing.
- Every figure in your answer (metres, sq m, rupees, percentages, periods, storeys) must appear in a passage you cite or in the computed evidence or the question. A program checks this; an answer with an unsupported figure is shown as unverified. If you mention a definition that has a number (e.g. high-rise building = more than 30 m, Rule 2(38)), cite it.
- If the question lacks a needed input (e.g. built-up area for a fee, plot area or road width for setbacks), state the rule (e.g. the fee table) and say which input the clerk must ask the citizen for. If a reasonable assumption is needed, state it.
- NEVER fill gaps with general knowledge. Everything you state must come from the rulebook text below (or a calculator result, or a listed amendment clearly labelled). Do not add facts about other laws, offices, portals, procedures, typical practice or market conditions, even if you believe them to be true and even if labelled "outside the rules" - the clerk could present them to a citizen as municipal law.
- If the rules do not answer the question (e.g. property tax, land market rates, municipal services, other laws), set status to "not_found". The answer must say only that the available Bhumi Vikas Rules do not support a reliable answer to this question (name the topic), in 1-2 sentences. No advice, no office names, no guesses, no citations. Do not stretch an unrelated rule to fit.
- If the rules answer only part of the question, set status "partial": answer the covered part with citations and say plainly which part the rules do not cover - leave that part unanswered.
- Amendments after 6 March 2025: if a listed amendment is relevant (e.g. plots up to 500 sq m and development permission), mention it in amendment_note, say it comes from a secondary summary and must be checked against the official gazette. Never quote the amendment as rule text in citations.
- The Development Plan of the town can set different FAR/density (Rule 61 footnote, Rule 103). Mention this only when relevant to FAR/density/setback answers.
- Follow-up questions: the clerk may ask follow-ups about the same citizen's case. Earlier questions and your earlier answers then appear before the new question. Read the new question in that context (e.g. "and if the road is 12 m?" keeps the plot from before), answer only the new question, and give fresh verbatim citations for it. Earlier answers are not a source; only the rulebook is.

Return only the JSON object described by the schema."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "enum": ["en", "hi"]},
        "status": {"type": "string", "enum": ["answered", "partial", "not_found"]},
        "answer": {"type": "string", "description": "Short answer in the question's language."},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string", "description": "Rule number as printed, e.g. '56' or '26-B'."},
                    "quote": {"type": "string", "description": "Verbatim English passage from that rule."},
                    "supports": {"type": "string", "description": "Which part of the answer this quote supports (question language)."},
                },
                "required": ["rule", "quote", "supports"],
                "additionalProperties": False,
            },
        },
        "amendment_note": {"type": "string", "description": "Empty string if no later amendment is relevant."},
        "ask_citizen": {"type": "string", "description": "Missing information the clerk should ask for, or empty string."},
    },
    "required": ["language", "status", "answer", "citations", "amendment_note", "ask_citizen"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "residential_plot_norms",
        "description": (
            "Compute, from the official tables, the minimum front/rear/side open spaces, FAR, maximum total built-up area, "
            "height limit and an indicative floor count for a RESIDENTIAL plot. Use for any setback / open space / FAR / "
            "floors / height question about a residential plot. Returns items each with rule, PDF page and table row quote."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_area_sqm": {"type": "number", "description": "Plot area in square metres."},
                "road_width_m": {"type": "number", "description": "Width of the street the plot faces, in metres."},
                "frontage_m": {"type": ["number", "null"], "description": "Plot frontage in metres, null if unknown."},
                "building_type": {"anyOf": [{"type": "string", "enum": ["detached", "semi_detached", "row"]}, {"type": "null"}],
                                  "description": "Building type if known, else null."},
                "proposed_height_m": {"type": ["number", "null"], "description": "Proposed building height in metres, null if unknown."},
            },
            "required": ["plot_area_sqm", "road_width_m", "frontage_m", "building_type", "proposed_height_m"],
            "additionalProperties": False,
        },
    },
    {
        "name": "building_permission_fee",
        "description": (
            "Compute the building permission application fee (Rule 21(2)) and permission fee (Rule 21(3)(b) slab table, "
            "or 21(3)(c) for high-rise) for a given proposed built-up area and use."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "built_up_area_sqm": {"type": "number", "description": "Proposed total built-up area in square metres."},
                "use": {"type": "string", "enum": ["residential", "commercial", "shop_cum_residence", "factory_admin_block", "social_educational"]},
                "high_rise": {"type": "boolean", "description": "True only for a high-rise building (more than 10 storeys or above 30 m)."},
            },
            "required": ["built_up_area_sqm", "use", "high_rise"],
            "additionalProperties": False,
        },
    },
]


TOOLS.append({
    "name": "development_permission_fee",
    "description": (
        "Compute the development permission application fee (Rule 21(2)(i), Rs 5000 per hectare or part) and permission "
        "fee (Rule 21(3)(a), rate per hectare by land use zone and planning-area population) for a land area."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "land_area_sqm": {"type": "number", "description": "Land area in square metres (1 hectare = 10,000 sq m)."},
            "zone": {"type": "string", "enum": ["residential_psp_industrial_transport", "commercial", "recreational_agriculture_other"]},
            "population": {"type": "string", "enum": ["above_10_lakh", "5_to_10_lakh", "below_5_lakh"],
                           "description": "Population of the planning area. Bhopal: above_10_lakh."},
        },
        "required": ["land_area_sqm", "zone", "population"],
        "additionalProperties": False,
    },
})


def _run_tool(name: str, args: dict) -> dict:
    if name == "residential_plot_norms":
        return residential_plot_norms(**args)
    if name == "building_permission_fee":
        return building_permission_fee(**args)
    if name == "development_permission_fee":
        return development_permission_fee(**args)
    return {"error": f"unknown tool {name}"}


class Assistant:
    def __init__(self, rules: dict[str, Rule]):
        self.rules = rules
        self.client = make_client()
        self.system = [
            {"type": "text", "text": INSTRUCTIONS},
            {
                "type": "text",
                "text": "<rulebook version=\"" + RULES_VERSION + "\">\n" + rulebook_prompt_text(rules) + "\n</rulebook>\n\n"
                "<later_amendments>\n" + amendments_prompt_text() + "\n</later_amendments>",
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            },
        ]

        self.cache = AnswerCache(fingerprint(RULES_VERSION, MODEL, EFFORT, MAX_TOKENS, INSTRUCTIONS, TOOLS,
                                             ANSWER_SCHEMA, amendments_prompt_text()))

    def ask(self, question: str, history: list[dict] | None = None) -> dict:
        """history: earlier turns of the same conversation, oldest first:
        [{"question": str, "answer": str, "cited_rules": [str]}]. Sent as plain text turns.

        Two paths:
          precomputed - Python already read every input and ran the calculators (router.plan).
                        ONE Claude request, tools disabled (tool_choice none); Claude explains and cites.
          tools       - inputs missing/ambiguous or no calculation applies. Claude may call calculators
                        (up to MAX_TOOL_ROUNDS extra requests) or ask the clerk for clarification.
        """
        t0 = time.time()
        history = (history or [])[-MAX_HISTORY_TURNS:]
        hit = self.cache.get(question, history)
        if hit is not None:  # same question, same conversation, same rules/model/instructions
            out = copy.deepcopy(hit)
            out["meta"].update(cached=True, api_calls=0, seconds=round(time.time() - t0, 3))
            return out
        plan = route(question, history)
        messages: list = []
        for turn in history:
            answer = turn.get("answer", "").strip()
            if turn.get("cited_rules"):
                answer += "\n(Rules cited: " + ", ".join(turn["cited_rules"]) + ")"
            messages.append({"role": "user", "content": turn.get("question", "").strip()})
            messages.append({"role": "assistant", "content": answer or "(no answer)"})

        content = question.strip()
        if plan.precomputed:
            path = "precomputed"
            content += "\n\n" + evidence_text(plan)
        else:
            path = "tools"
            if plan.ambiguous:
                content += "\n\n" + ambiguity_text(plan)
        messages.append({"role": "user", "content": content})

        tool_calls: list[dict] = list(plan.calculations)
        usage = {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
        response, api_calls = None, 0
        rounds = 1 if path == "precomputed" else MAX_TOOL_ROUNDS + 1
        for _ in range(rounds):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=self.system,
                messages=messages,
                tools=TOOLS,  # always sent so the cached prefix (tools + rulebook) is shared by both paths
                tool_choice={"type": "none"} if path == "precomputed" else {"type": "auto"},
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            api_calls += 1
            u = response.usage
            usage["input"] += u.input_tokens or 0
            usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            usage["output"] += u.output_tokens or 0

            if response.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    out = _run_tool(block.name, dict(block.input))
                    tool_calls.append({"tool": block.name, "input": dict(block.input), "output": out})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out, ensure_ascii=False)})
            messages.append({"role": "user", "content": results})

        meta = {"model": getattr(response, "model", MODEL), "seconds": round(time.time() - t0, 1), "usage": usage,
                "path": path, "api_calls": api_calls, "inputs_read": plan.notes, "inputs_missing": plan.missing,
                "ambiguous": plan.ambiguous}
        if response is None or response.stop_reason == "refusal":
            return self._error("The model declined to answer this question. Please check the rules directly.", meta, tool_calls)
        if response.stop_reason == "max_tokens":
            return self._error("The answer was too long and got cut off. Please ask a narrower question.", meta, tool_calls)
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return self._error("Could not read the model's answer. Please try again.", meta, tool_calls)
        result = self.postprocess(raw, tool_calls, meta, question, history)
        self.cache.put(question, history, result)
        return result

    # ------------------------------------------------------------------ verification

    def postprocess(self, raw: dict, tool_calls: list[dict], meta: dict, question: str = "",
                    history: list[dict] | None = None) -> dict:
        citations = []
        for c in raw.get("citations", []):
            chk = verify_quote(self.rules, c.get("rule", ""), c.get("quote", ""))
            cited = normalise_rule_id(c.get("rule", ""))
            rule_id = chk.rule if chk.verified else cited
            r = self.rules.get(rule_id)
            citations.append({
                "rule": rule_id,
                "rule_as_cited": c.get("rule", ""),
                "title": r.title if r else None,
                "quote": chk.exact_text if chk.verified else c.get("quote", ""),
                "supports": c.get("supports", ""),
                "verified": chk.verified,
                "rule_corrected": chk.verified and chk.rule != cited,
                "page": chk.page if chk.verified else (r.page_start if r else None),
            })

        status = raw.get("status", "answered")
        if status == "not_found":
            citations = []  # "not found" means no rule supports an answer - never show rule text under it
        # Reject unverified citations: they are never shown as support, only listed separately.
        rejected = [c for c in citations if not c["verified"]]
        citations = verified = [c for c in citations if c["verified"]]
        warnings = []
        if status != "not_found" and not verified:
            status = "unverified"
            warnings.append("None of the quoted text could be found in the official rules. Do not rely on this answer. Check the PDF.")
        elif rejected:
            warnings.append(f"{len(rejected)} quote(s) could not be found in the official text and were rejected. They are not used as support.")
        if any(c["rule_corrected"] for c in citations):
            warnings.append("A quote was found under a different rule number than the one cited. The rule number shown has been corrected.")

        cited_rules = sorted({c["rule"] for c in verified}, key=lambda x: (len(x), x))
        amendments = amendments_for_rules(cited_rules)
        for t in tool_calls:
            for a in t["output"].get("amendments", []) if isinstance(t["output"], dict) else []:
                if a not in amendments:
                    amendments.append(a)
        if raw.get("amendment_note") and not amendments:
            # model flagged an amendment we track; attach all tracked ones it may refer to
            amendments = [a for a in amendments_for_rules(["2"])]

        # Reject unsupported conclusions: every figure in the answer must come from verified rule text,
        # a calculator result, the question, or a tracked amendment.
        unsupported = []
        if status in ("answered", "partial"):
            evidence = evidence_for(self.rules, citations, tool_calls, question, history, amendments)
            # The answer (the conclusions) must be backed by the cited text / calculations. The
            # "ask the citizen" note only asks questions, so it is checked against the whole rulebook.
            unsupported = unsupported_figures(raw.get("answer", ""), evidence)
            whole = {"direct": evidence["direct"], "rules": [r.text for r in self.rules.values()]}
            unsupported += [f for f in unsupported_figures(raw.get("ask_citizen", ""), whole) if f not in unsupported]
            if unsupported:
                status = "unverified"
                warnings.append("These figures are not supported by the cited rule text or the calculations: "
                                + ", ".join(unsupported) + ". Check them in the PDF before using this answer.")

        return {
            "status": status,
            "language": raw.get("language", "en"),
            "answer": raw.get("answer", ""),
            "ask_citizen": raw.get("ask_citizen", ""),
            "amendment_note": raw.get("amendment_note", ""),
            "citations": citations,
            "rejected_citations": rejected,
            "unsupported_figures": unsupported,
            "cited_rules": cited_rules,
            "amendments": amendments,
            "calculations": tool_calls,
            "warnings": warnings,
            "rules_version": RULES_VERSION,
            "meta": meta,
        }

    def _error(self, msg: str, meta: dict, tool_calls: list) -> dict:
        return {
            "status": "error", "language": "en", "answer": msg, "ask_citizen": "", "amendment_note": "",
            "citations": [], "rejected_citations": [], "unsupported_figures": [], "cited_rules": [], "amendments": [], "calculations": tool_calls,
            "warnings": [msg], "rules_version": RULES_VERSION, "meta": meta,
        }
