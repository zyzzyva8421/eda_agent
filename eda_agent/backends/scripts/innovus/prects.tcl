#!/usr/bin/env tcl
#===============================================================================
# Innovus Pre-CTS Optimization Stage Script
# Usage: innovus -no_gui -overwrite -files prects.tcl
#
# This stage runs after place_opt but before CTS to optimize timing
# using pre-CTS optimization techniques
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/prects"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Pre-CTS Optimization Stage"
puts "=========================================="

# Step 1: Load design from placement
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/work/place/place.dat"]} {
    restoreDesign $saved_dir/work/place/place.dat $design_name
    puts "Loaded from work/place/place.dat"
} elseif {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Set aggressive timing constraints to create slack violations
puts "Step 2: Setting timing constraints..."

# Remove timing uncertainty which helps slack
setTimingRemoveUncertainty -setup -clock_latency -early -late

# Set tighter clock uncertainty (reduces margin)
setTimingUncertainty -setup 0.05 -clock_latency 0.02 [get_clocks *]

# Increase max delay to create more timing pressure
setMaxDelay 0.1 -from [all_loads] -to [all_registers]

puts "Timing constraints set"

# Step 3: Pre-CTS optimization
puts "Step 3: Running pre-CTS optimization..."

# Run pre-CTS optimization
optDesign -preCTS -setup

puts "Pre-CTS optimization complete"

# Step 3: Save stage
puts "Step 3: Saving pre-CTS..."
saveDesign $output_dir/prects
puts "Pre-CTS saved to $output_dir/prects"

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
puts "Pre-CTS optimization stage complete"
puts "=========================================="
exit 0