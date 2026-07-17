# 端到端工作流

命令中的路径和芯片仅为模板。执行前使用真实输入、输出和规则替换，并运行当前命令帮助。

## 日志到检查与绘图

```bash
ghealth_tool validate custom_rules/parse/custom.yaml
ghealth_tool parse -i raw.log -o parsed.csv -r custom_rules/parse/custom.yaml
ghealth_tool check -i parsed.csv -c gh3220 -o check_report.csv
ghealth_tool plot -i parsed.csv -o plots/ -c gh3220 --type both --no-show
```

parse 规则必须包含 `target_chip: gh3220`，且解析列名与 chip 列名一致。验证：解析 CSV
非空，表头符合 chip 规则；检查报告存在；图像数量与输入文件相符。

## 陌生 CSV 转标准芯片格式

```bash
ghealth_tool info input.csv --schema --preview 5
ghealth_tool convert --init-rule -i input.csv -c gh3036 -o custom_rules/convert/vendor.yaml
ghealth_tool validate custom_rules/convert/vendor.yaml
ghealth_tool convert -i input.csv -o converted.csv -r custom_rules/convert/vendor.yaml -v
ghealth_tool check -i converted.csv -c gh3036
```

先编辑生成规则中的列映射。验证输出列顺序、参考列有效值以及
`extra_source_align_errors.csv` 是否出现。

## 检查并分拣

```bash
ghealth_tool check -i data/ -c gh3036 -o data/check_report.csv
ghealth_tool check --sort --report data/check_report.csv --sort-output sorted/
```

第二条命令会移动报告中的源文件。执行前确认报告路径和 `文件相对路径` 列指向正确数据。

## 分类与评估

```bash
ghealth_tool classify -i data/ -o classified/ -r spo2_posture.yaml --copy --report
ghealth_tool evaluate -i classified/ -o evaluation/ --type spo2 --rule evaluate_spo2.yaml
```

验证未分类文件数量、分类目录结构、参考/预测列缺失原因和准确度汇总的 TOTAL 行。

## 产测

```bash
ghealth_tool factory -i factory_data/ -c gh3036_evk -o factory_metrics.csv -v
```

若 chip 规则没有增益或灯电流提取信息，显式提供 `--gain`、`--current`。检查有效通道和
每项最短时长，不把“无有效通道”当作成功。

## 离线多版本跑库

```bash
ghealth_tool config --offline-path /path/to/offline_algorithm_tools
ghealth_tool offline --list --chip gh3220
ghealth_tool offline -i data/ -c gh3220 --versions version_a,version_b -v
```

运行前确认：输入表头严格符合 chip 规则、同级 `<input>_mv` 可以接收不合规文件、两个
版本的 `cmd_setting.yaml` 参数顺序正确。验证每个版本目录中的整理结果、PSD 和
`accuracy_report.csv`，以及根目录 `accuracy_report_all_versions.csv`。

已有结果可使用：

```bash
ghealth_tool offline -i data/ -o existing_result/ -c gh3220 \
  --versions version_a,version_b --no-run
```

`--no-run` 不检查或移动输入 CSV，也不调用外部算法。

## 自动分析

```bash
ghealth_tool analyze -i data/ -o analysis/ --type hr --report all --focus "动态/**/*.csv"
```

分析命令先运行检查和准确度阶段。`--focus` 命中的文件即使正常也会继续深度分析；证据不足时才在输出工作区副本上升级离线 PSD。结果目录也可以直接作为输入。验证 `analysis_summary.json`、`file_diagnosis.csv`、证据图和报告中的结论、证据及跳过原因。

基础问题以 `check` 的 FAIL 为准，准确度指标优先合并 `evaluate` 明细。证据图统一复用 `plot`：心率原始证据使用 time/ac，血氧默认使用 ac，离线时频图使用 psd。无法归因或不确定应附哪张图时，心率优先附 `plot psd` 产物；显式禁用离线时确认报告记录了未执行原因。汇总应分别展示 `Online vs Polar`、`Offline vs Polar` 的 MAE 和 ±5/±10/±15 bpm 占比；Comp 非零有效时才显示 `Comp vs Polar`。异常原始归类可与准确度表拆页，普通正常文件不堆叠证据图。
