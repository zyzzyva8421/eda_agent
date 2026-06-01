"""Congestion tuning helpers for blockage synthesis and iterative runs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

import httpx

from eda_agent.config import settings

logger = logging.getLogger(__name__)


def bbox_from_wkt_impl(geom_wkt: str) -> tuple[float, float, float, float] | None:
    points = re.findall(
        r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
        geom_wkt,
    )
    if len(points) < 4:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def heuristic_decide_blockages_impl(
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
    *,
    bbox_from_wkt_fn: Callable[[str], tuple[float, float, float, float] | None] = bbox_from_wkt_impl,
) -> list[dict[str, Any]]:
    selected = sorted(
        hotspots,
        key=lambda h: float(h.get("overflow", 0) or 0),
        reverse=True,
    )[:max_blockages]

    blockages: list[dict[str, Any]] = []
    for idx, hs in enumerate(selected, start=1):
        geom_wkt = hs.get("geom_wkt")
        bbox = bbox_from_wkt_fn(geom_wkt) if isinstance(geom_wkt, str) else None
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox
        blockages.append(
            {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "type": "soft",
                "reason": (
                    f"heuristic_hotspot_rank_{idx}; "
                    f"overflow={hs.get('overflow', 0)}"
                ),
            }
        )
    return blockages


def llm_decide_blockages_impl(
    *,
    run_id: int,
    congestion_summary: dict[str, Any],
    hotspots: list[dict[str, Any]],
    max_blockages: int = 3,
    heuristic_decide_blockages_fn: Callable[..., list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Use LLM to decide blockage bounding boxes; fallback to heuristics."""
    if not hotspots:
        return []

    summary_json = json.dumps(congestion_summary, ensure_ascii=False)
    hotspot_sample = hotspots[:12]
    hotspot_json = json.dumps(hotspot_sample, ensure_ascii=False)

    system_prompt = (
        "You are an expert Innovus placement optimization engineer. "
        "Return ONLY JSON: {\"blockages\": [...]}\\n"
        "Each blockage item must include x1,y1,x2,y2,type,reason. "
        "Allowed type values: soft, hard, partial. "
        "Use no more than max_blockages items and prioritize highest overflow hotspots."
    )
    user_prompt = (
        f"run_id={run_id}\\n"
        f"max_blockages={max_blockages}\\n"
        f"congestion_summary={summary_json}\\n"
        f"hotspots={hotspot_json}\\n"
        "Output strict JSON only."
    )

    api_key = settings.minimax_api_key
    if not api_key:
        return heuristic_decide_blockages_fn(hotspots, max_blockages=max_blockages)

    model = settings.minimax_model
    base_url = settings.minimax_base_url.rstrip("/")
    group_id = settings.minimax_group_id
    url = (
        f"{base_url}/text/chatcompletion_v2?GroupId={group_id}"
        if group_id
        else f"{base_url}/chat/completions"
    )

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": 800,
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.rsplit("```", 1)[0].strip()
        parsed = json.loads(content)
        raw_blockages = parsed.get("blockages", [])
        if not isinstance(raw_blockages, list):
            return heuristic_decide_blockages_fn(hotspots, max_blockages=max_blockages)
        validated: list[dict[str, Any]] = []
        for item in raw_blockages[:max_blockages]:
            if not isinstance(item, dict):
                continue
            try:
                x1 = float(item["x1"])
                y1 = float(item["y1"])
                x2 = float(item["x2"])
                y2 = float(item["y2"])
            except Exception:
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            btype = str(item.get("type", "soft")).lower()
            if btype not in {"soft", "hard", "partial"}:
                btype = "soft"
            validated.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "type": btype,
                    "reason": str(item.get("reason", "llm_hotspot")),
                }
            )
        if validated:
            return validated
    except Exception:
        logger.warning("LLM blockage decision failed; using heuristic fallback", exc_info=True)

    return heuristic_decide_blockages_fn(hotspots, max_blockages=max_blockages)


def tune_congestion_with_blockage_impl(
    backend: str,
    design_name: str,
    design_config: str | None = None,
    pdk: str | None = None,
    innovus_workdir: str | None = None,
    tech_profile: str | None = None,
    congestion_threshold_pct: float = 2.0,
    max_iterations: int = 5,
    workdir: str | None = None,
    *,
    resolve_backend_design_identity_fn: Callable[..., tuple[str, str]],
    run_eda_stage_fn: Callable[..., dict[str, Any]],
    query_congestion_summary_fn: Callable[[int], dict[str, Any]],
    query_congestion_fn: Callable[..., list[dict[str, Any]]],
    llm_decide_blockages_fn: Callable[..., list[dict[str, Any]]],
    add_placement_blockage_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Iteratively tune place congestion by adding placement blockages."""
    history: list[dict[str, Any]] = []

    design_config, pdk = resolve_backend_design_identity_fn(
        backend=backend,
        design_config=design_config,
        pdk=pdk,
        innovus_workdir=innovus_workdir,
        tech_profile=tech_profile,
    )

    for iteration in range(1, max_iterations + 1):
        run_result = run_eda_stage_fn(
            backend=backend,
            stage="place",
            design_name=design_name,
            design_config=design_config,
            pdk=pdk,
            params={"workdir": workdir} if workdir else {},
        )
        run_id = run_result.get("run_id")
        status = run_result.get("status")
        iter_row: dict[str, Any] = {
            "iteration": iteration,
            "run_id": run_id,
            "status": status,
            "target_threshold_pct": congestion_threshold_pct,
        }
        if status != "success" or run_id is None:
            iter_row["error"] = run_result.get("error")
            history.append(iter_row)
            break

        summary = query_congestion_summary_fn(run_id)
        iter_row["congestion_summary"] = summary

        overflow_h_pct = float(summary.get("overflow_h_pct", 0.0) or 0.0)
        overflow_v_pct = float(summary.get("overflow_v_pct", 0.0) or 0.0)
        has_pct = ("overflow_h_pct" in summary) or ("overflow_v_pct" in summary)
        effective_overflow = (
            max(overflow_h_pct, overflow_v_pct)
            if has_pct
            else float(summary.get("total_overflow", 0.0) or 0.0)
        )
        iter_row["effective_overflow"] = effective_overflow
        iter_row["overflow_basis"] = "pct" if has_pct else "count"

        if effective_overflow <= congestion_threshold_pct:
            iter_row["converged"] = True
            history.append(iter_row)
            return {
                "converged": True,
                "iterations": iteration,
                "threshold_pct": congestion_threshold_pct,
                "history": history,
            }

        hotspots = query_congestion_fn(run_id)
        iter_row["hotspot_count"] = len(hotspots)
        if not hotspots:
            iter_row["converged"] = False
            iter_row["error"] = "No congestion hotspots found for blockage synthesis"
            history.append(iter_row)
            break

        blockages = llm_decide_blockages_fn(
            run_id=run_id,
            congestion_summary=summary,
            hotspots=hotspots,
        )
        if not blockages:
            iter_row["converged"] = False
            iter_row["error"] = "No valid blockage candidates produced"
            history.append(iter_row)
            break

        apply_result = add_placement_blockage_fn(
            run_id=run_id,
            blockages=blockages,
            workdir=workdir,
            stage="place",
        )
        iter_row["applied_blockages"] = blockages
        iter_row["blockage_apply_result"] = apply_result
        history.append(iter_row)

    return {
        "converged": False,
        "iterations": len(history),
        "threshold_pct": congestion_threshold_pct,
        "history": history,
    }
