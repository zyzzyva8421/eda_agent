#!/usr/bin/env python3
"""
Test the /agent/chat endpoint with LLM-powered tool selection.
"""

import requests
import json
import os
import sys

sys.path.insert(0, "/home/aliu/eda_agent")
os.environ["ORFS_ROOT"] = "/home/aliu/Desktop/OpenROAD-flow-scripts"

API_BASE = "http://localhost:8000"


def get_token():
    """Get authentication token."""
    resp = requests.post(
        f"{API_BASE}/auth/token",
        data={"username": "testuser", "password": "testpass"},
    )
    return resp.json()["access_token"]


def test_agent_chat(query: str):
    """Test the /agent/chat endpoint."""
    token = get_token()
    
    print(f"Query: {query}")
    print("-" * 40)
    
    response = requests.post(
        f"{API_BASE}/agent/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": query},
        timeout=120,  # Wait up to 2 minutes for LLM
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"Reply: {result.get('reply', 'N/A')}")
    else:
        print(f"Error: {response.status_code}")
        print(response.text[:500])


def main():
    print("=" * 60)
    print("Testing LLM-powered Agent Chat via API")
    print("=" * 60)
    
    test_agent_chat("show me the worst slack path for design aes in finish stage")


if __name__ == "__main__":
    main()