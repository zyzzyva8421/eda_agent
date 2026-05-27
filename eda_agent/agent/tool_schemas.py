"""OpenAI-style JSON schemas for agent tools."""

from __future__ import annotations

from typing import Any

# ── JSON schemas (OpenAI function-call format) ────────────────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_eda_stage",
            "description": (
                "Run a single EDA flow stage (e.g. synth, place, route) for a "
                "given design and return the run_id and status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name: 'orfs', 'innovus', 'icc2', or custom. 如果用户提到 'place' 但没有指定 backend，默认使用 'innovus'。",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage to run (e.g. 'route').",
                    },
                    "design_name": {
                        "type": "string",
                        "description": "Top-level design/module name (e.g. 'gcd').",
                    },
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value EDA parameters (e.g. CORE_UTILIZATION).",
                    },
                },
                "required": ["backend", "stage", "design_name"],
            },
        },
        # 注：design_config 和 pdk 对某些 backend（如 innovus）可从 settings 自动获取
    },
    {
        "type": "function",
        "function": {
            "name": "run_eda_flow",
            "description": (
                "Run a sequence of EDA flow stages (e.g. from synth to finish) for a "
                "given design. Stages run sequentially in order. Returns status for each stage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name: 'orfs', 'innovus', 'icc2', or custom.",
                    },
                    "stage_start": {
                        "type": "string",
                        "description": "Starting stage (e.g. 'synth') or 'all' to run all stages.",
                    },
                    "stage_end": {
                        "type": "string",
                        "description": "Ending stage (e.g. 'finish'). Ignored if stage_start='all'.",
                    },
                    "design_name": {
                        "type": "string",
                        "description": "Top-level design/module name (e.g. 'gcd').",
                    },
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value EDA parameters (e.g. CORE_UTILIZATION).",
                    },
                    "clean": {
                        "type": "boolean",
                        "description": "If true, run 'make clean' before starting to force rerun all stages.",
                    },
                },
                "required": ["backend", "stage_start", "design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_multi_agent_cycle",
            "description": (
                "Run one multi-agent orchestration cycle (pnr/sta/signoff/experiment) "
                "and optionally execute an experiment stage when gate status is auto_execute."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "Cycle objective, e.g. 'WNS >= -0.1 and overflow_h_pct <= 2.0'.",
                    },
                    "session_id": {
                        "type": "integer",
                        "description": "Optional flow session id for lineage.",
                    },
                    "run_id": {
                        "type": "integer",
                        "description": "Optional baseline run id for diagnosis context.",
                    },
                    "constraints": {
                        "type": "object",
                        "description": "Optional constraints such as risk_level/max_runtime_sec.",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Optional cycle inputs for sub-agent skeletons.",
                    },
                    "agents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional ordered sub-agent list, default pnr/sta/signoff/experiment.",
                    },
                    "execute_experiment": {
                        "type": "boolean",
                        "description": "If true and gate allows, execute experiment_request via run_eda_stage.",
                    },
                    "experiment_request": {
                        "type": "object",
                        "description": (
                            "Stage execution payload. Expected fields: backend, stage, design_name, "
                            "design_config/pdk or innovus_workdir/tech_profile, params."
                        ),
                    },
                },
                "required": ["objective"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_timing",
            "description": (
                "Query timing results (WNS, TNS, failing endpoints) and worst slack paths "
                "from the database for a specific design, stage, and optional run_id. "
                "Returns both summary metrics and individual violating paths."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {"type": "string"},
                    "stage": {"type": "string", "description": "Filter by stage (optional)."},
                    "run_id": {"type": "integer", "description": "Specific run ID (optional)."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 10)."},
                },
                "required": ["design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_congestion",
            "description": (
                "Spatial congestion query. Returns hotspot polygons that overlap "
                "a bounding box (x1,y1,x2,y2) in chip coordinates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "x1": {"type": "number"},
                    "y1": {"type": "number"},
                    "x2": {"type": "number"},
                    "y2": {"type": "number"},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_congestion_summary",
            "description": (
                "Query congestion summary metrics for a run (total overflow, horizontal/vertical "
                "overflow percentages) parsed from Innovus congestion reports."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_runs",
            "description": "Compare PPA metrics between two run IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id_a": {"type": "integer", "description": "Baseline run ID."},
                    "run_id_b": {"type": "integer", "description": "New run ID."},
                },
                "required": ["run_id_a", "run_id_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_params",
            "description": (
                "Based on the current run results and historical data, suggest "
                "parameter adjustments to improve PPA.  Returns a JSON object "
                "with recommended parameter key-value pairs and reasoning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer", "description": "Current run ID to analyse."},
                    "target_spec": {
                        "type": "string",
                        "description": "Natural language PPA target, e.g. 'WNS >= -0.1ns'.",
                    },
                },
                "required": ["run_id", "target_spec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tune_ppa",
            "description": (
                "Autonomous PPA tuning loop: repeatedly suggests parameters, runs the EDA "
                "stage, and checks if the target is met.  Returns the iteration history "
                "and final PPA metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name (e.g. 'orfs').",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage to tune (e.g. 'route').",
                    },
                    "design_name": {"type": "string"},
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "target_spec": {
                        "type": "string",
                        "description": "Natural language PPA target, e.g. 'WNS >= -0.1ns'.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum tuning iterations (default 5).",
                    },
                },
                "required": [
                    "backend", "stage", "design_name", "target_spec",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_placement_blockage",
            "description": (
                "Apply one or more Innovus placement blockages (soft/hard/partial) on the remote "
                "design state and persist them for subsequent place runs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {"type": "integer"},
                    "blockages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "x1": {"type": "number"},
                                "y1": {"type": "number"},
                                "x2": {"type": "number"},
                                "y2": {"type": "number"},
                                "type": {
                                    "type": "string",
                                    "description": "Blockage type: soft/hard/partial.",
                                },
                                "reason": {"type": "string"},
                            },
                            "required": ["x1", "y1", "x2", "y2"],
                        },
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Optional remote Innovus workdir override.",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage whose output_dir should host blockages.tcl (default: place).",
                    },
                },
                "required": ["run_id", "blockages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tune_congestion_with_blockage",
            "description": (
                "Iteratively run Innovus place, evaluate congestion summary, let the LLM decide "
                "placement blockages from hotspots, and repeat until overflow target is met."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {"type": "string"},
                    "design_name": {"type": "string"},
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "congestion_threshold_pct": {
                        "type": "number",
                        "description": "Target max of horizontal/vertical overflow percentage.",
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum tuning iterations.",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Optional Innovus remote workdir override.",
                    },
                },
                "required": ["backend", "design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_utilization",
            "description": (
                "Query design-area and cell-utilisation results from the database "
                "for a specific design, stage, and optional run_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {"type": "string"},
                    "stage": {"type": "string", "description": "Filter by stage (optional)."},
                    "run_id": {"type": "integer", "description": "Specific run ID (optional)."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 10)."},
                },
                "required": ["design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_power",
            "description": (
                "Query power breakdown (internal / switching / leakage / total) in Watts "
                "from the database for a specific design, stage, and optional run_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {"type": "string"},
                    "stage": {"type": "string", "description": "Filter by stage (optional)."},
                    "run_id": {"type": "integer", "description": "Specific run ID (optional)."},
                    "limit": {"type": "integer", "description": "Max rows to return (default 10)."},
                },
                "required": ["design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run_log",
            "description": (
                "Read the log file from a failed or successful EDA run to diagnose issues. "
                "Returns the last N lines of the log file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "integer",
                        "description": "Run ID to read log from.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of last lines to return (default 50).",
                    },
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tune_ppa_multistage",
            "description": (
                "Multi-stage autonomous PPA tuning loop. Unlike tune_ppa (which repeats a "
                "single fixed stage), this tool analyses which stage is the bottleneck "
                "(based on setup/hold violations, congestion, DRC counts) and re-runs "
                "the flow from that stage with adjusted parameters. Returns the full "
                "iteration history with per-stage metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name (e.g. 'orfs').",
                    },
                    "design_name": {"type": "string"},
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "target_spec": {
                        "type": "string",
                        "description": "Natural language PPA target, e.g. 'WNS >= -0.1ns'.",
                    },
                    "start_stage": {
                        "type": "string",
                        "description": (
                            "Earliest stage to run in the first pass "
                            "(default 'place'). Upstream stages (synth/floorplan) "
                            "are assumed already done."
                        ),
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum tuning iterations (default 5).",
                    },
                },
                "required": [
                    "backend", "design_name", "target_spec",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_job",
            "description": (
                "Submit an EDA job to the asynchronous queue for background execution. "
                "Returns a job_id immediately while the job runs in the background worker. "
                "Use 'job_status' to poll for completion. "
                "Set run_mode='flow' to run a sequence of stages (e.g. 'all' from synth to finish)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backend": {
                        "type": "string",
                        "description": "Backend name: 'orfs', 'innovus', 'icc2', or custom.",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage to execute (e.g. 'synth', 'place', 'route'). Ignored if run_mode='flow'.",
                    },
                    "design_name": {
                        "type": "string",
                        "description": "Top-level design/module name (e.g. 'gcd').",
                    },
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": "Key-value EDA parameters (optional).",
                    },
                    "stage_start": {
                        "type": "string",
                        "description": "Starting stage for flow mode (e.g. 'synth', 'all').",
                    },
                    "stage_end": {
                        "type": "string",
                        "description": "Ending stage for flow mode (e.g. 'finish').",
                    },
                    "run_mode": {
                        "type": "string",
                        "description": "Execution mode: 'stage' (single stage) or 'flow' (sequence of stages). Default: 'stage'.",
                    },
                },
                "required": ["backend", "design_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_status",
            "description": (
                "Check the status of a previously submitted async job. "
                "Returns the job status, run_id (if completed), and error message if failed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned from submit_job.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "job_logs",
            "description": (
                "Fetch the log file from a background job. "
                "Returns the last N lines of the log."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned from submit_job.",
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of last lines to return (default 50).",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_job",
            "description": (
                "Cancel a pending or running background job. "
                "Returns whether the cancellation succeeded."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Job ID returned from submit_job.",
                    },
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_case",
            "description": (
                "Save a resolved debugging case to persistent memory. "
                "Call this AFTER diagnosing a root cause so the knowledge can "
                "be retrieved in future sessions with similar problems."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "design_name": {
                        "type": "string",
                        "description": "Top-level design name (e.g. 'gcd').",
                    },
                    "pdk": {
                        "type": "string",
                        "description": "PDK identifier (e.g. 'sky130hd').",
                    },
                    "symptoms": {
                        "type": "string",
                        "description": (
                            "Free-text description of the observed problems "
                            "(timing violations, congestion, DRC errors, etc.)."
                        ),
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "The diagnosed root cause of the problems.",
                    },
                    "actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of actions taken to fix the issue.",
                    },
                    "result_metrics": {
                        "type": "object",
                        "description": (
                            "Key QoR metrics before and after the fix, e.g. "
                            "{\"wns_before\": -0.5, \"wns_after\": -0.1}."
                        ),
                    },
                },
                "required": ["symptoms", "root_cause"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "infer_root_cause",
            "description": (
                "Run the rule-based root cause inference engine against a specific "
                "EDA run and return ranked root cause hypotheses with evidence and "
                "experiment suggestions. Call this when the user asks WHY a run is "
                "failing or wants to diagnose timing/congestion/DRC issues."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "integer",
                        "description": "DB run id (runs.id) to diagnose.",
                    },
                    "symptoms": {
                        "type": "string",
                        "description": (
                            "Optional free-text description of the observed problems "
                            "(e.g. 'WNS is -0.5ns and there are many congestion hotspots'). "
                            "Stored alongside the inference record."
                        ),
                    },
                },
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_root_cause",
            "description": (
                "Confirm the engineer-approved root cause for a previous inference. "
                "Persists the result to case memory so it can be retrieved in future "
                "sessions. Call this AFTER the engineer agrees with a hypothesis."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inference_id": {
                        "type": "integer",
                        "description": "inference_id returned by infer_root_cause.",
                    },
                    "confirmed_cause_id": {
                        "type": "string",
                        "description": (
                            "The cause_id to confirm (e.g. 'routing_detour'). "
                            "Must match one of the cause_id values in the hypotheses list, "
                            "or a free-text string if none matched."
                        ),
                    },
                },
                "required": ["inference_id", "confirmed_cause_id"],
            },
        },
    },
    # ── Inference-guided optimisation loop ─────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "optimize_with_inference",
            "description": (
                "Run a closed-loop optimisation cycle: infer root cause from "
                "the current run, pick the best experiment suggested by the rule "
                "engine, apply it, re-run the stage, verify whether the root cause "
                "was mitigated, and repeat until convergence or max iterations. "
                "Phase B (rule weight learning) is triggered automatically on "
                "convergence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "integer",
                        "description": "DB run id (runs.id) of the baseline run.",
                    },
                    "target_spec": {
                        "type": "string",
                        "description": (
                            "Natural-language PPA target, e.g. "
                            "'WNS >= -0.1 and overflow_h_pct <= 2.0'."
                        ),
                    },
                    "backend": {
                        "type": "string",
                        "description": "Backend name: 'orfs', 'innovus', 'icc2'.",
                    },
                    "stage": {
                        "type": "string",
                        "description": "Flow stage to tune (e.g. 'place').",
                    },
                    "design_name": {"type": "string"},
                    "design_config": {
                        "type": "string",
                        "description": (
                            "Backend config path. For ORFS this is DESIGN_CONFIG; "
                            "for Innovus this is treated as remote workdir root."
                        ),
                    },
                    "pdk": {
                        "type": "string",
                        "description": (
                            "Technology/profile label. For Innovus this is metadata "
                            "used for traceability (default: tsmc18)."
                        ),
                    },
                    "innovus_workdir": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for remote workdir root. If provided "
                            "and design_config is empty, this value is used."
                        ),
                    },
                    "tech_profile": {
                        "type": "string",
                        "description": (
                            "Innovus-only alias for pdk/technology profile label. "
                            "If provided and pdk is empty, this value is used."
                        ),
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum loop iterations (default 5).",
                    },
                },
                "required": [
                    "run_id", "target_spec", "backend", "stage",
                    "design_name",
                ],
            },
        },
    },
]
