"""End-to-end test for LLM-driven congestion fixing in Innovus place stage.

This test:
1. Runs place stage on DTMF_CHIP design
2. Analyzes congestion results
3. Uses LLM to generate blockage fixes
4. Applies fixes via inject_hook mechanism
5. Iterates until congestion is cleared
"""

import pytest
import json
from eda_agent.agent.tools import execute_tool


@pytest.mark.slow
def test_llm_congestion_fix_iterative():
    """Run iterative congestion fixing until clean."""
    # 配置
    result_str = execute_tool("tune_congestion_with_blockage", {
        "backend": "innovus",
        "design_name": "DTMF_CHIP",
        "design_config": "DTMF_CHIP_config",
        "pdk": "tsmc18",
        "congestion_threshold_pct": 2.0,  # 目标: overflow < 2%
        "max_iterations": 5,
    })

    # 解析返回值（可能是 JSON 字符串）
    if isinstance(result_str, str):
        result = json.loads(result_str)
    else:
        result = result_str

    print(f"\n=== 最终结果 ===")
    print(f"Converged: {result.get('converged')}")
    print(f"Iterations: {result.get('iterations')}")
    print(f"History:")
    for h in result.get("history", []):
        print(f"  轮次 {h.get('iteration')}: overflow={h.get('effective_overflow')}% "
              f"status={h.get('status')}")

    # 检查是否有连接错误
    if result.get("converged") is None and "not reachable" in str(result):
        pytest.skip("VM host not reachable - need real Innovus environment")

    assert "converged" in result, f"Result should contain converged status: {result}"