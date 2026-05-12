#!/usr/bin/env tcl
#===============================================================================
# Innovus Signoff Stage Script
# Usage: innovus -no_gui -overwrite -files signoff.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/signoff"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Signoff Stage"
puts "=========================================="

# Step 1: Load design from routing
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView route
puts "Design loaded: $design_name"

# Step 2: Wire optimization (if needed)
puts "Step 2: Running optimizations..."
# Route optimization for timing
optDesign -postRoute -verbose

puts "Optimization complete"

# Step 3: Save signoff stage
puts "Step 3: Saving signoff..."
saveDesign $output_dir/signoff
puts "Signoff saved to $output_dir/signoff"

# Step 4: Verification
puts "Step 4: Verification..."

# Geometry check
verifyGeometry -outdir $output_dir > $output_dir/geom.rpt

# Step 5: Generate reports
puts "Step 5: Generating reports..."

# Timing report
report_timing > $output_dir/timing.rpt

# QoR summary
report_qor > $output_dir/qor.rpt

# Area report
report_area > $output_dir/area.rpt

# Power report
report_power -nosplit > $output_dir/power.rpt

# RC extraction report
report_rc -detail > $output_dir/rc.rpt

puts "Reports generated"

puts "=========================================="
puts "Signoff stage complete"
puts "=========================================="
exit 0