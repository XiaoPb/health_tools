# plot 命令

绘制 PPG 数据的时域图、频域图、STFT 时频图，也可复用离线结果生成 PSD 时频图。

## 用法

```bash
ghealth_tool plot -i <input.csv> -o <output_dir> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入 CSV 文件或目录；PSD 模式为离线结果目录 |
| `-o/--output` | 输出图片目录 |
| `-c/--chip` | 芯片类型（指定 CSV 格式） |
| `-r/--rule` | 转换规则文件（指定 CSV 格式） |
| `--type` | 图表类型: time\|freq\|stft\|psd\|both（默认: both） |
| `--channels` | 绘制通道（逗号分隔） |
| `--sample-rate` | 采样率 Hz（默认: 25） |
| `--window` | STFT 窗口大小秒（默认: 25） |
| `--overlap` | 窗口重叠率 0-1（默认: 0.96） |
| `--format` | 图片格式: png\|svg\|pdf（默认: png） |
| `--dpi` | 图片 DPI（默认: 150） |
| `--bandpass` | 带通滤波范围 Hz（默认: 0.5-4.0） |
| `--remove-baseline/--no-remove-baseline` | 启用或关闭基线去除（默认: 启用） |
| `--baseline-method` | 基线方法: mean\|median（默认: mean） |
| `--freq-bpm` | Y 轴显示 BPM（默认: 是） |
| `--freq-range` | 频率范围 BPM（默认: 30-240） |
| `--ref-column` | 参考曲线列名 |
| `--psd-acc` | PSD 模式下 ACC 绘图: `axis` 三轴 / `rms` 合成（默认: axis） |
| `--no-show` | 仅保存不显示 |
| `--filter` | 目录模式下仅处理文件名包含指定字符的 CSV |
| `-v/--verbose` | 详细输出 |

## STFT 时频图模式

### 模式 A：chip 自动模式

指定 `--chip` 且不指定 `--channels` 时自动触发：
- 自动检测非零 Ipd 通道
- 每个通道生成独立图片，包含 5 个子图：
  1. Ipd 通道 STFT
  2. ACCX STFT
  3. ACCY STFT
  4. ACCZ STFT
  5. CH - ACC（去运动伪影）
- 每个子图叠加 REF_RESULT0（红色虚线）+ ALGO_RESULT0（白色实线）

### 模式 B：手动通道模式

指定 `--channels` 时触发：
- 每个通道一个子图
- 统一处理流程：去基线 → 带通滤波 → STFT → 逐列归一化
- 支持 `--ref-column` 叠加参考折线

## PSD 时频图模式

指定 `--type psd` 时，输入路径必须是离线跑库整理后的结果目录，目录内包含
`*_result.vshb` 以及同名 `.prepsd`、`.accxpsd`、`.accypsd`、`.acczpsd` 文件。
输出目录无需提前创建，命令会自动创建并生成 PNG 图片。

默认 PSD 图包含 `PPG`、`ACCX`、`ACCY`、`ACCZ` 四个子图。指定
`--psd-acc rms` 时改为读取 `.accrmspsd`，只绘制 `PPG` 和 `ACCRMS`，不绘制
`ACCX/ACCY/ACCZ`。

PSD 模式复用 `offline` 命令的 PSD 绘图方式，`--format`、`--dpi`、`--channels`、
`--sample-rate` 等普通绘图参数不会影响 PSD 输出。

## 数据处理流程

1. 去基线（mean/median）
2. 带通滤波（Butterworth 4 阶）
3. STFT（hamming 窗）
4. 逐时间列 0-100 归一化（非 dB）
5. viridis colormap，BPM Y 轴 30-240

## 输出与异常汇总

- 输入为目录时递归处理 CSV，并使用进度条显示进度。
- 默认输出“绘图结果”汇总，成功文件不逐条打印。
- 空文件、格式不对、列缺失、读取失败和绘图失败会按原因统计。
- 使用 `-v/--verbose` 时显示失败/跳过文件明细，并保留每张图的保存路径提示。

## 示例

```bash
# chip 自动 STFT（每个非零 Ipd 通道一张图）
ghealth_tool plot -i data.csv -o ./plots --chip gh3036 --type stft --no-show -v

# 手动指定通道
ghealth_tool plot -i data.csv -o ./plots --chip gh3036 --type stft --channels Ipd0,Ipd1 --ref-column REF_RESULT0 --no-show -v

# 时域 + 频域
ghealth_tool plot -i data.csv -o ./plots --chip gh3036 --type both --channels Ipd0 --no-show -v

# 目录模式仅绘制文件名包含 valid 的 CSV
ghealth_tool plot -i ./csv/ -o ./plots --chip gh3036 --filter valid --no-show

# 离线结果目录生成 PSD 时频图
ghealth_tool plot -i ./offline_result/reorganized -o ./psd_plots --type psd

# 离线结果目录生成 PPG + ACCRMS PSD 时频图
ghealth_tool plot -i ./offline_result/reorganized -o ./psd_plots --type psd --psd-acc rms
```
