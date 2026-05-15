# LLM congestion 修复注入（第2轮）
set ::INJECT_PLACEDESIGN_BEFORE {
    puts "== AGENT: 多轮迭代修复place阶段congestion =="
    puts "第2轮：在次要热点区域添加blockage"
    createPlaceBlockage -box 405 970 487 1051 -type soft
}