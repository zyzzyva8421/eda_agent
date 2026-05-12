#!/usr/bin/env tcl
#===============================================================================
# Innovus Routing Stage Script
# Usage: innovus -no_gui -overwrite -files route.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/route"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Routing Stage"
puts "=========================================="

# Step 1: Load design from CTS
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/postCTSopt.inv.dat"]} {
    restoreDesign $saved_dir/postCTSopt.inv.dat $design_name
    puts "Loaded from postCTSopt.inv.dat"
} elseif {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView-route
puts "Design loaded: $design_name"

# Step 2: Global routing
puts "Step 2: Global routing..."
routeDesign -global
saveDesign $output_dir/route_global
puts "Global routing done"

# Step 3: Detail routing
puts "Step 3: Detail routing..."
routeDesign -detail
saveDesign $output_dir/route_detail
puts "Detail routing done"

# Step 4: Save final route stage
puts "Step 4: Saving route..."
saveDesign $output_dir/route
puts "Route saved to $output_dir/route"

# Step 5: Generate reports
puts "Step 5: Generating reports..."

# Timing report
report_timing -nosplit -verbose > $output_dir/timing.rpt

# DRC report
verifyGeometry -outdir $output_dir > $output_dir/drc.rpt

# Congestion report
report_congestion -verbose > $output_dir/congestion.rpt

# Area report
report_area > $output_dir/area.rpt

# Power report
report_power -nosplit > $output_dir/power.rpt

puts "Reports generated"

puts "=========================================="
puts "Routing stage complete"
puts "=========================================="
exit 0