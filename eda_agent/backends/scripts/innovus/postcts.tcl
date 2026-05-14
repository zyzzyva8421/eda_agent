#!/usr/bin/env tcl
#===============================================================================
# Innovus Post-CTS Optimization Stage Script
# Usage: innovus -no_gui -overwrite -files postcts.tcl
#
# This stage runs after CTS but before detailed routing to optimize timing
# using post-CTS optimization techniques (hold fixing, useful skew)
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/postcts"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Post-CTS Optimization Stage"
puts "=========================================="

# Step 1: Load design from CTS
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/work/cts/cts.dat"]} {
    restoreDesign $saved_dir/work/cts/cts.dat $design_name
    puts "Loaded from work/cts/cts.dat"
} elseif {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Post-CTS optimization
puts "Step 2: Running post-CTS optimization..."

# Run post-CTS optimization (setup + hold fixing)
optDesign -postCTS -setup -hold

puts "Post-CTS optimization complete"

# Step 3: Save stage
puts "Step 3: Saving post-CTS..."
saveDesign $output_dir/postcts
puts "Post-CTS saved to $output_dir/postcts"

# Step 4: Generate reports
puts "Step 4: Generating reports..."

# Timing report
report_timing > $output_dir/timing.rpt

# Area/utilization report
report_area > $output_dir/area.rpt

# Power report
report_power > $output_dir/power.rpt

puts "Reports generated"

puts "=========================================="
puts "Post-CTS optimization stage complete"
puts "=========================================="
exit 0