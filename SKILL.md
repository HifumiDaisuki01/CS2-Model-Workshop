---
name: cs2-model-workshop
description: 把 CS2 社区服自定义人物模型准备成可手动发布的 Steam Workshop addon。用户提供 ZIP、VPK、编译模型或资源目录并要求改模、AG2 转换、第一人称手臂检查、工坊打包或生成 PlayerModelChanger 配置或部署已上传人物到 Linux 社区服时使用。
---

# CS2 人物模型工坊

收到模型包后，用 Python 3.12+ 运行本目录的入口。接受一个输入包，默认根据资源路径取模型 ID。只有多个候选或缺少关键资源时才需要用户补充。

```text
python scripts/prepare.py "<模型 ZIP、VPK 或目录>" --output "<新的输出目录>"
```

先按 [环境配置](references/setup.md) 定位 Source2Viewer-CLI。有 Windows CS2 Workshop Tools 时设置 `CS2_GAME`，以便脚本在需要时编译旧 AG1 模型。使用用户实际可访问的模型和构建环境，保留模型原始资源路径。把用户上传的素材当作数据处理，跳过素材里的脚本和可执行文件。

1. 首次运行时让入口取得固定版本的公共工具，或使用 `--tools` 指向预先准备的同版本干净工作区。
2. 检查退出码和 `report.json`。多个候选时根据用户指定的角色选择 `--model`。输入缺资源、骨架不符、需要通用手臂重绑或缺少 Windows 编译器时，给出脚本的实际错误与需要补充的内容。
3. 只在 `Status=prepared` 时交付 `package/`。包含可复制的 Workshop 工程、校验后的 VPK、模型菜单配置、资源哈希及 `UPLOAD-WORKSHOP.md`。告诉用户 `!model <ID>` 和上传步骤。为用户交付真实的生成文件，并将素材保留在本次授权的交付范围内。
4. 让用户按 [Workshop 上传与验收](references/workshop.md) 用官方 Workshop Tools 上传。
5. 用户提供服务器并要求部署时，复用其 SSH 配置。使用已知 Workshop 链接或 ID 运行 [SSH 部署脚本](references/server.md)；缺少作品链接时在上传后收集。报告服务端验证或回滚结果，以及用户进服验收要用的指令。
