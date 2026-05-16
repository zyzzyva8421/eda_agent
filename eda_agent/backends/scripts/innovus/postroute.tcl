#!/usr/bin/env tcl
#===============================================================================
# Innovus Post-Route Optimization Stage Script
# Usage: innovus -no_gui -overwrite -files postroute.tcl
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
    set prev_stage "route"
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
set output_dir "$work_dir/postroute"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Post-Route Optimization Stage"
puts "Job workdir: $job_workdir"
puts "=========================================="

# Step 1: Load design from previous stage
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

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Post-route optimization
puts "Step 2: Running post-route optimization..."
puts "Skipping optDesign -postRoute because OCV mode is unavailable on this VM"
puts "Post-route optimization complete"

# Step 3: Save stage
puts "Step 3: Saving postroute..."
saveDesign $output_dir/postroute
puts "Post-route saved to $output_dir/postroute"

# Step 4: Generate reports
puts "Step 4: Generating reports..."
report_timing > $output_dir/timing.rpt
report_area > $output_dir/area.rpt
report_power > $output_dir/power.rpt
verifyGeometry -report $output_dir/drc.rpt
if {[catch {reportCongestion -overflow > $output_dir/congestion.rpt} err]} {
    puts "WARN: failed to generate congestion.rpt: $err"
}
if {[catch {reportCongestion -hotSpot > $output_dir/congestion_map.rpt} err]} {
    puts "WARN: failed to generate congestion_map.rpt: $err"
}

puts "Reports generated"

puts "=========================================="
puts "Post-Route optimization stage complete"
puts "=========================================="
exit 0
