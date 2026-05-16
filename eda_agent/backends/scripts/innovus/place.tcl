#!/usr/bin/env tcl
#===============================================================================
# Innovus Placement Stage Script
# Usage: innovus -no_gui -overwrite -files place.tcl
#===============================================================================

# Get job-specific workdir from environment (fallback to default)
if {[info exists ::env(JOB_WORKDIR)] && $::env(JOB_WORKDIR) ne ""} {
    set job_workdir $::env(JOB_WORKDIR)
} else {
    set job_workdir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1"
}

# Previous stage name (for restore from previous stage output)
if {[info exists ::env(PREV_STAGE)] && $::env(PREV_STAGE) ne ""} {
    set prev_stage $::env(PREV_STAGE)
} else {
    set prev_stage "powerplan"
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

# agent注入参数（如有）- use job-specific dir
if {[file exists "$job_workdir/scripts/agent_args.tcl"]} {
    source $job_workdir/scripts/agent_args.tcl
}
if {[file exists "$job_workdir/scripts/inject_hook.tcl"]} {
    source $job_workdir/scripts/inject_hook.tcl
}

# Output directory for this stage in job workdir
set output_dir "$work_dir/place"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Placement Stage"
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

# Step 3: Save placement stage to job workdir
puts "Step 3: Saving placement to job workdir..."
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
