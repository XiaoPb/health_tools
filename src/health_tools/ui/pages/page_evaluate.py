"""准确率评估页面"""

import streamlit as st

from health_tools.core.evaluator import BatchEvaluator
from health_tools.models.rules import EvaluateRule
from health_tools.rules.loader import RuleLoader
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import dir_input, output_input

st.header("Evaluate - 准确率评估")

with st.sidebar:
    chip_rule = chip_select(key="eval_chip")

input_dir = dir_input("输入目录", key="eval_input")
output_path = output_input("输出目录", key="eval_output")

eval_type = st.selectbox("评估类型", ["hr", "spo2"], key="eval_type")

c1, c2 = st.columns(2)
ref_column = c1.text_input("参考列", value="REF_RESULT0", key="eval_ref")
pred_column = c2.text_input("预测列", value="ALGO_RESULT0", key="eval_pred")

c1, c2 = st.columns(2)
diff_threshold = c1.number_input(
    "差值阈值", value=30.0 if eval_type == "hr" else 5.0, key="eval_diff"
)
stale_minutes = c2.number_input("停滞时间 (分钟)", value=2.0, key="eval_stale")

if st.button("执行评估", type="primary", key="eval_run"):
    if input_dir is None:
        st.error("请输入有效输入目录")
        st.stop()
    if not output_path:
        st.error("请输入输出目录")
        st.stop()

    from pathlib import Path

    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    rule_file = f"evaluate_{eval_type}.yaml"
    try:
        rule = RuleLoader.load_evaluate_rule(rule_file)
    except Exception:
        rule = EvaluateRule(type=eval_type)

    rule.ref_column = ref_column
    rule.pred_column = pred_column
    rule.anomaly["diff_threshold"] = diff_threshold
    rule.anomaly["stale_minutes"] = stale_minutes

    evaluator = BatchEvaluator(rule, chip_rule=chip_rule)
    results = evaluator.evaluate_directory(input_dir, out_dir, verbose=False)

    if results:
        st.success("评估完成")
        with st.expander("输出文件"):
            for name, path in results.items():
                st.text(f"{name}: {path}")
    else:
        st.warning("无评估结果")
