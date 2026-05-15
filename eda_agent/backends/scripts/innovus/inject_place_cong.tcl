# agent注入示例：修复place阶段congestion
# 例如插入一个createPlaceBlockage命令
set ::INJECT_PLACEDESIGN_BEFORE {
    puts "== AGENT: 自动注入placement blockage修复 =="
    createPlaceBlockage -box 100 100 200 200 -type hard
}
