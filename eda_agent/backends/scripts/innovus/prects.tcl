#!/usr/bin/env tcl
#===============================================================================
# Innovus Pre-CTS Optimization Stage Script
# Usage: innovus -no_gui -overwrite -files prects.tcl
#===============================================================================

# 注入钩子，支持 agent 侧参数注入
source $design_dir/scripts/inject_hook.tcl


set design_name "DTMF_CHIP"
set design_dir "/home/host/InnovusBlk_18_1.tar/InnovusBlk_18_1/FPR"
set saved_dir "$design_dir/saved"

# agent注入参数（如有）
if {[file exists "$design_dir/scripts/agent_args.tcl"]} {
    source $design_dir/scripts/agent_args.tcl
}
source $design_dir/scripts/inject_hook.tcl


# Output directory for this stage
set output_dir "$design_dir/work/prects"
file mkdir $output_dir

suppressMessage ENCEXT-2799
encMessage warning 0

puts "=========================================="
puts "Innovus Pre-CTS Optimization Stage"
puts "=========================================="

# Step 1: Load design from placement
puts "Step 1: Loading design..."
if {[file exists "$design_dir/work/place/place.dat"]} {
    restoreDesign $design_dir/work/place/place.dat $design_name
    puts "Loaded from work/place/place.dat"
} else {
    puts "ERROR: No design found to restore"
    exit 1
}

setDrawView place
puts "Design loaded: $design_name"

# Step 2: Set aggressive timing constraints to create slack violations
puts "Step 2: Setting timing constraints..."
if {[catch {setTimingRemoveUncertainty -setup -clock_latency -early -late} err]} { puts "WARN: setTimingRemoveUncertainty unsupported: $err" }
if {[catch {setTimingUncertainty -setup 0.05 -clock_latency 0.02 [get_clocks *]} err]} { puts "WARN: setTimingUncertainty unsupported: $err" }
if {[catch {setMaxDelay 0.1 -from [all_loads] -to [all_registers]} err]} { puts "WARN: setMaxDelay unsupported: $err" }
puts "Timing constraints set"

# Step 3: Pre-CTS optimization
puts "Step 3: Running pre-CTS optimization..."
optDesign -preCTS -setup
puts "Pre-CTS optimization complete"

# Step 4: Save stage
puts "Step 4: Saving pre-CTS..."
saveDesign $output_dir/prects
puts "Pre-CTS saved to $output_dir/prects"

# Step 5: Generate reports
puts "Step 5: Generating reports..."
report_timing > $output_dir/timing.rpt
report_area > $output_dir/area.rpt
report_power > $output_dir/power.rpt
if {[catch {reportCongestion -overflow > $output_dir/congestion.rpt} err]} {
    puts "WARN: failed to generate congestion.rpt: $err"
}
if {[catch {reportCongestion -hotSpot > $output_dir/congestion_map.rpt} err]} {
    puts "WARN: failed to generate congestion_map.rpt: $err"
}

puts "Reports generated"

puts "=========================================="
puts "Pre-CTS optimization stage complete"
puts "=========================================="
exit 0
