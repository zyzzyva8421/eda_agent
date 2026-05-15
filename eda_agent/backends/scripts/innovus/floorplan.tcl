#!/usr/bin/env tcl
#===============================================================================
# Innovus Floorplan Stage Script
# Usage: innovus -no_gui -overwrite -files floorplan.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# agent注入参数（如有）
if {[file exists "$design_dir/scripts/agent_args.tcl"]} {
    source $design_dir/scripts/agent_args.tcl
}
source $design_dir/scripts/inject_hook.tcl

# Output directory for this stage
set output_dir "$design_dir/work/floorplan"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Floorplan Stage"
puts "=========================================="

# Step 1: Load design (start from saved pre-floorplan state or def)
puts "Step 1: Loading design..."
if {[file exists "$saved_dir/DTMF_CHIP.dat"]} {
    restoreDesign $saved_dir/DTMF_CHIP.dat $design_name
    puts "Loaded from DTMF_CHIP.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView fplan
puts "Design loaded: $design_name"

# Step 3: Save floorplan stage
puts "Step 3: Saving floorplan..."
saveDesign $output_dir/floorplan
puts "Floorplan saved to $output_dir/floorplan"

# Step 4: Generate reports
puts "Step 4: Generating reports..."
report_area > $output_dir/area.rpt

puts "=========================================="
puts "Floorplan stage complete"
puts "=========================================="
exit 0