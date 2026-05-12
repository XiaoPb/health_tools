# snr 命令

计算 SNR/CTR/Noise（产测用途）。

## 用法

```bash
ghealth_tool snr -i <input.csv> [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `-i/--input` | 输入 CSV 文件 |
| `-c/--chip` | 芯片类型（指定 CSV 格式） |
| `-r/--rule` | 转换规则文件（指定 CSV 格式） |
| `--gain` | 增益参数 |
| `--current` | 灯电流（mA） |
| `--sample-rate` | 采样率 Hz（默认: 100） |
| `--channels` | 指定计算通道（逗号分隔） |
| `-o/--output` | 输出结果 CSV 文件 |
| `-v/--verbose` | 详细输出 |

## 计算公式

| 指标 | 公式 |
|------|------|
| SNR | 20 * log10(Mean / Std) dB，0.5Hz 高通滤波后计算 |
| Noise | 6 * Std，转换为 uV：rawdata / 2^23 * 1.8 * 10^6 |
| CTR | Ipd / Iled (nA/mA) |

处理参数：
- 跳过前 10 秒数据
- 使用中间 50 秒数据
- 0.5Hz Butterworth 高通滤波

## 输出

表格显示每个通道的 SNR(dB)、Noise、CTR、Mean、Std、Min、Max。

## 示例

```bash
# 计算所有通道
ghealth_tool snr -i data.csv --chip gh3036

# 指定通道和参数
ghealth_tool snr -i data.csv --chip gh3036 --channels Ipd0,Ipd1 --gain 4.0 --current 20.0

# 输出到文件
ghealth_tool snr -i data.csv --chip gh3036 -o results.csv -v
```
