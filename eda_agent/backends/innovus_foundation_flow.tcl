#!/usr/bin/env tcl
#===============================================================================
# Innovus Complete PR Flow Script
# For DTMF chip case
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set output_dir "$design_dir/work/foundation_flow"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Complete PR Flow"
puts "=========================================="

# Step 1: Load existing design
puts "Step 1: Loading design..."
restoreDesign $design_dir/saved/postCTSopt.inv.dat $design_name
setDrawView fplan
puts "Design loaded: $design_name"

# Step 2: Placement
puts "Step 2: Placement..."
place_opt
saveDesign $output_dir/place
puts "Placement done"

# Step 3: Routing - global
puts "Step 3: Global routing..."
routeDesign -global
saveDesign $output_dir/route_global
puts "Global routing done"

# Step 4: Routing - detail
puts "Step 4: Detail routing..."
routeDesign -detail
saveDesign $output_dir/route_detail
puts "Detail routing done"

# Step 5: Verification
puts "Step 5: Verification..."
verifyGeometry

# Step 6: Skip optimization (requires OCV setup)
# Step 7: Reports
puts "Step 7: Generating reports..."
set output_file "$output_dir/timing.rpt"
report_timing -summary > $output_file
puts "Timing report: $output_file"

set output_file "$output_dir/power.rpt"
report_power > $output_file
puts "Power report: $output_file"

set output_file "$output_dir/area.rpt"  
report_area > $output_file
puts "Area report: $output_file"

set output_file "$output_dir/drc.rpt"
reportDesign -checks > $output_file
puts "DRC report: $output_file"

puts "=========================================="
puts "PR Flow Completed!"
puts "Reports: $output_dir"
puts "=========================================="

exit
