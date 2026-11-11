# CS2 Model Workshop

一个用于准备 CS2 社区服人物模型的 Codex Skill。平时只交一个模型包，生成官方 Workshop Tools 可用的 addon、校验后的备用 VPK 和 PlayerModelChanger 菜单配置。你负责在 Steam 工坊上传并进游戏验收。上传后可以提供服务器与作品链接，由 Skill 通过 SSH 下载、挂载并配置换模。

## 开始使用

把本仓库作为一个 Skill 文件夹放进 Codex 的 `.agents/skills/cs2-model-workshop/`，然后提交人物模型包，说「用 `$cs2-model-workshop` 把这个人物打包成 CS2 Workshop 工程」。也可以直接运行：

```bash
python scripts/prepare.py character.zip --output character-workshop
```

先准备 Python 3.12+、Git、Source2Viewer-CLI。完整依赖、Windows 编译配置和多模型选择见 [环境配置](references/setup.md)。

| 输入 | 处理 |
| --- | --- |
| 完整的 CS2 AG2 资源目录、ZIP 或 VPK | 识别人物，检查依赖闭包、骨架、LOD0、内嵌手臂权重和 VPK 完整性 |
| 内嵌手臂完整、仅缺一个受支持的旧外部引用 | 调用固定版本的结构化修复器，再对照修复前后的蒙皮 GLB |
| 符合现有 Porter 条件的 AG1 人物 | 用 Windows Workshop Tools 编译后重新校验，原版手臂预期会记录在报告 |
| 缺依赖、未知骨架、通用 FBX/PMX 或需要重绑手臂 | 输出具体阻塞原因。需要先准备可用的 CS2 人物资源 |

成功时打开 `<输出>/package/UPLOAD-WORKSHOP.md`。它带有本次 addon 名和 `!model` 指令。若处理失败，查看 `report.json` 和 `logs/`。静态检查、Windows 编译、工坊上传和客户端验收是独立状态。

## 阿洛娜练习包

仓库包含已编译的 [阿洛娜示例 ZIP](examples/aluona/aluona-workshop-example.zip)，可直接练习上传，也可作为 Skill 输入练习打包。[示例用法与来源](examples/aluona/README.md)

## 部署到服务器

```bash
python3 scripts/deploy.py ./character-workshop/package '<Workshop 作品链接>' --server user@host
```

支持已有 MAM 和兼容 PlayerModelChanger 的 Linux systemd 服。脚本校验实际下载的模型资源，备份后追加配置，重启并通过 RCON 验证。遇到失败自动恢复配置。完整条件和参数见 [SSH 部署](references/server.md)。

仓库提供 Skill、脚本、说明及阿洛娜单人物示例。旧转换与校验工具通过固定提交复用，见 [CS2-MODEL-CHANGER](https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER/tree/000c0f492761e0b396fa0eb264f0e679a23a18a7)。项目不附带 Valve 运行库或 Steam 登录信息。
