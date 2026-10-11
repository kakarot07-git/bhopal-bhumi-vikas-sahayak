# Track 1: Bhumi Vikas Sahayak

**Ask the Bhopal building rulebook, and get an answer you can trust.**

## The problem

Every house, shop or extra floor built in Bhopal must follow the **MP Bhumi Vikas Rules, 2012**. The rules run to 108 pages and 105 numbered rules, with fee tables, setback tables and floor-area limits spread across them. The state keeps amending them. The latest consolidated copy stops at March 2025, and on 28 August 2026 the state changed the rule for plots up to 500 sq m again.

The people who need answers do not have time to read 108 pages:

- A clerk at the Bhopal Municipal Corporation building-permission counter answers the same questions all day.
- A plot owner pays fees, submits plans and waits, then learns the plan breaks a setback rule.
- A small architect checks the same tables by hand on every job.

## Your user

**A building-permission clerk at Bhopal Municipal Corporation.** A citizen stands at the counter and asks: "My plot is 200 sq m on a 9 m road. How much gap do I leave at the front, how many floors can I build, and what fee do I pay?" The clerk needs a correct answer in a minute, with the rule number to show the citizen.

## The data

Everything sits in `data/` and `resources/` in this folder.

| File | What it holds |
|---|---|
| `data/bhumi_vikas_rules.jsonl` | All 105 rules (plus 26-B), one per line, with rule number, title, part, PDF page range and full text |
| `data/bhumi_vikas_rules_sample.jsonl` | 5 rules for quick testing |
| `data/bhumi_vikas_rules_fulltext_by_page.txt` | The whole English text, marked page by page |
| `resources/..._EN.pdf` | The official English PDF (source of truth) |
| `resources/..._HI.pdf` | The official Hindi PDF. Its old font copies out as garbage. Read it, do not parse it |
| `resources/sample_questions.md` | 17 real-world questions to test against, including two the rules do not answer |

Read `data/DATA_DICTIONARY.md` before you start.

## What "done" looks like

A working tool where the clerk:

1. Asks a question in plain English or Hindi.
2. Gets a short answer in the same language.
3. Sees the **rule number and the exact text** the answer came from.
4. Gets a clear "I don't find this in the rules" when the rules are silent.

A strong submission also shows how often it gets the answer right. Run the sample questions, check each answer against the PDF, and report the score.

## Starting points

These are ideas, not instructions. Pick your own approach.

- Fee and setback numbers live in tables. Tables are easy to misread. Check table answers against the PDF.
- Maths (fees, areas, floor counts) belongs in code, not in a language model's head.
- The rules changed after March 2025. Think about how your tool tells the clerk which version of the rules it used.
- Your non-technical teammates matter here: writing test questions from real Bhopal cases, checking answers, writing plain Hindi.

## Constraints

- Public data only. Everything you need is in this folder.
- No connection to any live government system.
- Do not present an answer as legal advice. The clerk decides. Your tool points to the rule.

## Sources

- MP Bhumi Vikas Rules 2012, consolidated to 6 Mar 2025, Town and Country Planning Department: https://mptownplan.gov.in/NewsPDF/bvn06032025E.pdf (downloaded 9 Oct 2026)
- Amendment of 28 Aug 2026 to Rule 2(5)(c), plots up to 500 sq m: https://teamleaseregtech.com/updates/article/59469/government-of-madhya-pradesh-amendment-to-land-development-rules (read 10 Oct 2026)
