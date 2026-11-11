# 环境配置

需要 Python 3.12+、Git 和 [Source2Viewer-CLI](https://s2v.app/)。优先用历史验证版本 VRF 20.1.7467。确保可执行文件在 PATH 中，或把其绝对路径设为 `CS2_VRF`。首次运行会从 GitHub 取得 [CS2-MODEL-CHANGER 的固定提交](https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER/tree/000c0f492761e0b396fa0eb264f0e679a23a18a7) 中的脚本和参考数据。项目无需 Steam 凭据。

- **AG2 直打包**可在 Linux 或 Windows 执行。设置 `CS2_GAME` 或 `--base-vpk <CS2 原版 pak01_dir.vpk>` 可用本机游戏 VPK 的目录判断原版依赖。否则会使用历史已确认的原版资源清单，并在报告注明依据。
- **旧外部引用修复**需要 .NET 10 SDK 和用于还原 ValveResourceFormat 的 NuGet 访问。修复适用前提是已经有完整 AG2 和内嵌第一人称网格，且只缺一个符合现有结构化修复条件的直接引用。旧动画包含项的修复仅适用于已审计的 10052 原始版本。几何和蒙皮导出不一致时会停止。
- **旧 AG1 编译**需要 Windows，安装 CS2 Workshop Tools 并设置 `CS2_GAME` 为游戏安装根目录。若提示 Porter Python 依赖缺失，在当前 Python 环境安装工具缓存中 `server/ag2-port/tools/requirements.txt` 的依赖。编译写入独立临时 addon，保存日志后清理该临时目录。
- **第一人称重绑**需要可用的手臂几何和对应骨骼映射。Lime E 有可复用工程与 [真实绑定矩阵迁移记录](https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER/blob/000c0f492761e0b396fa0eb264f0e679a23a18a7/server/lime-e-windows/EXPERIENCE_LIME_E_CN.md)。本入口接受其已编译成品，通用自动重绑留给后续版本。

Windows PowerShell 示例

```powershell
$env:CS2_VRF = 'D:\Tools\Source2Viewer-CLI.exe'
$env:CS2_GAME = 'D:\SteamLibrary\steamapps\common\Counter-Strike Global Offensive'
py -3 scripts/prepare.py 'D:\models\character.zip'
```

Linux 示例

```bash
export CS2_VRF="$PWD/tools/Source2Viewer-CLI"
python3 scripts/prepare.py ./character.zip
```

多人物包用 `--model characters/.../name.vmdl` 指定一人。`--id` 和 `--name` 分别覆盖指令 ID 和菜单显示名。分卷 VPK 选择 `*_dir.vpk` 并将所有分卷放在同目录。单独的 `.vmdl_c` 需要保留 `characters/` 路径，并让依赖处于同一个资源根目录内。
