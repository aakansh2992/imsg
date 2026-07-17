"""AI analysis: send the inventory + rule findings to Claude for a tailored,
prioritized tune-up and upgrade plan.

Optional feature: requires `pip install anthropic` and an ANTHROPIC_API_KEY
(or an `ant auth login` profile). Everything else in the tool works without it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

SYSTEM_PROMPT = """You are a veteran laptop repair and optimization technician.
You are given a Windows system inventory (JSON) and findings from a local rules
engine. Produce a practical tune-up plan for THIS specific machine.

Requirements:
- Be specific to the actual hardware found (model, CPU generation, disk types,
  RAM slots, battery wear). Look up what you know about this exact model line.
- Order recommendations by real-world impact per dollar/hour of effort.
- Distinguish clearly: (a) free software fixes, (b) cheap part upgrades,
  (c) advanced work (thermal repaste, solder-level) with honest cost/risk.
- Call out anything in the findings you disagree with or would reprioritize.
- Be honest about limits: no magic settings; if the hardware is the
  bottleneck, say so plainly.
- End with a one-paragraph "if you only do one thing" verdict."""


def build_user_prompt(inventory: Dict[str, Any],
                      findings: List[dict]) -> str:
    # Trim the noisiest sections so the prompt stays focused.
    inv = dict(inventory)
    if isinstance(inv.get("drivers"), list):
        inv["drivers"] = inv["drivers"][:15]
    if isinstance(inv.get("startup"), list):
        inv["startup"] = [s.get("Name") for s in inv["startup"]]
    return (
        "SYSTEM INVENTORY:\n" + json.dumps(inv, indent=1, default=str)
        + "\n\nRULE-ENGINE FINDINGS:\n" + json.dumps(findings, indent=1,
                                                     default=str)
        + "\n\nWrite the tailored tune-up plan."
    )


def ai_analyze(inventory: Dict[str, Any], findings: List[dict],
               model: str = "claude-opus-4-8") -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "AI analysis needs the Anthropic SDK: pip install anthropic"
        ) from exc

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY or `ant auth login`
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user",
                   "content": build_user_prompt(inventory, findings)}],
    ) as stream:
        response = stream.get_final_message()

    parts = [block.text for block in response.content
             if block.type == "text"]
    if not parts:
        raise RuntimeError(
            f"No text in model response (stop_reason={response.stop_reason})")
    return "\n".join(parts)
