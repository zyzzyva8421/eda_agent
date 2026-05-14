#!/usr/bin/env tcl
#===============================================================================
# Innovus Floorplan Stage Script
# Usage: innovus -no_gui -overwrite -files floorplan.tcl
#===============================================================================

set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

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
if {[file exists "$saved_dir/pr.inv.dat"]} {
    restoreDesign $saved_dir/pr.inv.dat $design_name
    puts "Loaded from pr.inv.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView fplan
puts "Design loaded: $design_name"

# Step 2: Floorplan commands - create tighter floorplan for congestion
puts "Step 2: Creating floorplan..."

# Create very tight floorplan (95% utilization) to force congestion
setDesignMode -plate density 95

# Set tight aspect ratio
setDesignMode -aspect_ratio 1.0

# Run create_floorplan with much higher density to create congestion
create_floorplan -core_utilization 0.95 -aspect_ratio 1.0 \
    -left_existing 5 -bottom_existing 5 -right_existing 5 -top_existing 5

# Step 3: Save floorplan stage
puts "Step 3: Saving floorplan..."
saveDesign $output_dir/floorplan
puts "Floorplan saved to $output_dir/floorplan"

# Step 4: Generate reports
puts "Step 4: Generating reports..."
createSummaryReport -outdir $output_dir

puts "=========================================="
puts "Floorplan stage complete"
puts "=========================================="
exit 0