#!/usr/bin/env python3
import re

# Read report
with open('/home/aliu/Desktop/OpenROAD-flow-scripts/flow/reports/sky130hd/aes/base/6_finish.rpt') as f:
    text = f.read()

# Try to find path blocks with the pattern
blocks = re.split(r'-{40,}|={40,}', text)

for i, block in enumerate(blocks[:10]):
    if 'Startpoint' in block and 'Endpoint' in block:
        print(f'=== Block {i} ===')
        print(block[:600])
        print()