#!/usr/bin/env tcl
#===============================================================================
# Innovus Floorplan Stage Script
# Usage: innovus -no_gui -overwrite -files floorplan.tcl
#===============================================================================

# Get job-specific workdir from environment (fallback to default)
if {[info exists ::env(JOB_WORKDIR)] && $::env(JOB_WORKDIR) ne ""} {
    set job_workdir $::env(JOB_WORKDIR)
} else {
    set job_workdir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1"
}

# Get case directory (base workdir without /runs/<run_id>)
if {[info exists ::env(CASE_DIR)] && $::env(CASE_DIR) ne ""} {
    set case_dir $::env(CASE_DIR)
} else {
    # Extract base dir by removing /runs/<run_id> suffix
    set case_dir $job_workdir
    if {[string match "*runs*" $case_dir]} {
        # Remove /runs/<run_id> suffix
        regexp {(.*runs)/[^/]+$} $case_dir match case_dir
    }
}

set design_name "DTMF_CHIP"
set design_dir "$job_workdir/FPR"
set saved_dir "$case_dir/FPR/saved"
set work_dir "$job_workdir/FPR/work"

# Inject hook
if {[file exists "$job_workdir/scripts/inject_hook.tcl"]} {
    source $job_workdir/scripts/inject_hook.tcl
}

# Output directory for this stage
set output_dir "$work_dir/floorplan"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Floorplan Stage"
puts "Job workdir: $job_workdir"
puts "=========================================="

# Step 1: Load design from saved
puts "Step 1: Loading design..."
set saved_db "$saved_dir/${design_name}.dat"
if {[file exists $saved_db]} {
    restoreDesign $saved_db $design_name
    puts "Loaded from $saved_db"
} else {
    puts "ERROR: No design found to restore from $saved_db"
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