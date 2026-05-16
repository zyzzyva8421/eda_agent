#!/usr/bin/env tcl
#===============================================================================
# Innovus Powerplan Stage Script
# Usage: innovus -no_gui -overwrite -files powerplan.tcl
#===============================================================================

# Get job-specific workdir from environment (fallback to default)
if {[info exists ::env(JOB_WORKDIR)] && $::env(JOB_WORKDIR) ne ""} {
    set job_workdir $::env(JOB_WORKDIR)
} else {
    set job_workdir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1"
}

# Previous stage name (for restore)
if {[info exists ::env(PREV_STAGE)] && $::env(PREV_STAGE) ne ""} {
    set prev_stage $::env(PREV_STAGE)
} else {
    set prev_stage "floorplan"
}

# Previous job's workdir (for direct restore without copy)
if {[info exists ::env(PREV_JOB_DIR)] && $::env(PREV_JOB_DIR) ne ""} {
    set prev_job_dir $::env(PREV_JOB_DIR)
} else {
    set prev_job_dir ""
}

set design_name "DTMF_CHIP"
set design_dir "$job_workdir/FPR"
set saved_dir "$design_dir/saved"
set work_dir "$job_workdir/FPR/work"
set prev_work_dir "$prev_job_dir/FPR/work"

# Inject hook
if {[file exists "$job_workdir/scripts/inject_hook.tcl"]} {
    source $job_workdir/scripts/inject_hook.tcl
}

# Output directory for this stage
set output_dir "$work_dir/powerplan"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Powerplan Stage"
puts "Job workdir: $job_workdir"
puts "=========================================="

# Step 1: Load design from previous stage
# Prefer direct restore from previous job directory (no copy needed)
puts "Step 1: Loading design from previous stage: $prev_stage..."
if {$prev_job_dir ne ""} {
    set prev_db "$prev_work_dir/$prev_stage/${prev_stage}.dat"
    puts "Trying direct restore from prev_job_dir: $prev_db"
} else {
    set prev_db "$work_dir/$prev_stage/${prev_stage}.dat"
}
if {[file exists $prev_db]} {
    restoreDesign $prev_db $design_name
    puts "Loaded from $prev_db"
} else {
    puts "ERROR: No design found to restore from $prev_db"
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
report_power > $output_dir/power.rpt

puts "Reports generated"

puts "=========================================="
puts "Powerplan stage complete"
puts "=========================================="
exit 0
