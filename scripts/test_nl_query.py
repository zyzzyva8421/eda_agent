#!/usr/bin/env python3
"""
Natural Language Query Demo for EDA Agent.

This demonstrates how a user would query timing data using natural language:
  - "show me the worst slack path for design aes in route stage"

The agent would:
  1. Parse the natural language
  2. Extract design_name=aes, stage=route
  3. Call query_timing tool
  4. Format results into a readable response
"""

import json
import os
import sys

sys.path.insert(0, "/home/aliu/eda_agent")
os.environ["ORFS_ROOT"] = "/home/aliu/OpenROAD-flow-scripts"

from eda_agent.agent.tools import execute_tool


def query_worst_timing_path(design_name: str, stage: str) -> dict:
    """Query worst timing path for a design/stage."""
    result = json.loads(execute_tool("query_timing", {
        "design_name": design_name,
        "stage": stage,
        "limit": 5
    }))
    return result


def format_nl_response(query: str, result: dict) -> str:
    """Format query result as natural language response."""
    summary = result.get("summary", [])
    paths = result.get("paths", [])
    
    if not summary and not paths:
        return f"I couldn't find timing data for '{query}'."
    
    lines = []
    lines.append(f"Query: {query}")
    lines.append("")
    
    # Summary
    if summary:
        s = summary[0]
        wns = s.get("wns_ns", "N/A")
        tns = s.get("tns_ns", "N/A")
        
        status = "PASS" if wns is None or wns >= 0 else "FAIL"
        lines.append(f"Timing Summary ({s.get('stage', 'unknown')} stage):")
        lines.append(f"  WNS: {wns} ns [{status}]")
        lines.append(f"  TNS: {tns} ns")
        lines.append("")
    
    # Paths
    if paths:
        lines.append("Worst Slack Paths:")
        
        # Sort by slack (worst first)
        sorted_paths = sorted(paths, key=lambda x: x.get("slack_ns", 0))
        
        for i, p in enumerate(sorted_paths[:3], 1):
            slack = p.get("slack_ns")
            status = "VIOLATED" if slack < 0 else "MET"
            
            # Shorten long names
            sp = p.get("startpoint", "")[:35]
            ep = p.get("endpoint", "")[:35]
            
            lines.append(f"  {i}. {sp}...")
            lines.append(f"      -> {ep}...")
            lines.append(f"      slack: {slack} ns ({status})")
    else:
        lines.append("Note: Individual timing paths not available for this stage.")
        lines.append("      Route reports typically only contain summary metrics.")
    
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("EDA Agent - Natural Language Query Demo")
    print("=" * 60)
    print()
    
    # Example queries
    queries = [
        ("show me the worst slack path for design aes in finish stage", "aes", "finish"),
        ("show me the worst slack path for design aes in route stage", "aes", "route"),
    ]
    
    for nl_query, design, stage in queries:
        print(format_nl_response(nl_query, query_worst_timing_path(design, stage)))
        print()
        print("-" * 60)
        print()
    
    print("=" * 60)
    print("To use via API (when server/auth is configured):")
    print("=" * 60)
    print("""
  curl -X POST http://localhost:8000/agent/chat \\
       -H "Authorization: Bearer <token>" \\
       -d '{"message": "show me the worst slack path for design aes in finish stage"}'
""")


if __name__ == "__main__":
    main()