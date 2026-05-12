#!/usr/bin/env tcl
#===============================================================================
# Innovus CTS (Clock Tree Synthesis) Stage Script
# Usage: innovus -no_gui -overwrite -files cts.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# Output directory for this stage
set output_dir "$design_dir/work/cts"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus CTS Stage"
puts "=========================================="

# Step 1: Load design from placement
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

# Step 2: Clock tree synthesis
puts "Step 2: Running CTS..."

# Use Innovus CCOPT for CTS
create_ccopt_clock_tree_spec
ccopt_design

puts "CTS complete"

# Step 3: Save CTS stage
puts "Step 3: Saving CTS..."
saveDesign $output_dir/cts
puts "CTS saved to $output_dir/cts"

# Step 4: Generate reports
puts "Step 4: Generating reports..."

# Timing report
report_timing -nosplit -verbose > $output_dir/timing.rpt

# Clock tree report
report_ccopt_clock_tree_structure > $output_dir/clock_tree.rpt

# Area report
report_area > $output_dir/area.rpt

# Power report  
report_power -nosplit > $output_dir/power.rpt

puts "Reports generated"

puts "=========================================="
puts "CTS stage complete"
puts "=========================================="
exit 0