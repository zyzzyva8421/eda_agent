#!/usr/bin/env python3
"""Quick smoke test: invoke Innovus backend to run the FPR/.test case."""

from pathlib import Path
from eda_agent.backends import get_backend
from eda_agent.backends.base import DesignSpec

def main():
    backend = get_backend("innovus")
    print(f"Backend: {backend.name} v{backend.version}")
    print(f"Available: {backend.is_available()}")
    print(f"Supported stages: {backend.get_supported_stages()}")
    
    # Prepare design spec and parameters for a quick run
    design = DesignSpec(
        name="InnovusBlk_18_1",
        config_path=Path("/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1"),
        pdk="unknown",
    )
    
    # Run the FPR/.test case with a simple command
    params = {
        "command": "cd /home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR/.test && /opt/cadance/INNOVUS181/bin/innovus -nowin -init innovus.cmd > /tmp/innovus_test.log 2>&1 && echo 'SUCCESS'",
        "timeout_sec": 300,
    }
    
    print(f"\nRunning stage 'floorplan' for {design.name}...")
    result = backend.run_stage("floorplan", design, params)
    
    print(f"Status: {result.status}")
    print(f"Run ID: {result.run_id}")
    print(f"Log path: {result.log_path}")
    print(f"Error: {result.error_message}")
    
    if result.log_path and result.log_path.exists():
        print(f"\n--- Log content (tail -n 50) ---")
        log_content = result.log_path.read_text()
        lines = log_content.splitlines()
        for line in lines[-50:]:
            print(line)

if __name__ == "__main__":
    main()
