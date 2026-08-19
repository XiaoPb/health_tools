# plot 命令

绘制 PPG 数据的时域图、频域图、AC/PI 图、FFT 图和 STFT 时频图，也可复用离线结果
生成 PSD 时频图。

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
| `--type` | 图表类型: time\|freq\|stft\|psd\|ac\|fft\|both（默认: both） |
| `--channels` | 绘制通道；AC 模式支持用分号分组 |
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
| `--accuracy-thresholds` | PSD 固定准确度阈值，逗号分隔，默认 `5,10,15` |
| `--accuracy-inclusive/--accuracy-strict` | PSD 阈值边界包含/严格模式；默认 strict，即 `abs(error) < threshold` |
| `--no-show` | 仅保存不显示 |
| `--filter` | 目录模式下仅处理文件名包含指定字符的 CSV |
| `--workers` | 并发线程数，范围 1-8，默认 8 |
| `-v/--verbose` | 详细输出 |

## AC/PI 模式

指定 `--type ac` 时，每个通道组生成一张包含三个纵向子图的图片：

1. 原始 ACCX、ACCY、ACCZ 三轴；
2. 去基线并经过 `--bandpass` 带通滤波后的 PPG；
3. 各 PPG 通道的 PI 百分比。

同一通道在 PPG 和 PI 子图中使用相同颜色。每组最多包含 4 个 PPG 通道，PI 使用居中的
完整 5 秒滑动窗口计算：

```text
AC_RMS = RMS(窗口内带通后的 PPG)
DC_mean = Mean(窗口内原始 PPG)
PI = AC_RMS / DC_mean * 100%
```

首尾各约 2.5 秒没有完整窗口，因此不绘制 PI；`DC_mean` 为 0 时对应 PI 也为空。

`--channels` 使用逗号合并通道、分号划分输出组：

- `--channels "CH0,CH2"`：CH0 和 CH2 合并在一张图；
- `--channels "CH0"`：只绘制 CH0；
- `--channels "CH0,CH2;CH1"`：生成 CH0+CH2 合并图和 CH1 单通道图。

PowerShell 会把分号解释为命令分隔符，因此包含分号时必须给参数值加引号。显式分组的输出
文件名为 `<输入名>_ac_<通道组>.<格式>`。未指定 `--channels` 时，GH3036 自动选择前 4 个
非零 `Ipd*` 通道，GH3220 自动选择前 4 个非零 `CH*` 通道，输出为
`<输入名>_ac.<格式>`；其余非零通道会在终端中列为未绘制通道。

## FFT 模式

指定 `--type fft` 时，每个 PPG 通道生成一张 `<输入名>_fft_<通道>.<格式>`。图片在同一
频率轴上叠加原始 PPG 和带通后 PPG 的单边幅值谱，两条曲线使用独立 Y 轴。横轴不包含
`0 Hz` 的 DC 点，显示范围延伸到 Nyquist 频率。

FFT 未指定 `--channels` 时也按芯片自动识别所有非零 PPG 通道，不受 AC 模式每组 4 个
通道的限制。现有 `--type freq` 绘制 Welch PSD，与直接单边幅值谱的 `fft` 不同。

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

PSD 准确度默认使用 `5,10,15`，strict 模式按 `abs(error) < threshold` 计入；指定
`--accuracy-inclusive` 后按 `abs(error) <= threshold` 计入。

VSHB 的 `polar`、`offline`、`online`、`comp` 列中，没有任意一个 finite 且非 `0` 值的列
被禁用，不参与边界、比较或指标显示。剩余全部启用列共同确定首尾共享边界，即首个和最后
一个“所有启用列均为 finite 且非 `0`”的行；所有列使用同一切片。切片中间的 `0` 保留并
参与正常误差计算，`NaN`/`Inf` 仅在每个比较对象成对计算时过滤。

Polar 启用时，顶部为所有启用的 Offline、Online、Comp 分别显示 `vs Polar`；Polar 禁用
时，只有 Online 和 Offline 均启用才回退显示 `Online vs Offline`。各比较对象独立使用自己
的 `samples`，与 offline 报告的分类和 `TOTAL` 加权口径一致。Comp 启用时，PPG 子图额外
使用亮青色 `#00E5FF` 虚线绘制 comp，并在图例中显示 `comp`。绘图区按实际指标行数动态
下移；图例固定在 PPG 子图右上角，允许遮挡部分曲线或 PSD 内容。

PSD 模式复用 `offline` 命令的 PSD 绘图方式，`--format`、`--dpi`、`--channels`、
`--sample-rate` 等普通绘图参数不会影响 PSD 输出。直接使用 `plot --type psd` 时只把图片
保存到 `-o/--output` 指定目录，不在 VSHB 所在目录生成副本。

## STFT 数据处理流程

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

# 自动选择最多 4 个 PPG 通道绘制 AC/PI
ghealth_tool plot -i data.csv -o ./plots --chip gh3220 --type ac --no-show

# 两个合并通道组 + 一个单通道组（PowerShell 中需要引号）
ghealth_tool plot -i data.csv -o ./plots --chip gh3220 --type ac --channels "CH0,CH2;CH1" --no-show

# 分别绘制 CH0 和 CH2 的原始/带通后 FFT
ghealth_tool plot -i data.csv -o ./plots --chip gh3220 --type fft --channels CH0,CH2 --no-show

# 目录模式仅绘制文件名包含 valid 的 CSV
ghealth_tool plot -i ./csv/ -o ./plots --chip gh3036 --filter valid --no-show

# 离线结果目录生成 PSD 时频图
ghealth_tool plot -i ./offline_result/reorganized -o ./psd_plots --type psd

# 离线结果目录生成 PPG + ACCRMS PSD 时频图
ghealth_tool plot -i ./offline_result/reorganized -o ./psd_plots --type psd --psd-acc rms
```
