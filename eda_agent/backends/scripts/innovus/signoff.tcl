#!/usr/bin/env tcl
#===============================================================================
# Innovus Signoff Stage Script
# Usage: innovus -no_gui -overwrite -files signoff.tcl
#===============================================================================

source $design_dir/scripts/inject_hook.tcl


set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"
set postroute_dir "$design_dir/work/postroute"

# agent注入参数（如有）
if {[file exists "$design_dir/scripts/agent_args.tcl"]} {
    source $design_dir/scripts/agent_args.tcl
}
source $design_dir/scripts/inject_hook.tcl


# Output directory for this stage
set output_dir "$design_dir/work/signoff"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Signoff Stage"
puts "=========================================="

# Step 1: Load design from postroute
puts "Step 1: Loading design..."
if {[file exists "$postroute_dir/postroute.dat"]} {
    restoreDesign $postroute_dir/postroute.dat $design_name
    puts "Loaded from work/postroute/postroute.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
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
