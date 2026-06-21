"""Stage 5 — bounded LLM narrator (off the critical path; FINAL_PLAN §8.2).

The LLM **never computes, allocates, ranks, or executes**. It receives the
immutable optimizer snapshot and emits a 2-3 sentence plain-English narration of
what the plan does and why. Every displayed number renders from app state, not
from this prose — the narration is explanatory text only.

Every call has a **deterministic template fallback** (`deterministic_narration`)
so a missing API key or an LLM outage cannot break the demo. The live path supports
two providers over httpx (already a locked dep — no extra package, no SDK), chosen
by which key is present:
  * **OpenAI** (`OPENAI_API_KEY`) — Chat Completions API
  * **Anthropic** (`ANTHROPIC_API_KEY`) — Messages API
OpenAI is tried first when both are set. Any failure silently degrades to the template.
"""

from __future__ import annotations

import json
import os
import re

from backend.api.schemas import NarrationResponse, Recommendation

# Provider models (overridable via env). Keys are read at CALL time so the server
# can start without them (the deterministic fallback path stays available).
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
LLM_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")   # Anthropic model
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 320
_TIMEOUT_S = 12.0

# The decision boundary, stated to the model: it narrates, it does not decide.
_SYSTEM = (
    "You are a narration assistant for a paid-media decision engine. A deterministic "
    "optimizer has ALREADY produced the plan; you do NOT compute, allocate, rank, or decide. "
    "Write a crisp 2-3 sentence EXECUTIVE narration (prose, never a list) that explains the "
    "PATTERN and the WHY using ONLY the provided JSON facts:\n"
    "1) Lead with the move as a pattern: shift budget toward the few strongest-marginal "
    "campaigns and trim the saturated / below-hurdle ones (a campaign's marginal_cm_roas vs "
    "cm_hurdle is the reason). Name at most 2-3 representative campaigns per side — do NOT "
    "enumerate every campaign or list per-campaign percentages.\n"
    "2) Then the outcome: whether it clears the blended ROAS floor, with the calibrated ROAS "
    "and net-contribution change.\n"
    "3) If approval_required is true, end with: human approval is required before stubbed "
    "execution.\n"
    "Quote figures EXACTLY using the provided *_display strings; never invent, recompute, or "
    "reformat a number, and only name campaigns present in the facts. No causality, "
    "guarantee, or certainty claims. Plain executive tone, no bullet points, no markdown."
)

# Post-generation grounding guardrails (defense-in-depth on top of the structural one:
# numbers in the UI never come from this prose). A live narration that fails any check is
# discarded in favour of the deterministic template — never shown.
_MIN_CHARS, _MAX_CHARS, _MAX_SENTENCES = 40, 900, 6
# Overclaims a governance tool must never imply. Tight on purpose (avoid false positives
# on common words like "certain"): only flag unambiguous causal/guarantee language.
_BANNED = re.compile(
    r"\b(guarantee\w*|causal|causation|risk[\s-]?free|no\s+risk|assured|infallible|"
    r"will\s+definitely|100%\s+certain)\b",
    re.IGNORECASE,
)
# A platform-prefixed campaign mention, e.g. "Google — Nonbrand Search" / "Meta - Broad …".
_CAMPAIGN_MENTION = re.compile(r"(?:Google|Meta)\s*[—–-]\s*[A-Z][A-Za-z0-9/&+ ]+")


def _norm(s: str) -> str:
    """Lowercase, collapse whitespace, normalize dash variants — for lenient matching."""
    return re.sub(r"\s+", " ", s.replace("—", "-").replace("–", "-")).strip().lower()

# Human-readable labels for the solver's binding-constraint identifiers.
_CONSTRAINT_LABELS = {
    "blended_roas_floor": "the blended ROAS floor",
    "nc_cpa_target": "the NC-CPA ceiling",
    "prospecting_min_share": "the prospecting floor",
    "total_budget": "the budget cap",
    "budget": "the budget cap",
}
_RISK_LABELS = {
    "inventory_no_scale": "inventory holds (no-scale)",
    "below_hurdle": "below-hurdle campaigns",
    "movement_up_cap": "movement caps",
    "movement_down_cap": "movement caps",
}


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _delta_per_day(delta: float) -> str:
    """Scannable per-day delta, e.g. +$17.2K/day or -$840/day."""
    sign = "+" if delta >= 0 else "-"
    a = abs(delta)
    return f"{sign}${a / 1000:.1f}K/day" if a >= 1000 else f"{sign}${a:,.0f}/day"


def _join_names(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def grounding_facts(rec: Recommendation) -> dict:
    """The bounded, safe set of facts the narrator may reference — derived purely from the
    immutable snapshot (no latent truth, no recomputation). Carries per-campaign marginal
    economics (the 'why') plus PRE-FORMATTED figure strings, so the model explains the
    pattern and quotes figures verbatim instead of reformatting (or inventing) numbers."""
    k = rec.kpis
    ups = sorted((ln for ln in rec.lines if ln.delta_pct > 0.5),
                 key=lambda ln: ln.delta_pct, reverse=True)
    downs = sorted((ln for ln in rec.lines if ln.delta_pct < -0.5),
                   key=lambda ln: ln.delta_pct)
    held = [ln.campaign_name for ln in rec.lines
            if "inventory_no_scale" in ln.risk_flags and abs(ln.delta_pct) < 0.5]
    binding = [b.name for b in rec.binding.portfolio if b.status in ("binding", "violated")]
    risks = sorted({f for ln in rec.lines for f in ln.risk_flags})
    net_delta = k.net_contribution_projected - k.net_contribution_current

    def brief(ln):
        return {"campaign": ln.campaign_name, "delta_pct": round(ln.delta_pct, 1),
                "marginal_cm_roas": round(ln.marginal_cm_roas, 2), "pacing": ln.pacing_flag}

    return {
        "feasible": rec.feasible,
        "policy_mode": rec.policy_mode,
        "approval_required": True,   # human approval ALWAYS precedes stubbed execution
        # the 'why': scale where marginal_cm_roas is strongest; trim where saturated /
        # below the contribution hurdle (cm break-even = 1.0×).
        "cm_hurdle": round(rec.marginal_cm_hurdle, 2),
        "scale_up": [brief(ln) for ln in ups[:4]],
        "pull_back": [brief(ln) for ln in downs[:4]],
        "held": held,
        "reserve_per_day": round(k.reserve, 0),
        "reserve_display": f"{_money(k.reserve)}/day" if k.reserve > 0 else "none (full budget deployed)",
        # pre-formatted figure strings — the model must quote these verbatim
        "blended_roas_display": f"{k.blended_roas_current:.2f}\u00d7 \u2192 {k.blended_roas_projected:.2f}\u00d7",
        "roas_floor_display": f"{rec.constraints.roas_floor:.1f}\u00d7",
        "roas_floor_cleared": k.blended_roas_projected >= rec.constraints.roas_floor,
        "cm_roas_display": f"{k.cm_roas_current:.2f}\u00d7 \u2192 {k.cm_roas_projected:.2f}\u00d7",
        "net_contribution_display": f"{_money(k.net_contribution_current)}/day \u2192 {_money(k.net_contribution_projected)}/day",
        "net_contribution_delta_display": _delta_per_day(net_delta),
        "binding_constraints": binding,
        "risk_flags": risks,
    }


def deterministic_narration(rec: Recommendation) -> str:
    """Template fallback — self-contained, never raises. Mirrors the executive style of the
    live narrator: the PATTERN and the WHY, exact figures, then the approval line."""
    f = grounding_facts(rec)

    if not f["feasible"]:
        why = (" Unmet: " + "; ".join(rec.conflicts) + ".") if rec.conflicts else ""
        return (
            "No allocation satisfies the current constraints, so the plan below is a "
            "diagnostic candidate and cannot be approved." + why
        )

    scale = _join_names([c["campaign"] for c in f["scale_up"][:3]])
    trim = _join_names([c["campaign"] for c in f["pull_back"][:3]])
    lead = "Feasible plan: shift budget toward " + (scale or "the strongest-marginal campaigns") \
        + " where marginal returns are strongest"
    if trim:
        lead += ", while trimming " + trim + " where the next dollar is weaker"
    lead += "."

    if f["roas_floor_cleared"]:
        econ = (f"It clears the {f['roas_floor_display']} blended ROAS floor — calibrated ROAS "
                f"{f['blended_roas_display']} and net contribution {f['net_contribution_display']} "
                f"({f['net_contribution_delta_display']}).")
    else:
        econ = (f"Calibrated ROAS moves {f['blended_roas_display']} (below the "
                f"{f['roas_floor_display']} floor) with net contribution "
                f"{f['net_contribution_display']} ({f['net_contribution_delta_display']}).")

    return " ".join([lead, econ, "Human approval is required before stubbed execution."])


def _user_prompt(facts: dict) -> str:
    return "Narrate this optimizer plan in 2-3 sentences. Facts JSON:\n" + json.dumps(facts)


def is_grounded(text: str, rec: Recommendation) -> bool:
    """Post-generation guardrail: accept a live narration only if it is plausibly faithful
    to the snapshot. Conservative by design — it rejects clear hallucinations (fabricated
    campaign names, overclaims, runaway length) without false-positiving on legitimate
    phrasing. A rejected narration falls back to the deterministic template, so the worst
    case is the safe template, never a shown hallucination."""
    if not text:
        return False
    t = text.strip()
    if not (_MIN_CHARS <= len(t) <= _MAX_CHARS):
        return False
    # count only SENTENCE-ENDING punctuation (followed by space/end) so decimals like
    # "4.19×" are not mistaken for sentence breaks
    if len(re.findall(r"[.!?]+(?=\s|$)", t)) > _MAX_SENTENCES:
        return False
    if _BANNED.search(t):
        return False
    # every platform-prefixed campaign the prose names must exist in the plan (no inventing)
    allowed = [_norm(ln.campaign_name) for ln in rec.lines]
    for m in _CAMPAIGN_MENTION.findall(t):
        mention = _norm(m)
        if not any(mention in name or name in mention for name in allowed):
            return False
    return True


def _call_openai(facts: dict) -> str | None:
    """Live OpenAI Chat Completions call via httpx. Returns None (→ fallback) on a
    missing key, a missing dependency, or any API/transport error — never raises."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.post(
            _OPENAI_URL,
            headers={
                "authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "max_tokens": _MAX_TOKENS,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _user_prompt(facts)},
                ],
            },
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        text = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        return text or None
    except Exception:
        return None


def _call_anthropic(facts: dict) -> str | None:
    """Live Anthropic Messages call via httpx. Returns None (→ fallback) on a missing
    key, a missing dependency, or any API/transport error — never raises."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import httpx
    except ImportError:
        return None
    try:
        resp = httpx.post(
            _ANTHROPIC_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "max_tokens": _MAX_TOKENS,
                "temperature": 0.2,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": _user_prompt(facts)}],
            },
            timeout=_TIMEOUT_S,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        return text or None
    except Exception:
        return None


def _target_model() -> str:
    """The model the live path WOULD use, for transparency on the fallback record."""
    if os.environ.get("OPENAI_API_KEY"):
        return OPENAI_MODEL
    if os.environ.get("ANTHROPIC_API_KEY"):
        return LLM_MODEL
    return "deterministic"


def narrate(rec: Recommendation) -> NarrationResponse:
    """Narrate a snapshot: a live LLM call when a provider key is configured (OpenAI
    preferred, then Anthropic), else the deterministic template. The template is also
    the safety net for any live-path failure."""
    try:
        facts = grounding_facts(rec)
        text = _call_openai(facts)
        if text and is_grounded(text, rec):
            return NarrationResponse(text=text, source="llm", model=OPENAI_MODEL)
        text = _call_anthropic(facts)
        if text and is_grounded(text, rec):
            return NarrationResponse(text=text, source="llm", model=LLM_MODEL)
        return NarrationResponse(text=deterministic_narration(rec),
                                 source="fallback", model=_target_model())
    except Exception:
        # last-resort minimal narration — the endpoint must never 500 on narration
        moves = "deploy the budget within policy guardrails"
        return NarrationResponse(text=f"The optimizer recommends a plan to {moves}.",
                                 source="fallback", model=LLM_MODEL)
