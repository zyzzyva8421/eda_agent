#!/usr/bin/env tcl
#===============================================================================
# Innovus Routing Stage Script
# Usage: innovus -no_gui -overwrite -files route.tcl
#===============================================================================

source $design_dir/scripts/inject_hook.tcl


set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# agent注入参数（如有）
if {[file exists "$design_dir/scripts/agent_args.tcl"]} {
    source $design_dir/scripts/agent_args.tcl
}
source $design_dir/scripts/inject_hook.tcl


# Output directory for this stage
set output_dir "$design_dir/work/route"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Routing Stage"
puts "=========================================="

# Step 1: Load design from postcts
puts "Step 1: Loading design..."
if {[file exists "$design_dir/work/postcts/postcts.dat"]} {
    restoreDesign $design_dir/work/postcts/postcts.dat $design_name
    puts "Loaded from work/postcts/postcts.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
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
report_timing > $output_dir/timing.rpt
verifyGeometry -report $output_dir/drc.rpt
if {[catch {reportCongestion -overflow > $output_dir/congestion.rpt} err]} {
    puts "WARN: failed to generate congestion.rpt: $err"
}
if {[catch {reportCongestion -hotSpot > $output_dir/congestion_map.rpt} err]} {
    puts "WARN: failed to generate congestion_map.rpt: $err"
}
report_area > $output_dir/area.rpt
report_power -nosplit > $output_dir/power.rpt

puts "Reports generated"

puts "=========================================="
puts "Routing stage complete"
puts "=========================================="
exit 0
