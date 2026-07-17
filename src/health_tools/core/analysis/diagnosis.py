"""依据规则和证据合成诊断结论。"""

from typing import Any, Dict, Optional

from health_tools.core.analysis.conditions import matches
from health_tools.models.rules import AnalysisRule


def _evidence(features: Dict[str, Any], cause: Optional[Dict[str, Any]]) -> str:
    if cause is None:
        return "未找到满足全部条件的原因模式"
    check_details = features.get("check_details")
    if isinstance(check_details, dict):
        keywords = {
            "data_incomplete": ("帧", "时间戳"),
            "data_range_invalid": ("范围",),
            "acc_invalid": ("ACC",),
            "signal_conversion_invalid": ("居中", "IPD"),
        }.get(str(cause.get("id", "")), ())
        selected = [
            f"{name}: {detail}"
            for name, detail in check_details.items()
            if any(keyword.upper() in str(name).upper() for keyword in keywords)
        ]
        if selected:
            return "；".join(selected)
    values = []
    for name in (
        "missing_ratio",
        "pi",
        "motion_rms",
        "mae",
        "max_error",
        "error_ratio",
        "presence",
        "clarity",
        "mean_frequency_difference_hz",
        "locked_ratio",
        "pulled_ratio",
        "harmonic_ratio",
    ):
        if name in features and features[name] is not None:
            value = features[name]
            values.append(f"{name}={value:.3g}" if isinstance(value, float) else f"{name}={value}")
    return "，".join(values) or cause.get("title", "")


def diagnose(features: Dict[str, Any], rule: AnalysisRule) -> Dict[str, Any]:
    if features.get("polar_review_required") and not features.get("reference_valid"):
        return {
            "cause": None,
            "conclusion": "证据不足",
            "confidence": 0.2,
            "evidence": "Polar 全局不可用，需人工复审；不据此进行错误归因",
            "actions": [],
        }
    causes = sorted(rule.causes, key=lambda item: int(item.get("priority", 0)), reverse=True)
    matched = None
    for cause in causes:
        if cause.get("origin") == "algorithm" and not (
            features.get("raw_valid")
            and features.get("reference_valid")
            and features.get("algorithm_abnormal")
        ):
            continue
        if matches(cause.get("when", {}), features):
            matched = cause
            break
    if matched is None:
        if features.get("raw_valid") and features.get("reference_valid"):
            if features.get("algorithm_abnormal"):
                return {
                    "cause": None,
                    "conclusion": "证据不足",
                    "confidence": 0.4,
                    "evidence": _evidence(features, None),
                    "actions": [],
                }
            return {
                "cause": None,
                "conclusion": "未发现异常",
                "confidence": 0.9,
                "evidence": "原始数据、参考数据和算法误差检查均未发现异常",
                "actions": [],
            }
        return {
            "cause": None,
            "conclusion": "证据不足",
            "confidence": 0.3,
            "evidence": _evidence(features, None),
            "actions": [],
        }
    origin = matched.get("origin")
    actions = list(matched.get("actions", [])) if origin == "raw" else []
    if origin == "reference":
        conclusion = "参考数据问题"
        confidence = 0.95
    elif origin == "raw" and actions:
        conclusion = "原始数据问题"
        confidence = 0.9
    elif origin == "raw" or origin == "algorithm":
        conclusion = "算法性能极限"
        confidence = 0.9 if features.get("psd_locked") or features.get("psd_harmonic") else 0.75
    else:
        conclusion = "证据不足"
        confidence = 0.4
    return {
        "cause": matched,
        "conclusion": conclusion,
        "confidence": confidence,
        "evidence": _evidence(features, matched),
        "actions": actions,
    }
