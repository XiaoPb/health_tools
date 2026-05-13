"""数据分类页面"""

import streamlit as st

from health_tools.core.classifier import DataClassifier
from health_tools.models.rules import ClassifyRule
from health_tools.rules.loader import RuleLoader
from health_tools.ui.components.chip_selector import chip_select
from health_tools.ui.components.file_picker import dir_input

st.header("Classify - 数据分类")

with st.sidebar:
    chip_rule = chip_select(key="cls_chip")

input_dir = dir_input("输入目录", key="cls_input")
output_dir = dir_input("输出目录", key="cls_output")

# 动态列出可用规则文件
builtin_dir = RuleLoader.get_builtin_rules_path() / "classify"
available_rules = sorted(f.name for f in builtin_dir.glob("*.yaml")) if builtin_dir.exists() else []
rule_options = available_rules + ["(自定义)"]
rule_choice = st.selectbox("分类规则", rule_options, key="cls_rule")

classify_rule = None
if rule_choice != "(自定义)":
    try:
        classify_rule = RuleLoader.load_classify_rule(rule_choice)
    except Exception as e:
        st.warning(f"加载规则失败: {e}")

if rule_choice == "(自定义)":
    st.markdown("**自定义分类规则**")
    filename_regex = st.text_input("文件名正则", key="cls_regex")
    fields_str = st.text_input("字段名 (逗号分隔)", key="cls_fields")
    default_dir = st.text_input("默认分类目录", value="unclassified", key="cls_default")

copy_mode = st.radio("操作模式", ["复制", "移动", "符号链接"], key="cls_mode")
calc_accuracy = st.checkbox("计算准确率", key="cls_acc")

if st.button("执行分类", type="primary", key="cls_run"):
    if input_dir is None:
        st.error("请输入有效输入目录")
        st.stop()
    if output_dir is None:
        st.error("请输入有效输出目录")
        st.stop()

    if classify_rule is None and rule_choice == "(自定义)":
        fields = [f.strip() for f in fields_str.split(",") if f.strip()]
        classify_rule = ClassifyRule(
            filename={"regex": filename_regex, "fields": fields},
            default=default_dir,
        )

    if classify_rule is None:
        st.error("无有效分类规则")
        st.stop()

    classifier = DataClassifier(classify_rule, chip_rule=chip_rule)
    classifier.create_structure(output_dir)

    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        st.warning("目录中无 CSV 文件")
        st.stop()

    results = {"成功": 0, "失败": 0}
    for f in csv_files:
        target = classifier.classify(f, output_dir)
        if target:
            results["成功"] += 1
        else:
            results["失败"] += 1

    st.success(f"分类完成: {results['成功']} 成功, {results['失败']} 失败")
