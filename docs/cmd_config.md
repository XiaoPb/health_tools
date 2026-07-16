# config 命令

全局配置管理，设置用户级规则目录和离线工具配置。别名：`cfg`。

## 用法

```bash
ghealth_tool config [options]
ghealth_tool cfg [options]
```

## 参数

| 参数 | 说明 |
|------|------|
| `--init` | 初始化用户配置目录（~/.ghealth_tools/） |
| `--force` | 强制更新内置规则文件（覆盖已有） |
| `--show` | 显示当前配置（默认） |
| `--rules-dir` | 设置规则目录路径 |
| `--offline-path` | 设置离线工具搜索路径（自动扫描版本） |
| `--offline-default` | 设置芯片默认版本（格式: `chip=version`） |
| `--offline-scan` | 重新扫描离线工具版本 |

## 离线命令参数模板

`offline_versions` 只记录扫描到的算法版本和默认版本。`offline_cmd` 用来为特定
`芯片 + 算法版本` 指定传给 `TEE_Algorithm.exe` 的参数顺序和数量。

`cmd_arg` 写什么参数，最终命令就传什么参数；未写入 `cmd_arg` 的变量不会加入命令。
`cmd_default` 给 `start_idx`、`end_idx`、`datatype` 等非列索引变量提供默认值；未在
`cmd_default` 或内置变量表中出现的名称会按字面量传给 exe。
`accx`、`ppg_ch0`、`polar` 等列号不写在 `config.yaml` 中，会从 `rules/chip/<chip>.yaml`
自动推导，规则缺失时使用内置默认值。PPG 变量最大支持 `ppg_ch0..31`，但只有最终生效
`cmd_arg` 中出现的通道才会使用 `offline --ppg-offset/--ppg-map` 计算映射；写在
`cmd_default` 中不算声明。

也可以在每个 `TEE_Algorithm.exe` 同目录放置 `cmd_setting.yaml`，文件根节点直接包含
`cmd_arg` 和可选的 `cmd_default`：

```yaml
cmd_arg: [input_dir, output_dir, csv, hba_fs, scene_en, ch_num]
cmd_default:
  csv: csv
  scene_en: 0
```

本地配置存在时整份替换该版本的全局配置；不存在时才回退到 `config.yaml`。本地文件
损坏、`cmd_arg` 不是非空列表或 `cmd_default` 不是对象时，离线跑库会直接停止。完整
优先级为：本地 `cmd_setting.yaml`、全局 `offline_cmd` 版本配置、`offline_versions` 中的
版本/芯片配置、内置命令格式。命令行显式参数仍优先于所选配置的默认值。

按当前 GH3036 默认顺序，可配置为：

```yaml
offline_cmd:
  gh3036:
    GH_HR_exc_keep-B6lite_v1.0.1.2:
      cmd_arg:
        - start_idx
        - end_idx
        - input_dir
        - output_dir
        - csv
        - hba_fs
        - scene_en
        - datatype
        - ch_num
        - accx
        - accy
        - accz
        - ppg_ch0
        - ppg_ch1
        - ppg_ch2
        - ppg_ch3
        - polar
        - mcu_out
        - comp_out
      cmd_default:
        start_idx: 0
        end_idx: -1
        datatype: 0
        scene_en: 0
```

如果某个版本不需要 `comp_out`，只从 `cmd_arg` 删除 `comp_out` 即可。心率参考列使用
规范变量名 `polar`。PPG 通道也可以稀疏声明，例如只写 `ppg_ch0` 和 `ppg_ch4`；偏移
仍按变量自身编号计算。命令行指定未声明通道时，该设置会被忽略并输出 WARN。完整映射
语义与示例见 [`offline` 命令](cmd_offline.md#ppg-通道映射)。

## 配置目录结构

```
~/.ghealth_tools/
├── config.yaml                    # 配置文件
├── rules/                         # 用户规则目录
│   ├── chip/                      # 芯片定义（优先于内置规则）
│   ├── parse/                     # 解析规则
│   ├── classify/                  # 分类规则
│   ├── convert/                   # 转换规则
│   └── evaluate/                  # 评估规则
└── offline_algorithm_tools/       # 离线算法工具目录
    ├── gh3036/
    │   └── <category>/            # exclusive/premium/medium/basic
    │       └── <version>/
    │           └── TEE_Algorithm.exe
    └── gh3220/
        └── <category>/
            └── <version>/
                └── TEE_Algorithm.exe
```

## 规则优先级

1. 绝对路径 → 直接使用
2. 用户规则目录 `~/.ghealth_tools/rules/<type>/` → 存在则优先
3. 内置规则目录 → 兜底

## 输出与失败条件

- 不带修改选项时等同于 `--show`，只在终端显示当前规则目录和离线版本配置。
- `--init` 创建 `~/.ghealth_tools/`；已有规则默认不覆盖，配合 `--force` 才更新。
- `--offline-path` 必须指向可访问目录，设置后立即扫描芯片、等级和版本。
- `--offline-default` 使用 `chip=version` 格式，芯片或版本未扫描到时返回错误。
- 配置以 UTF-8 YAML 保存；无效 YAML 或本地 `cmd_setting.yaml` 会由使用它的命令报告。

## 示例

```bash
# 初始化配置
ghealth_tool cfg --init

# 查看配置
ghealth_tool cfg --show

# 修改规则目录
ghealth_tool cfg --rules-dir /path/to/custom/rules

# 设置离线工具路径（自动扫描版本）
ghealth_tool cfg --offline-path /path/to/offline_algorithm_tools

# 重新扫描离线工具版本
ghealth_tool cfg --offline-scan

# 设置芯片默认算法版本
ghealth_tool cfg --offline-default gh3220=V4300_GH_HR_exc_pv_v2.0.3.0

# 添加自定义芯片支持（初始化后复制模板修改即可）
cp src/health_tools/rules/chip/gh3036.yaml ~/.ghealth_tools/rules/chip/my_chip.yaml
# 编辑 my_chip.yaml 后即可使用:
ghealth_tool check -i data.csv --chip my_chip
```
