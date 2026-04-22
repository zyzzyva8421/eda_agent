#!/usr/bin/env python3
"""
API test script - Call /agent/chat endpoint and let LLM decide which tool to use.

This tests the full flow:
  1. User sends natural language query to /agent/chat
  2. LLM parses the query and decides which tool to call
  3. Tool is executed against the database
  4. Result is returned to the LLM for formatting
"""

import json
import os
import sys
import requests

sys.path.insert(0, "/home/aliu/eda_agent")
os.environ["ORFS_ROOT"] = "/home/aliu/Desktop/OpenROAD-flow-scripts"

# Configuration
API_BASE = "http://localhost:8000"


def get_test_token():
    """Get a test JWT token (simplified for testing)."""
    # Try login first
    resp = requests.post(
        f"{API_BASE}/auth/token",
        data={"username": "test", "password": "test"},
    )
    
    if resp.status_code == 200:
        return resp.json()["access_token"]
    
    # If user doesn't exist, try register
    if resp.status_code == 401:
        try:
            requests.post(
                f"{API_BASE}/auth/register",
                json={"username": "test", "password": "test123"},
            )
            resp = requests.post(
                f"{API_BASE}/auth/token",
                data={"username": "test", "password": "test123"},
            )
            return resp.json()["access_token"]
        except:
            return None
    
    return None


def test_agent_chat(query: str):
    """Test the /agent/chat endpoint."""
    print(f"\nQuery: {query}")
    print("-" * 40)
    
    # Get token
    token = get_test_token()
    
    if not token:
        print("ERROR: Could not authenticate")
        print("Note: bcrypt may have compatibility issues")
        return None
    
    # Make request
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        resp = requests.post(
            f"{API_BASE}/agent/chat",
            json={"message": query},
            headers=headers,
            timeout=60,
        )
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"Reply: {result.get('reply', 'N/A')}")
            return result
        else:
            print(f"ERROR: {resp.status_code}")
            print(resp.text)
            return None
    
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to server")
        print("Make sure server is running: uvicorn eda_agent.api.main:app")
        return None
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out (LLM may be slow)")
        return None


def test_direct_planner():
    """Test the Planner directly (without HTTP)."""
    from eda_agent.agent.planner import Planner
    from eda_agent.agent.memory import AgentMemory
    
    print("\nTesting Planner directly (bypassing HTTP)...")
    print("-" * 40)
    
    planner = Planner()
    memory = AgentMemory()
    
    query = "show me the worst slack path for design aes in finish stage"
    print(f"Query: {query}")
    
    try:
        # This will call the MiniMax API
        # Note: This will actually call the LLM!
        result = planner.run(query, memory=memory)
        print(f"Reply: {result}")
        return result
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def main():
    print("=" * 60)
    print("Testing LLM-powered Agent Chat")
    print("=" * 60)
    
    # Try direct planner first (simulates what /agent/chat does)
    test_direct_planner()
    
    print("\n" + "=" * 60)
    print("Testing via HTTP API")
    print("=" * 60)
    
    # Test via HTTP
    test_agent_chat("show me the worst slack path for design aes in finish stage")


if __name__ == "__main__":
    main()