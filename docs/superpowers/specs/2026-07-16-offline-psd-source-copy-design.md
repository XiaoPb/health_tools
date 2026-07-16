# Offline PSD 双份保存与固定图例设计

## 目标

离线跑库生成 PSD 图片时，每个 VSHB 结果只渲染一次，同时把相同图片保存到现有集中输出
目录和该 VSHB 所在的整理目录。PPG 子图图例显式固定在右上角，不因曲线或数据范围改变
位置，允许遮挡部分图像内容。

## 图例位置

心率折线的动态图例继续只包含实际绘制的 offline、online、polar 和 comp 曲线，顺序保持
不变。调用 Matplotlib 图例时显式传入 `loc="upper right"`，不启用自动位置选择，也不把
图例移到图轴外。

## 双份保存范围

`PsdPlotter.plot` 增加一个默认关闭的同步保存参数。参数关闭时保持现有行为，只写
`save_dir`；参数开启时，同一渲染缓冲区写入两个位置：

- 主副本：`<版本输出>/psd_bmpfile/<base_name>.png`。
- 源目录副本：`<VSHB 所在目录>/<base_name>.png`。

例如：

```text
<版本输出>/数据整理/场景A/sample_result.vshb
<版本输出>/数据整理/场景A/sample.png
<版本输出>/psd_bmpfile/sample.png
```

只有 `ghealth_tool offline` 的绘图阶段开启该参数。`ghealth_tool plot --type psd`、Streamlit
页面和其他直接使用 `PsdPlotter` 的调用保持单份保存，避免改变已有输出契约。

## 数据流与返回值

每个 VSHB 仍只读取 PSD、创建 Figure 和执行 `canvas.draw()` 一次。得到 RGB 图像数组后，
先写主副本，再在开关开启时写源目录副本；两次写入使用同一个数组，保证内容逐像素一致。

`PsdPlotter.plot` 的返回列表继续只包含主副本路径，因此调用方的“生成 N 张”仍表示处理了
N 个 VSHB 文件，不把两份物理文件报告为 2N。offline 成功信息补充说明图片也已同步保存到
各 VSHB 目录。

## 错误处理

任一保存目标失败时，该 VSHB 按现有单文件异常机制输出 `PSD错误`，关闭 Figure 后继续处理
其他 VSHB。不开启同步保存时，不创建或写入 VSHB 所在目录的 PNG。

## 文档与测试

更新 `docs/cmd_offline.md`，说明集中目录和整理目录中的两份输出；更新 `docs/cmd_plot.md`，
明确直接使用 PSD 绘图仍只保存到指定输出目录。CLI 选项不变。

测试覆盖：

- 图例调用显式包含 `loc="upper right"`。
- 同步保存开启时，主副本和 VSHB 同目录副本都存在、非空且像素一致。
- 同步保存关闭时，只生成主副本。
- 嵌套 VSHB 在各自所在目录生成图片。
- offline 绘图阶段开启同步保存参数，普通 plot 调用保持默认关闭。
- 现有返回数量、进度和无有效 VSHB 行为不回归。
