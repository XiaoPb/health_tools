"""安全的结构化条件求值，不执行规则中的任意代码。"""

from typing import Any, Mapping


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return (actual is not None) is bool(expected)
    if actual is None:
        return False
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "lt":
            return actual < expected
        if op == "le":
            return actual <= expected
        if op == "gt":
            return actual > expected
        if op == "ge":
            return actual >= expected
        if op == "in":
            return actual in expected
        if op == "not_in":
            return actual not in expected
        if op == "between":
            return expected[0] <= actual <= expected[1]
    except (TypeError, KeyError, IndexError):
        return False
    return False


def matches(condition: Mapping[str, Any], features: Mapping[str, Any]) -> bool:
    if "all" in condition:
        return all(matches(item, features) for item in condition["all"])
    if "any" in condition:
        return any(matches(item, features) for item in condition["any"])
    if "not" in condition:
        return not matches(condition["not"], features)
    feature = condition.get("feature")
    if not isinstance(feature, str):
        return False
    return _compare(features.get(feature), str(condition.get("op", "eq")), condition.get("value"))
