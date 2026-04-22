#!/usr/bin/env python3
"""Test query for CTS worst slack path.

This script directly calls the query_timing tool to get CTS timing data.
"""

import json
import sys
import os

# Add project to path
sys.path.insert(0, "/home/aliu/eda_agent")
os.environ["ORFS_ROOT"] = "/home/aliu/OpenROAD-flow-scripts"

from eda_agent.agent.tools import execute_tool


def main():
    print("=" * 60)
    print("Testing query_timing for CTS worst slack")
    print("=" * 60)

    # Query timing for design=gcd, stage=cts
    result = json.loads(
        execute_tool("query_timing", {"design_name": "gcd", "stage": "cts", "limit": 5})
    )

    # Display summary
    print("\n[Summary]")
    for s in result.get("summary", []):
        print(f"  Stage: {s.get('stage')}")
        print(f"  WNS:   {s.get('wns_ns')} ns")
        print(f"  TNS:   {s.get('tns_ns')} ns")
        print(f"  FEP:   {s.get('failing_endpoints')}")

    # Display paths
    print("\n[Paths]")
    paths = result.get("paths", [])
    if paths:
        for p in paths:
            print(f"  {p.get('startpoint')} -> {p.get('endpoint')}")
            print(f"    slack: {p.get('slack_ns')} ns")
    else:
        print("  (no individual paths in report - CTS summary only)")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()