#!/usr/bin/env python3
"""Quick test for the EDA Agent planner."""
import os
os.environ['ORFS_ROOT'] = '/home/aliu/Desktop/OpenROAD-flow-scripts'

from eda_agent.agent.planner import Planner

planner = Planner()
result = planner.run('show me congestion for design aes at route stage')
print(result)