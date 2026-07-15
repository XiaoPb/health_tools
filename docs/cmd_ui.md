# ui 命令

启动 GHealth Tools 的 Streamlit 图形界面。UI 复用 CLI 的解析、转换、分类、检查、绘图、
评估和规则能力，适合交互式选择文件与查看结果。

## 安装

UI 是可选依赖：

```bash
pip install "ghealth-tools[ui]"
```

源码开发环境使用：

```bash
pip install -e ".[ui,dev]"
```

## 用法

```bash
ghealth_tool ui [options]
```

## 参数

| 参数 | 说明 |
|---|---|
| `--port` | Streamlit 服务端口，默认 8501 |

## 输出

命令启动本地 Streamlit 服务并在终端显示访问地址。页面包含信息查看、解析、绘图、分类、
转换、分割、评估、产测和芯片规则编辑等功能；可用页面以当前安装版本为准。

## 失败条件

- 未安装 `streamlit` 时，命令提示安装 `ghealth-tools[ui]`。
- 端口被占用时，选择其他端口，例如 `--port 8502`。
- 页面执行任务时仍遵循对应 CLI 的规则格式、输入结构和输出约定。

## 示例

```bash
# 使用默认端口
ghealth_tool ui

# 指定端口
ghealth_tool ui --port 8502
```

命令行任务索引见 [命令索引](commands.md)，规则格式见 [规则文件格式](rules.md)。
