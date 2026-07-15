# VSHB Comp 与 Polar 准确度统计设计

## 目标

所有直接读取 VSHB 文件并统计心率准确度的流程，在现有指标之外同步统计
`comp vs polar`。当单个 VSHB 文件的 `comp` 列没有任何非零有效值时，跳过该文件的
`comp vs polar` 指标，不输出无意义的全零结果。

## 适用范围

本次改动覆盖两处现有 VSHB 准确度消费方：

- 离线跑库生成的 `accuracy_report.csv` 及多版本汇总报告。
- PSD 图片顶部显示的准确度摘要。

不修改通用 `evaluate`、`classify` 等不直接读取 VSHB 文件的准确度流程。

## VSHB 解析

共用 VSHB 读取器新增标准列 `comp`，所有消费方继续通过该读取器获得一致数据。

- 有表头文件依次兼容 `comp_hr`、`cmp_hr` 和 `comp` 列名，匹配时忽略大小写和首尾空白。
- 无表头旧格式使用 `polar` 后一列，即 0-based 索引 3，作为 `comp`。
- 有表头但缺少 comp 列时，以缺失值填充标准 `comp` 列，使文件仍可参与已有准确度统计。
- 无表头文件不足 4 列时，文件仍按现有必需列规则处理，但 `comp` 视为缺失。

读取结果的标准列顺序为 `time`、`offline`、`ref`、`online`、`comp`。

## 有效性与统计行为

每个 VSHB 文件独立判断 `comp`：至少存在一个大于 0 的数值时视为有效；全为 0、全为空值
或列缺失时均跳过 `comp vs polar`。

当 `polar` 存在有效值时：

- 保留现有 `offline vs polar` 和 `online vs polar` 指标。
- `comp` 有效时，在 `polar > 0` 的数据范围内计算 `comp vs polar`。
- 指标计算继续复用现有准确度函数及方法集合，预测值中的无效值按现有函数规则处理。

当 `polar` 全为 0 或无有效值时：

- 保留现有 `online vs offline` 降级逻辑。
- 不计算 `comp vs polar`，因为缺少其指定参考值。

## 报告与展示

离线报告使用 `(comp)` 后缀输出与现有 offline、online 相同的一组指标。分类平均和 `TOTAL`
仅对包含相应 comp 指标的文件进行加权，不让跳过的文件贡献零值。终端中的在线/离线准确度
表同时展示 comp 指标。

PSD 图片在 `comp` 和 `polar` 均有效时追加 `Comp vs Polar` 一行。`comp` 全为 0 或缺失时，
图片布局和指标行保持现状。叠加曲线本次不新增 comp 曲线，避免改变现有图例和可视区域；
需求仅涉及准确度统计。

## 文档与测试

更新 `docs/cmd_offline.md`，说明 comp 列识别、旧格式列位置、全零跳过和报告字段。

测试覆盖：

- 有表头 `comp_hr`、`cmp_hr` 和 `comp` 别名解析。
- 无表头文件从索引 3 读取 comp。
- 有效 comp 生成离线报告指标及正确汇总。
- comp 全为 0、缺失或 polar 无效时跳过 comp 指标。
- PSD 指标摘要按相同条件增加或省略 `Comp vs Polar`。
- 现有 VSHB 解析和准确度行为不回归。
