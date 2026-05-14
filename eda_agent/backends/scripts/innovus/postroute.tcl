#!/usr/bin/env tcl
#===============================================================================
# Innovus Post-Route Optimization Stage Script
# Usage: innovus -no_gui -overwrite -files postroute.tcl
#
# This stage runs after routing but before final signoff to optimize timing
# using post-route optimization techniques (CTO, refinement)
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/postroute"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Post-Route Optimization Stage"
puts "=========================================="

# Step 1: Load design from route
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/work/route/route.dat"]} {
    restoreDesign $saved_dir/work/route/route.dat $design_name
    puts "Loaded from work/route/route.dat"
} elseif {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Post-route optimization
puts "Step 2: Running post-route optimization..."

# Run post-route optimization
optDesign -postRoute -setup -hold

puts "Post-route optimization complete"

# Step 3: Save stage
puts "Step 3: Saving postroute..."
saveDesign $output_dir/postroute
puts "Post-route saved to $output_dir/postroute"

# Step 4: Generate reports
puts "Step 4: Generating reports..."

# Timing report
report_timing > $output_dir/timing.rpt

# Area/utilization report
report_area > $output_dir/area.rpt

# Power report
report_power > $output_dir/power.rpt

# DRC report
verifyGeometry -report $output_dir/drc.rpt

puts "Reports generated"

puts "=========================================="
puts "Post-Route optimization stage complete"
puts "=========================================="
exit 0