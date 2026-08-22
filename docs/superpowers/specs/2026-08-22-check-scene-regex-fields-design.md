# check 场景正则字段设计

## 目标

`check` 命令的 `scene_regex` 除了识别 `scene` 外，支持可选命名组 `name` 和 `hand`，并在报告的场景分类之后输出姓名和手别。

## 设计

- 正则由现有 `_compile_scene_regex` 编译，`scene` 仍为必需命名组。
- `_scene_for_path` 扩展为返回 `(scene, name, hand)`；未匹配或缺少可选组时填充 `default`。
- `FileCheckReport` 保存三个字段，报告 CSV 在 `场景分类` 后依次写入 `姓名`、`手别`、`文件相对路径`。
- 现有仅包含 `scene` 的规则保持兼容。

## 验证

测试 Linux/Windows 分隔符、匹配失败、旧规则兼容，以及报告列顺序和字段值。
