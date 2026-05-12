#!/usr/bin/env tcl
#===============================================================================
# Innovus Powerplan Stage Script
# Usage: innovus -no_gui -overwrite -files powerplan.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/powerplan"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Powerplan Stage"
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

setDrawView fplan
puts "Design loaded: $design_name"

# Step 2: Power planning
puts "Step 2: Powerplan..."

# Add power rings
# createPowerRing -width 0.5 -spacing 0.5 -nets {VDD VSS}

# Add power stripes
# addPowerStripe -width 1.0 -spacing 5.0 -nets {VDD}

puts "Powerplan complete"

# Step 3: Save powerplan stage
puts "Step 3: Saving powerplan..."
saveDesign $output_dir/powerplan
puts "Powerplan saved to $output_dir/powerplan"

# Step 4: Generate reports
puts "Step 4: Generating reports..."
report_power -nosplit > $output_dir/power.rpt

puts "Reports generated"

puts "=========================================="
puts "Powerplan stage complete"
puts "=========================================="
exit 0