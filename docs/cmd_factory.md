# factory 命令

计算 SNR/CTR/Noise（产测用途）。别名：`fac`。

## 用法

```bash
ghealth_tool factory -i <input> -c <chip> [options]
ghealth_tool fac -i <input> -c <chip> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入 CSV 文件或目录 |
| `-c/--chip` | 芯片类型（指定 CSV 格式） |
| `-r/--rule` | 转换规则文件（指定 CSV 格式） |
| `--gain` | 增益参数（KΩ），覆盖芯片自动提取 |
| `--current` | 灯电流（mA），覆盖芯片自动提取 |
| `--sample-rate` | 采样率 Hz（默认使用芯片配置） |
| `--snr-cfg` | SNR 配置：skip_head,skip_tail,min_duration（如 10,10,90） |
| `--ctr-cfg` | CTR 配置：skip_head,skip_tail,min_duration（如 1,0,2） |
| `--noise-cfg` | Noise 配置：skip_head,skip_tail,min_duration（如 2,0,4） |
| `--adc-offset` | ADC 偏移量，覆盖芯片规则配置 |
| `--channels` | 指定计算通道（逗号分隔） |
| `-o/--output` | 输出结果 CSV 文件或目录 |
| `--filter` | 目录模式下仅处理文件名包含指定字符的 CSV |
| `-v/--verbose` | 详细输出 |

## 计算公式

| 指标 | 公式 |
|------|------|
| SNR | 20 * log10(Mean / Std) dB，0.5Hz 高通滤波后计算 |
| Noise | 6 * Std 转换为 uV：`(value - adc_offset) / adc_full_scale * adc_vref * 1e6` |
| CTR | `rawdata_uv / (tia_ratio * RF) * 1000` → ipd_pA，`ipd_pA / 1000 / iled` → nA/mA |

其中 `adc_full_scale`、`adc_offset`、`adc_vref`、`tia_ratio` 均从芯片规则的 `chip_info` 读取。

## 独立时长判断

每个指标有独立的数据时长要求（通过 `factory_config` 配置）：

- SNR：默认需要 90 秒，剔除前后各 10 秒
- CTR：默认需要 2 秒，剔除前 1 秒
- Noise：默认需要 4 秒，剔除前 2 秒

满足哪个指标的时长就计算哪个，全不满足时才跳过该通道。

## chip_info 自动提取

当芯片规则配置了 `chip_info` 时，自动从数据中提取每个通道的增益和灯电流：

- `gain`：从 AGC_INFO 列的指定位段提取增益等级，映射到 `gain_tia_map`
- `led_current_sum`：从 AGC_INFO 列提取总电流
- 当 `led_current_sum` 设为 `optional: true` 时，自动累加各 `led_current_drv*` 通道
- source 列全为 0 时视为无效数据，不计算 CTR（除非命令行指定 `--gain`/`--current`）

## 输出

- 表格显示每个通道的 SNR(dB)、CTR(nA/mA)、Noise(uV)、Mean、Max、Min、Gain、Current、采样率、数据时长
- 同时输出 chip_info 面板，显示每通道的 Gain 和 Current
- 目录模式输出“产测结果”汇总，读取失败、空文件、无有效通道等按原因统计
- 使用 `-v/--verbose` 时显示失败/跳过文件明细

## 输出文件命名

- 单文件模式：`factory_{文件名}.csv`
- 目录模式：`factory_{目录名}.csv`
- 指定 `-o` 为目录时：在该目录下生成上述文件名

## 示例

```bash
# 单文件计算
ghealth_tool fac -i data.csv -c gh3036_evk

# 目录批量计算
ghealth_tool fac -i data_dir/ -c gh3036_evk -v

# 指定增益和电流（覆盖自动提取）
ghealth_tool fac -i data.csv -c gh3036 --gain 10 --current 25.0

# 覆盖 SNR 时长配置
ghealth_tool fac -i data.csv -c gh3036_evk --snr-cfg "5,5,60"

# 输出到指定目录
ghealth_tool fac -i data_dir/ -c gh3036_evk -o results/
```
