#!/usr/bin/env tcl
#===============================================================================
# Innovus Placement Stage Script
# Usage: innovus -no_gui -overwrite -files place.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/place"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Placement Stage"
puts "=========================================="

# Step 1: Load design from floorplan
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Placement optimization
puts "Step 2: Running placement..."
place_opt

# Optional: detailed options
# place_opt -effort high -verbose

puts "Placement complete"

# Step 3: Save placement stage
puts "Step 3: Saving placement..."
saveDesign $output_dir/place
puts "Placement saved to $output_dir/place"

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
puts "Placement stage complete"
puts "=========================================="
exit 0