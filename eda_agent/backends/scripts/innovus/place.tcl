#!/usr/bin/env tcl
#===============================================================================
# Innovus Placement Stage Script
# Usage: innovus -no_gui -overwrite -files place.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# agent注入参数（如有）
if {[file exists "$design_dir/scripts/agent_args.tcl"]} {
    source $design_dir/scripts/agent_args.tcl
}
source $design_dir/scripts/inject_hook.tcl

# agent注入参数（如有）
if {[file exists "$design_dir/scripts/agent_args.tcl"]} {
    source $design_dir/scripts/agent_args.tcl
}
source $design_dir/scripts/inject_hook.tcl

# Output directory for this stage
set output_dir "$design_dir/work/place"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Placement Stage"
puts "=========================================="

# Step 1: Load design from powerplan
puts "Step 1: Loading design..."
if {[file exists "$design_dir/work/powerplan/powerplan.dat"]} {
    restoreDesign $design_dir/work/powerplan/powerplan.dat $design_name
    puts "Loaded from work/powerplan/powerplan.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Placement - aggressive for timing pressure and congestion
puts "Step 2: Running placement..."

createRouteBlk -box 383.838 765.249 487.976 1010.281
selectRouteBlk -box 383.8400 765.2500 487.9750 1010.2800 defLayerBlkName -layer Metal3
setSelectedRouteBlk 383.84 765.25 487.975 1010.28 defLayerBlkName {{1 } {2 } {V2 } {3 } {V3 } {4 } {V4 } {5 } {V5 } {6 } {V6 }} {Undefined ALLNET} {} {}

# Run placement
setPlaceMode -timingDriven true \
             -congEffort auto \
             -reorderScan false
placeDesign

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

# Congestion summary + hotspot map
earlyGlobalRoute
if {[catch {reportCongestion -overflow > $output_dir/congestion.rpt} err]} {
    puts "WARN: failed to generate congestion.rpt: $err"
}
if {[catch {reportCongestion -hotSpot > $output_dir/congestion_map.rpt} err]} {
    puts "WARN: failed to generate congestion_map.rpt: $err"
}

puts "Reports generated"

puts "=========================================="
puts "Placement stage complete"
puts "=========================================="
exit 0
