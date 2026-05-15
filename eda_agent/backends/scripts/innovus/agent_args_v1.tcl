# LLM congestion 修复注入（多轮迭代版本）
# 第1轮注入：热点区域添加blockage
set ::INJECT_PLACEDESIGN_BEFORE {
    puts "== AGENT: 多轮迭代修复place阶段congestion =="
    puts "第1轮：在主要热点区域添加blockage"
    createPlaceBlockage -box 365 768 527 1011 -type hard
    createPlaceBlockage -box 365 728 487 810 -type soft
}