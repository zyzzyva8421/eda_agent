# LLM congestion 修复注入（基于真实 hotspot 数据）
# hotspot 1: bbox (365.52, 768.88, 526.80, 1010.80), score 48.20
# hotspot 2: bbox (365.52, 728.56, 486.48, 809.20), score 13.44
set ::INJECT_PLACEDESIGN_BEFORE {
    puts "== AGENT: LLM生成placement blockage修复 =="
    puts "在热点区域添加blockage以缓解congestion"
    createPlaceBlockage -box 365 768 527 1011 -type hard
    createPlaceBlockage -box 365 728 487 810 -type soft
}
