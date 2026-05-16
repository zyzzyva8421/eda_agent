#!/usr/bin/env tcl
#===============================================================================
# Innovus Signoff Stage Script
# Usage: innovus -no_gui -overwrite -files signoff.tcl
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
    set prev_stage "postroute"
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
set output_dir "$work_dir/signoff"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Signoff Stage"
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
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Wire optimization (if needed)
puts "Step 2: Running optimizations..."
puts "Skipping optDesign -postRoute in signoff stage"
puts "Optimization complete"

# Step 3: Save signoff stage
puts "Step 3: Saving signoff..."
saveDesign $output_dir/signoff
puts "Signoff saved to $output_dir/signoff"

# Step 4: Verification
puts "Step 4: Verification..."
verifyGeometry -report $output_dir/geom.rpt

# Step 5: Generate reports
puts "Step 5: Generating reports..."
report_timing > $output_dir/timing.rpt
report_qor -file $output_dir/qor.rpt
report_area > $output_dir/area.rpt
report_power > $output_dir/power.rpt
if {[catch {reportCongestion -overflow > $output_dir/congestion.rpt} err]} {
    puts "WARN: failed to generate congestion.rpt: $err"
}
if {[catch {reportCongestion -hotSpot > $output_dir/congestion_map.rpt} err]} {
    puts "WARN: failed to generate congestion_map.rpt: $err"
}
if {[llength [info commands report_rc]] > 0} {
    if {[catch {report_rc -detail > $output_dir/rc.rpt} rc_err]} {
        puts "WARN: report_rc failed: $rc_err"
    }
} else {
    puts "WARN: report_rc command not available; skip rc.rpt"
}

puts "Reports generated"

puts "=========================================="
puts "Signoff stage complete"
puts "=========================================="
exit 0
