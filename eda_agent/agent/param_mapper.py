"""
Innovus PPA 参数映射 - 基于 /home/aliu/Desktop/hello/me 项目

定义各阶段可调参数、取值范围、影响关系、约束条件
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class OptimizationObjective(Enum):
    """优化目标"""
    SETUP = "setup"          # 改善 timing (WNS/TNS)
    LEAKAGE = "leakage"      # 最小化漏电功耗
    DYNAMIC = "dynamic"      # 最小化动态功耗
    AREA = "area"            # 最小化面积
    CONGESTION = "congestion" # 减少拥塞


class FlowStage(Enum):
    """Innovus 流程阶段（与当前 flow 脚本对齐）"""

    SYNTH = "synth"
    FLOORPLAN = "floorplan"
    POWERPLAN = "powerplan"
    PLACE = "place"
    CTS = "cts"
    ROUTE = "route"
    SIGNOFF = "signoff"


@dataclass
class ParameterSpec:
    """单个参数规范"""
    name: str
    tcl_command: str           # e.g., "setPlaceMode -congEffort"
    param_type: str            # "enum", "numeric", "boolean"
    sample_values: List[Any]   # 采样值
    base_value: Any            # 基准值（默认值）
    stage: str                 # 参数族阶段: "prects", "cts", "postcts", "route", "postroute", "global"
    flow_stages: List[str] = field(default_factory=list)  # 作用到的 flow 阶段
    
    # PPA 影响（相对于基准）
    timing_impact: int = 0      # -2 to +2 (负数恶化，正数改善)
    power_impact: int = 0       # -2 to +2
    area_impact: int = 0        # -2 to +2
    congestion_impact: int = 0  # -2 to +2
    
    dependencies: List[str] = field(default_factory=list)  # 依赖的其他参数
    conflicts: List[str] = field(default_factory=list)     # 冲突的参数
    description: str = ""
    
    def is_compatible(self, param_dict: Dict[str, Any]) -> bool:
        """检查当前参数是否与其他参数兼容"""
        for conflict in self.conflicts:
            if conflict in param_dict:
                return False
        return True


class InnovusParamMapper:
    """Innovus PPA 参数映射管理"""
    
    def __init__(self):
        self.params: Dict[str, ParameterSpec] = {}
        self.stage_aliases: Dict[str, List[str]] = {
            FlowStage.SYNTH.value: ["global"],
            FlowStage.FLOORPLAN.value: ["global"],
            FlowStage.POWERPLAN.value: ["global"],
            FlowStage.PLACE.value: ["prects", "global"],
            FlowStage.CTS.value: ["cts", "postcts", "global"],
            FlowStage.ROUTE.value: ["route", "postroute", "global"],
            FlowStage.SIGNOFF.value: ["postroute", "global"],
        }
        self._init_prects_params()
        self._init_cts_params()
        self._init_postcts_params()
        self._init_route_params()
        self._init_postroute_params()
    
    def _init_prects_params(self):
        """PRECTS 阶段（Pre-CTS Optimization）"""
        
        # 拥塞度相关
        self.params["design_cong_effort"] = ParameterSpec(
            name="design_cong_effort",
            tcl_command="set_db design_cong_effort",
            param_type="enum",
            sample_values=["auto", "high"],
            base_value="auto",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1, congestion_impact=-2,
            description="Design level congestion effort"
        )
        
        self.params["place_global_cong_effort"] = ParameterSpec(
            name="place_global_cong_effort",
            tcl_command="set_db place_global_cong_effort",
            param_type="enum",
            sample_values=["base", "auto", "high", "extreme"],
            base_value="base",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1, congestion_impact=-3, area_impact=-1,
            description="Place global congestion effort (extreme=最激进)"
        )
        
        self.params["place_cong_effort"] = ParameterSpec(
            name="place_cong_effort",
            tcl_command="setPlaceMode -congEffort",
            param_type="enum",
            sample_values=["auto", "low", "high"],
            base_value="auto",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=2, congestion_impact=-2, area_impact=-1,
            description="Placement congestion effort"
        )
        
        # Placement 相关
        self.params["place_ppa_2"] = ParameterSpec(
            name="place_ppa_2",
            tcl_command="setPlaceMode -exp_skp_scale_WT_cost_ratio",
            param_type="numeric",
            sample_values=[0.5, 1, 2, 3, 5, 6, 10],
            base_value=5,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1, power_impact=-1,
            description="Timing vs Congestion weight (lower=timing优先, higher=congestion优先)"
        )
        
        self.params["place_global_SPP_enhancement"] = ParameterSpec(
            name="place_global_SPP_enhancement",
            tcl_command="setPlaceMode -place_global_exp_SPP_enhancement_v2",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            power_impact=-1,
            dependencies=["read_activity_file"],
            description="Activity-aware power-driven placement (需要 activity file)"
        )

        self.params["place_global_spp_multipass"] = ParameterSpec(
            name="place_global_spp_multipass",
            tcl_command="setPlaceMode -place_global_exp_spp_multipass",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            power_impact=-1,
            dependencies=["read_activity_file"],
            description="SPP multipass optimization (需要 activity file 与功能可用)"
        )
        
        self.params["place_detail_wire_length_opt_effort"] = ParameterSpec(
            name="place_detail_wire_length_opt_effort",
            tcl_command="setPlaceMode -place_detail_wire_length_opt_effort",
            param_type="enum",
            sample_values=["none", "medium", "high"],
            base_value="medium",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1, area_impact=1,
            description="Detailed placement wire length optimization effort"
        )
        
        # 流程相关
        self.params["design_flow_effort_3"] = ParameterSpec(
            name="design_flow_effort_3",
            tcl_command="set_db design_flow_effort",
            param_type="enum",
            sample_values=["standard", "extreme"],
            base_value="extreme",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value, FlowStage.CTS.value, FlowStage.ROUTE.value],
            timing_impact=2, power_impact=-1, congestion_impact=-1,
            description="Overall flow effort level (extreme=最激进优化)"
        )
        
        self.params["design_power_effort"] = ParameterSpec(
            name="design_power_effort",
            tcl_command="set_db design_power_effort + set_db opt_leakage_to_dynamic_ratio",
            param_type="enum",
            sample_values=["base", 0.001, 0.2, 0.5, 0.999],
            base_value="base",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value, FlowStage.CTS.value, FlowStage.ROUTE.value],
            power_impact=-2,
            description="Leakage vs Dynamic power weight (0.001=dynamic优先, 0.999=leakage优先)"
        )

        self.params["place_ppa_1"] = ParameterSpec(
            name="place_ppa_1",
            tcl_command="setPlaceMode -NMPspreadOutFactor",
            param_type="numeric",
            sample_values=[0.5, 1, 1.5, 2],
            base_value=1,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1,
            congestion_impact=-1,
            description="Placement spread out 因子"
        )

        self.params["place_max_density"] = ParameterSpec(
            name="place_max_density",
            tcl_command="setPlaceMode -place_global_max_density",
            param_type="numeric",
            sample_values=[0.75, 0.8, 0.85, 0.9],
            base_value=0.85,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1,
            congestion_impact=-2,
            area_impact=-1,
            description="全局 placement 密度上限（越低越缓解拥塞）"
        )
        
        # 优化相关
        self.params["opt_all_end_points"] = ParameterSpec(
            name="opt_all_end_points",
            tcl_command="setOptMode -opt_all_end_points",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1, power_impact=-1,
            description="Optimize all endpoints (not just critical path)"
        )
        
        self.params["opt_fix_fanout_load"] = ParameterSpec(
            name="opt_fix_fanout_load",
            tcl_command="setOptMode -opt_fix_fanout_load",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1, area_impact=1,
            description="Fix high fanout loads"
        )

        self.params["opt_max_length"] = ParameterSpec(
            name="opt_max_length",
            tcl_command="setOptMode -opt_max_length",
            param_type="numeric",
            sample_values=[-1],
            base_value=-1,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1,
            description="长连线优化长度阈值（-1 表示关闭）"
        )
        
        self.params["opt_podv2_flow_effort"] = ParameterSpec(
            name="opt_podv2_flow_effort",
            tcl_command="setOptMode -opt_pod_v2_effort",
            param_type="enum",
            sample_values=["auto", "standard", "extreme"],
            base_value="auto",
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            power_impact=-2,
            description="Power Optimization Design v2 effort"
        )

        self.params["opt_skew_pre_cts"] = ParameterSpec(
            name="opt_skew_pre_cts",
            tcl_command="setOptMode -opt_skew_pre_cts",
            param_type="boolean",
            sample_values=[True, False],
            base_value=True,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=1,
            description="Pre-CTS skew aware optimization"
        )

        self.params["prects_multibit"] = ParameterSpec(
            name="prects_multibit",
            tcl_command="setOptMode -opt_multi_bit_flop_opt",
            param_type="enum",
            sample_values=[0, 1, 2, 3],
            base_value=0,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            power_impact=-1,
            area_impact=-1,
            description="Pre-CTS multibit 优化强度"
        )

        self.params["prects_usk"] = ParameterSpec(
            name="prects_usk",
            tcl_command="setOptMode -useful_skew",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="prects",
            flow_stages=[FlowStage.PLACE.value],
            timing_impact=2,
            description="Pre-CTS useful skew"
        )
    
    def _init_cts_params(self):
        """CTS 阶段（Clock Tree Synthesis）"""
        
        self.params["cts_clone_clock_gates"] = ParameterSpec(
            name="cts_clone_clock_gates",
            tcl_command="set_ccopt_property clone_clock_gates",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="cts",
            flow_stages=[FlowStage.CTS.value],
            timing_impact=2, power_impact=1, area_impact=2,
            description="Clone clock gates to improve skew (costs area+power)"
        )
        
        self.params["cts_ppa_2"] = ParameterSpec(
            name="cts_ppa_2",
            tcl_command="setOptMode -expPostCTSGlobalSkew + setOptMode -expGlobalSkewEffort",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="cts",
            flow_stages=[FlowStage.CTS.value],
            timing_impact=2,
            description="Post-CTS global skew optimization (post-CTS stage)"
        )
        
        self.params["cts_target_skew_1"] = ParameterSpec(
            name="cts_target_skew_1",
            tcl_command="set_ccopt_property skew_target",
            param_type="enum",
            sample_values=["base", "v0", "v1", "v2", "v3"],
            base_value="base",
            stage="cts",
            flow_stages=[FlowStage.CTS.value],
            timing_impact=1,
            description="Target skew level (v3=最激进, v0=保守)"
        )

        self.params["cts_use_inverters"] = ParameterSpec(
            name="cts_use_inverters",
            tcl_command="set_db cts_use_inverters",
            param_type="enum",
            sample_values=["auto", True],
            base_value="auto",
            stage="cts",
            flow_stages=[FlowStage.CTS.value],
            timing_impact=1,
            power_impact=-1,
            description="CTS 中允许使用 inverter（依赖库设置）"
        )

        self.params["postcts_multibit_1"] = ParameterSpec(
            name="postcts_multibit_1",
            tcl_command="setOptMode -opt_multi_bit_flop_opt",
            param_type="enum",
            sample_values=[0, 1, 2, 3],
            base_value=0,
            stage="cts",
            flow_stages=[FlowStage.CTS.value],
            power_impact=-1,
            area_impact=-1,
            description="Post-CTS multibit 优化等级"
        )
    
    def _init_postcts_params(self):
        """POST-CTS 阶段（Post-CTS Optimization）"""
        
        self.params["postcts_ppa_2"] = ParameterSpec(
            name="postcts_ppa_2",
            tcl_command="setOptMode -skewClock* (with setUsefulSkewMode -noBoundary)",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="postcts",
            flow_stages=[FlowStage.CTS.value],
            timing_impact=2, area_impact=1,
            description="Post-CTS useful skew optimization (hold fixing)"
        )
    
    def _init_route_params(self):
        """ROUTE 阶段（Detailed Routing）"""
        
        self.params["route_ppa_2"] = ParameterSpec(
            name="route_ppa_2",
            tcl_command="setNanoRouteMode -routeExpWithEdr",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="route",
            flow_stages=[FlowStage.ROUTE.value],
            timing_impact=1, power_impact=1, area_impact=-1,
            description="Enable EDR (Enhanced Detailed Routing)"
        )
        
        self.params["route_ppa_3"] = ParameterSpec(
            name="route_ppa_3",
            tcl_command="route_design -explicit_clock_routing",
            param_type="boolean",
            sample_values=[False, True],
            base_value=False,
            stage="route",
            flow_stages=[FlowStage.ROUTE.value],
            timing_impact=1,
            description="Explicit clock routing before signal routing"
        )
    
    def _init_postroute_params(self):
        """POST-ROUTE 阶段（Post-Route Optimization）"""
        
        self.params["design_flow_effort_2"] = ParameterSpec(
            name="design_flow_effort_2",
            tcl_command="set_db design_flow_effort",
            param_type="enum",
            sample_values=["standard", "extreme"],
            base_value="standard",
            stage="postroute",
            flow_stages=[FlowStage.ROUTE.value, FlowStage.SIGNOFF.value],
            timing_impact=2, power_impact=-1,
            description="Post-route optimization effort (extreme=最激进)"
        )

        self.params["route_timing_driven"] = ParameterSpec(
            name="route_timing_driven",
            tcl_command="setNanoRouteMode -routeWithTimingDriven",
            param_type="boolean",
            sample_values=[False, True],
            base_value=True,
            stage="global",
            flow_stages=[FlowStage.ROUTE.value],
            timing_impact=1,
            power_impact=1,
            description="Timing-driven routing 全局开关"
        )
    
    def get_stage_params(self, stage: str) -> Dict[str, ParameterSpec]:
        """获取指定阶段的所有参数"""
        return {
            name: spec 
            for name, spec in self.params.items() 
            if spec.stage == stage
        }

    def get_flow_stage_params(self, flow_stage: str) -> Dict[str, ParameterSpec]:
        """按 Innovus 流程阶段获取参数（synth/floorplan/powerplan/place/cts/route/signoff）"""
        if flow_stage not in self.stage_aliases:
            return {}

        aliases = set(self.stage_aliases[flow_stage])
        return {
            name: spec
            for name, spec in self.params.items()
            if spec.stage in aliases or flow_stage in spec.flow_stages
        }

    def build_stage_catalog(self) -> Dict[str, List[Dict[str, Any]]]:
        """构建用于 UI/LLM 提示词的阶段参数目录"""
        catalog: Dict[str, List[Dict[str, Any]]] = {}
        for stage in FlowStage:
            entries: List[Dict[str, Any]] = []
            for name, spec in self.get_flow_stage_params(stage.value).items():
                entries.append(
                    {
                        "name": name,
                        "tcl_command": spec.tcl_command,
                        "type": spec.param_type,
                        "sample_values": spec.sample_values,
                        "base_value": spec.base_value,
                        "impact": {
                            "timing": spec.timing_impact,
                            "power": spec.power_impact,
                            "area": spec.area_impact,
                            "congestion": spec.congestion_impact,
                        },
                        "description": spec.description,
                    }
                )
            catalog[stage.value] = sorted(entries, key=lambda x: x["name"])
        return catalog
    
    def get_impact_score(self, 
                        params: Dict[str, Any],
                        objective: OptimizationObjective) -> float:
        """
        根据优化目标计算参数组合的预期影响度
        
        返回值：-10 ~ +10（越高越好）
        """
        score = 0.0
        
        for param_name, param_value in params.items():
            if param_name not in self.params:
                continue
            
            spec = self.params[param_name]
            
            if objective == OptimizationObjective.SETUP:
                score += spec.timing_impact * 2
            elif objective == OptimizationObjective.LEAKAGE:
                score += spec.power_impact * 2
            elif objective == OptimizationObjective.DYNAMIC:
                score += spec.power_impact * 2
            elif objective == OptimizationObjective.AREA:
                score += spec.area_impact * 2
            elif objective == OptimizationObjective.CONGESTION:
                score += spec.congestion_impact * 2
        
        return score
    
    def suggest_params(self, 
                      objective: OptimizationObjective,
                      design_constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        根据优化目标建议参数组合
        """
        suggested = {}
        design_constraints = design_constraints or {}
        
        if objective == OptimizationObjective.SETUP:
            # 优先改善 timing
            suggested = {
                "place_cong_effort": "high",
                "design_flow_effort_3": "extreme",
                "opt_all_end_points": True,
                "cts_clone_clock_gates": True,
                "postcts_ppa_2": True,
                "design_flow_effort_2": "extreme",
            }
        
        elif objective == OptimizationObjective.LEAKAGE:
            # 优先降低漏电
            suggested = {
                "design_power_effort": 0.999,
                "opt_podv2_flow_effort": "extreme",
                "cts_clone_clock_gates": False,
                "postcts_ppa_2": False,
            }
        
        elif objective == OptimizationObjective.DYNAMIC:
            # 优先降低动态功耗
            suggested = {
                "design_power_effort": 0.001,
                "place_global_SPP_enhancement": True,
                "cts_clone_clock_gates": False,
            }
        
        elif objective == OptimizationObjective.AREA:
            # 优先降低面积
            suggested = {
                "cts_clone_clock_gates": False,
                "design_flow_effort_3": "standard",
                "postcts_ppa_2": False,
                "opt_fix_fanout_load": False,
            }
        
        elif objective == OptimizationObjective.CONGESTION:
            # 优先减少拥塞
            suggested = {
                "design_cong_effort": "high",
                "place_global_cong_effort": "extreme",
                "route_ppa_2": True,
                "route_ppa_3": True,
            }
        
        return suggested
    
    def validate_params(self, params: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        验证参数组合的有效性
        
        返回：(is_valid, error_messages)
        """
        errors = []
        
        for param_name, param_value in params.items():
            if param_name not in self.params:
                errors.append(f"Unknown parameter: {param_name}")
                continue
            
            spec = self.params[param_name]
            
            # 检查值是否在采样值范围内
            if param_value not in spec.sample_values:
                errors.append(
                    f"{param_name}: value {param_value} not in sample_values {spec.sample_values}"
                )
            
            # 检查依赖关系
            for dep in spec.dependencies:
                if dep not in params:
                    errors.append(
                        f"{param_name} requires {dep}"
                    )
            
            # 检查冲突
            for conflict in spec.conflicts:
                if conflict in params:
                    errors.append(
                        f"{param_name} conflicts with {conflict}"
                    )
        
        return len(errors) == 0, errors


# 全局实例
PARAM_MAPPER = InnovusParamMapper()


if __name__ == "__main__":
    mapper = InnovusParamMapper()
    
    # 示例：获取 PRECTS 阶段参数
    print("=== PRECTS Parameters ===")
    prects_params = mapper.get_stage_params("prects")
    for name, spec in prects_params.items():
        print(f"{name}: {spec.sample_values} (base: {spec.base_value})")
    
    print("\n=== PLACE Flow Stage Catalog ===")
    for item in mapper.build_stage_catalog()["place"][:6]:
        print(f"{item['name']}: {item['sample_values']}")

    print("\n=== Suggest params for SETUP ===")
    suggested = mapper.suggest_params(OptimizationObjective.SETUP)
    print(suggested)
    
    print("\n=== Validate params ===")
    test_params = {
        "place_cong_effort": "high",
        "design_flow_effort_3": "extreme",
        "invalid_param": "value"
    }
    is_valid, errors = mapper.validate_params(test_params)
    print(f"Valid: {is_valid}")
    for err in errors:
        print(f"  - {err}")
