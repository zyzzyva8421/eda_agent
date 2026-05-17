# inject_hook.tcl
# 通用命令注入钩子，支持 BEFORE/AFTER 注入
# 用法：
#   1. agent 通过 set ::INJECT_<CMD>_BEFORE {tcl代码} 或 ::INJECT_<CMD>_AFTER 传递注入内容
#   2. stage 脚本头部 source 本文件
#   3. 支持多命令注入

proc __inject_hook {cmd} {
    set before_var ::INJECT_[string toupper $cmd]_BEFORE
    set after_var  ::INJECT_[string toupper $cmd]_AFTER
    # 如果原始命令已被rename，则跳过
    if {[llength [info commands __orig__$cmd]] > 0} { return }
    if {[llength [info commands $cmd]] == 0} { return }
    rename $cmd __orig__$cmd
    proc $cmd {args} [string map [list CMD $cmd BEFORE_VAR $before_var AFTER_VAR $after_var] {
        if {[info exists BEFORE_VAR]} {
            eval $BEFORE_VAR
        }
        set rc [catch {eval __orig__CMD $args} result]
        if {[info exists AFTER_VAR]} {
            eval $AFTER_VAR
        }
        if {$rc} { return -code error $result }
        return $result
    }]
}

# 支持的命令列表，可扩展
set ::INJECT_HOOK_COMMANDS {placeDesign optDesign routeDesign ccopt_design}
foreach cmd $::INJECT_HOOK_COMMANDS {
    puts "DEBUG: Setting up hook for: $cmd"
    __inject_hook $cmd
}

# Verify hooks are set up
puts "DEBUG: INJECT_HOOK_COMMANDS loaded"
