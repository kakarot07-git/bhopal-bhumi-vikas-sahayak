"""Web server: one page for the clerk, a small JSON API behind it.

Run:  python -m app.server     (then open http://localhost:8000)
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi import Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .amendments import AMENDMENTS
from .calculators import (building_permission_fee, case_summary, development_permission_fee,
                          residential_plot_norms, self_check)
from .report import build_report
from .rules import ROOT, RULES_VERSION, load_rules, normalise_rule_id, search_rules
from .validate import validate_devfee, validate_fee, validate_plot

RULES = load_rules()
PROBLEMS = self_check(RULES)
if PROBLEMS:  # a table row in calculators.py does not match the official text - refuse to start
    raise SystemExit("Calculator tables do not match the official rules text:\n" + "\n".join(PROBLEMS))

PDF_EN = ROOT / "resources" / "MP_Bhumi_Vikas_Rules_2012_upto_2025-03-06_EN.pdf"
PDF_HI = ROOT / "resources" / "MP_Bhumi_Vikas_Rules_2012_upto_2025-03-06_HI.pdf"
STATIC = ROOT / "static"

_assistant = None


def assistant():
    global _assistant
    if _assistant is None:
        from .assistant import Assistant
        _assistant = Assistant(RULES)
    return _assistant


app = FastAPI(title="Bhumi Vikas Sahayak")

# The rulebook and PDFs never change while the server runs: let the browser keep them (faster tab
# switches and rule views). The page itself and AI answers are not cached by the browser.
_KB_PATHS = ("/api/rules", "/api/rule/", "/api/search", "/pdf/")


@app.middleware("http")
async def kb_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and request.url.path.startswith(_KB_PATHS) and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Turn(BaseModel):
    question: str = Field(max_length=1000)
    answer: str = Field(max_length=6000)
    cited_rules: list[str] = Field(default_factory=list, max_length=30)


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    history: list[Turn] = Field(default_factory=list, max_length=10)  # earlier turns, for follow-up questions


class PlotIn(BaseModel):
    plot_area_sqm: float = Field(gt=0)
    road_width_m: float = Field(gt=0)
    frontage_m: float | None = Field(default=None, gt=0)
    building_type: str | None = None
    proposed_height_m: float | None = Field(default=None, gt=0)


class DevFeeIn(BaseModel):
    land_area_sqm: float = Field(gt=0)
    zone: str = "residential_psp_industrial_transport"
    population: str = "above_10_lakh"


class CaseIn(BaseModel):
    plot_area_sqm: float = Field(gt=0)
    road_width_m: float = Field(gt=0)
    frontage_m: float | None = Field(default=None, gt=0)
    building_type: str | None = None
    proposed_height_m: float | None = Field(default=None, gt=0)
    use: str = "residential"
    built_up_area_sqm: float | None = Field(default=None, gt=0)


class FeeIn(BaseModel):
    built_up_area_sqm: float = Field(gt=0)
    use: str = "residential"
    high_rise: bool = False


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/pdf/en")
def pdf_en():
    return FileResponse(PDF_EN, media_type="application/pdf")


@app.get("/pdf/hi")
def pdf_hi():
    return FileResponse(PDF_HI, media_type="application/pdf")


_ai_check = {"at": 0.0, "ok": None, "why": ""}


def ai_reachable() -> tuple[bool, str]:
    """Cheap check (no tokens): can we reach the Claude API with working credentials?
    Cached for 60 s so page loads stay fast. Used to switch the page into offline reference mode."""
    import time
    if time.time() - _ai_check["at"] < 60 and _ai_check["ok"] is not None:
        return _ai_check["ok"], _ai_check["why"]
    try:
        import anthropic
        from .assistant import make_client
        make_client(max_retries=0, timeout=4.0).models.retrieve(os.environ.get("BVS_MODEL", "claude-opus-5-5"))
        ok, why = True, ""
    except Exception as e:  # no key, no network, API down - all mean "offline" for the clerk
        ok = False
        why = ("AI key not set (ANTHROPIC_API_KEY)" if isinstance(e, TypeError) and "authentication" in str(e).lower()
               else type(e).__name__)
    _ai_check.update(at=time.time(), ok=ok, why=why)
    return ok, why


def _deployment_info() -> dict:
    """Safe diagnostics for setting up the AI key on a host such as Vercel. Never returns the key itself:
    only whether it is present, whether it looks like a Claude key, and the NAMES of similar variables
    (catches typos like a trailing space or a hyphen)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    similar = sorted(k for k in os.environ if "ANTHROPIC" in k.upper() and k != "ANTHROPIC_API_KEY")
    return {
        "api_key_present": bool(key.strip()),
        "api_key_looks_valid": key.strip().startswith("sk-ant-"),
        "api_key_has_spaces": key != key.strip(),
        "similar_variable_names": similar,
        "host_environment": os.environ.get("VERCEL_ENV", "local"),
        "commit": (os.environ.get("VERCEL_GIT_COMMIT_SHA") or "")[:7] or None,
    }


@app.get("/api/status")
def status():
    ok, why = ai_reachable()
    return {
        "rules_version": RULES_VERSION,
        "rules_loaded": len(RULES),
        "tables_verified": not PROBLEMS,
        "model": os.environ.get("BVS_MODEL", "claude-opus-5-5"),
        "ai_available": ok,
        "ai_unavailable_reason": why,
        "deployment": _deployment_info(),
        "amendments": AMENDMENTS,
    }


@app.post("/api/ask")
def ask(body: AskIn):
    try:
        return assistant().ask(body.question, [t.model_dump() for t in body.history])
    except Exception as e:  # surface a readable message to the clerk; calculators still work
        import anthropic
        if isinstance(e, TypeError) and "authentication" in str(e).lower():
            msg = ("The AI key is not set on this server. Add ANTHROPIC_API_KEY to the server's environment "
                   "variables (on Vercel: Project Settings > Environment Variables) and redeploy. "
                   "The Setback & FAR, Fee and Rules tabs still work.")
        elif isinstance(e, anthropic.AuthenticationError):
            msg = "The AI key is missing or invalid. Ask your administrator to set ANTHROPIC_API_KEY. The calculators below still work."
        elif isinstance(e, anthropic.RateLimitError):
            msg = "Too many requests right now. Please wait a few seconds and try again."
        elif isinstance(e, anthropic.APIConnectionError):
            msg = "No internet connection to the AI service. The calculators and rule viewer still work offline."
        elif isinstance(e, anthropic.APIStatusError):
            msg = f"The AI service returned an error ({e.status_code}). Please try again."
        else:
            msg = f"Something went wrong: {type(e).__name__}. The calculators still work."
        raise HTTPException(status_code=503, detail=msg)


@app.post("/api/calc/plot")
def calc_plot(body: PlotIn):
    _require_valid(validate_plot, body.model_dump())
    return residential_plot_norms(**body.model_dump())


@app.post("/api/calc/fee")
def calc_fee(body: FeeIn):
    _require_valid(validate_fee, body.model_dump())
    out = building_permission_fee(**body.model_dump())
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    return out


@app.post("/api/calc/devfee")
def calc_devfee(body: DevFeeIn):
    _require_valid(validate_devfee, body.model_dump())
    out = development_permission_fee(**body.model_dump())
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    return out


@app.post("/api/case-summary")
def calc_case(body: CaseIn):
    _require_valid(validate_plot, body.model_dump())
    out = case_summary(**body.model_dump())
    if "error" in out:
        raise HTTPException(status_code=400, detail=out["error"])
    return out


def _require_valid(fn, data: dict):
    res = fn(data)
    if not res["valid"]:
        raise HTTPException(status_code=422, detail="; ".join(v["en"] for v in res["errors"].values()))


@app.post("/api/validate/{kind}")
def validate(kind: str, body: dict):
    fn = {"plot": validate_plot, "fee": validate_fee, "devfee": validate_devfee}.get(kind)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown form '{kind}'")
    return fn(body)


@app.post("/api/report")
def report(body: dict):
    """One PDF with everything from this session (answers re-verified, calculations recomputed)."""
    for key, fn in (("plot", validate_plot), ("compare", validate_plot), ("fee", validate_fee), ("devfee", validate_devfee)):
        if body.get(key) and not fn(body[key])["valid"]:
            body[key] = None  # never print a calculation from invalid inputs
    pdf = build_report(body, RULES)
    from datetime import datetime
    name = f"BVS-case-report-{datetime.now():%Y%m%d-%H%M}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/search")
def search(q: str = ""):
    return search_rules(RULES, q[:200])


@app.get("/api/rule/{rule_id}")
def get_rule(rule_id: str):
    r = RULES.get(normalise_rule_id(rule_id))
    if not r:
        raise HTTPException(status_code=404, detail=f"Rule {rule_id} not found")
    return {"rule": r.rule, "title": r.title, "part": r.part, "page_start": r.page_start, "page_end": r.page_end, "text": r.text}


@app.get("/api/rules")
def list_rules():
    return [{"rule": r.rule, "title": r.title, "part": r.part, "page_start": r.page_start, "page_end": r.page_end} for r in RULES.values()]


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    print(f"Bhumi Vikas Sahayak running at http://localhost:{port}")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=port)
