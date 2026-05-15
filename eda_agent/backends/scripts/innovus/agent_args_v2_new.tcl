# 第2轮：根据新热点生成 blockage（第1轮后分析新的 congestion_map.rpt）
# 新热点1: bbox (365.52, 768.88, 526.80, 1010.80), score 50.10
# 新热点2: bbox (365.52, 728.56, 486.48, 809.20), score 13.84
set ::INJECT_PLACEDESIGN_BEFORE {
    puts "== AGENT: 第2轮迭代修复congestion =="
    puts "基于新热点分析结果生成修复策略"
    # 针对新热点，特别是热点1的核心区域
    createPlaceBlockage -box 380 775 520 1005 -type soft
}
