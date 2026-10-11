"""Answer cache: a repeated question returns the stored, already-verified answer instantly.

Key = the normalised question + the conversation so far + a fingerprint of everything that shapes the
answer (rules version, model, effort, AI instructions, tools, amendments). Change any of those and old
entries simply stop matching. Kept in memory and appended to cache/answers.jsonl so it survives restarts.
Only good answers are stored (answered / partial / not found) - never errors or unverified answers.

Turn off with BVS_CACHE=0. Entries expire after BVS_CACHE_DAYS (default 30). The file stays on the
machine running the server; delete it to clear the cache.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from .rules import ROOT

CACHE_FILE = ROOT / "cache" / "answers.jsonl"
ENABLED = os.environ.get("BVS_CACHE", "1") != "0"
TTL = float(os.environ.get("BVS_CACHE_DAYS", "30")) * 86400
CACHEABLE = {"answered", "partial", "not_found"}


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q).strip().casefold().rstrip("?।. ")


class AnswerCache:
    def __init__(self, fingerprint: str, path: Path = CACHE_FILE):
        self.fp = fingerprint
        self.path = path
        self.mem: dict[str, dict] = {}
        self.lock = threading.Lock()
        if ENABLED and path.exists():
            now = time.time()
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if now - e.get("at", 0) < TTL:
                    self.mem[e["key"]] = e["value"]

    def key(self, question: str, history: list[dict] | None) -> str:
        hist = [[_norm(h.get("question", "")), h.get("answer", "").strip()] for h in history or []]
        raw = json.dumps([self.fp, _norm(question), hist], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, question: str, history: list[dict] | None) -> dict | None:
        if not ENABLED:
            return None
        return self.mem.get(self.key(question, history))

    def put(self, question: str, history: list[dict] | None, value: dict) -> None:
        if not ENABLED or value.get("status") not in CACHEABLE:
            return
        k = self.key(question, history)
        with self.lock:
            self.mem[k] = value
            self.path.parent.mkdir(exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"key": k, "at": time.time(), "value": value}, ensure_ascii=False) + "\n")


def fingerprint(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
    return h.hexdigest()[:16]
