#!/usr/bin/env python3
"""
Demo: How LLM decides which tool to use for natural language queries.

This shows the ReAct (Reason + Act) loop that LLM uses:
1. User sends natural language query
2. LLM analyzes the query and decides which tool to call
3. Tool is executed with extracted parameters
4. Result is returned to LLM for formatting
"""

import json
import os
import sys

sys.path.insert(0, "/home/aliu/eda_agent")
os.environ["ORFS_ROOT"] = "/home/aliu/Desktop/OpenROAD-flow-scripts"

from eda_agent.agent.tools import TOOL_SCHEMAS, execute_tool


def show_llm_reasoning():
    """Demonstrate how LLM would reason about tool selection."""
    
    query = "show me the worst slack path for design aes in finish stage"
    
    print("=" * 60)
    print("LLM Tool Selection Demo")
    print("=" * 60)
    
    print(f"\n[User Query]: {query}")
    print("\n[LLM Reasoning]:")
    print("-" * 40)
    
    # This is what LLM would think:
    print("""
Step 1: Analyze the query
  - User wants timing information for a specific design
  - Keywords: "worst slack path", "finish stage", "design aes"
  
Step 2: Select appropriate tool
  - Available tools:
    * run_eda_stage    - Run EDA flow stages
    * query_timing     - Query timing metrics (WNS, TNS, paths) ✓ MATCH
    * query_congestion - Query spatial congestion
    * compare_runs     - Compare two runs
    * suggest_params  - Suggest parameter changes
    
  - Decision: Use "query_timing" tool

Step 3: Extract parameters from natural language
  - design_name: "aes" (extracted from "design aes")
  - stage: "finish" (extracted from "finish stage")
  - limit: 5 (default)

Step 4: Call tool with parameters
""")
    
    # Execute the tool
    result = json.loads(execute_tool("query_timing", {
        "design_name": "aes",
        "stage": "finish",
        "limit": 5
    }))
    
    print("Tool Result:")
    print(json.dumps(result, indent=2))
    
    print("\n[LLM Final Formatting]:")
    print("-" * 40)
    print(f"""
Based on the query "show me the worst slack path for design aes in finish stage":

Timing Summary:
  Stage: finish
  WNS: {result['summary'][0]['wns_ns']} ns {"[FAIL]" if result['summary'][0]['wns_ns'] < 0 else "[PASS]"}
  TNS: {result['summary'][0]['tns_ns']} ns

Worst Slack Path:
  1. {result['paths'][0]['startpoint'][:40]}...
     -> {result['paths'][0]['endpoint'][:40]}...
     Slack: {result['paths'][0]['slack_ns']} ns

The timing is met with a small margin - consider optimizing 
if this is a critical path.
""")


def show_tool_schemas():
    """Show what tool schemas LLM uses to decide."""
    
    print("\n" + "=" * 60)
    print("Available Tool Schemas (what LLM sees)")
    print("=" * 60)
    
    for schema in TOOL_SCHEMAS:
        fn = schema["function"]
        print(f"\n- {fn['name']}")
        print(f"  {fn['description'][:100]}...")


def main():
    show_tool_schemas()
    show_llm_reasoning()


if __name__ == "__main__":
    main()