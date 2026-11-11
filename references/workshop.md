# 上传 CS2 Workshop 并进服验收

## 上传

1. 用你的 Steam 账号打开安装了 **Counter-Strike 2 Workshop Tools** 的 Windows 电脑。
2. 从交付的 `package/addon/` 复制两个工程目录，保持相对路径和文件名。

   | 交付目录 | 复制到 CS2 安装根目录下 |
   | --- | --- |
   | `addon/content/csgo_addons/{{ADDON}}` | `content/csgo_addons/{{ADDON}}` |
   | `addon/game/csgo_addons/{{ADDON}}` | `game/csgo_addons/{{ADDON}}` |

   如果电脑上已有同名 addon，先将旧目录移到备份位置，再复制整目录。
3. 从 Steam 启动 CS2 Workshop Tools，选择 `{{ADDON}}`，用官方 **Workshop Manager** 的 addon 发布流程创建作品，填写标题、描述、预览图和所需可见性，然后上传。确认你有权在该可见性下分发素材。此工程是社区服人物资源包，沿用模型 addon 发布流程。上传时使用上表的工程目录。`workshop-vpk/` 是独立校验及备用包。
4. 打开 Steam 作品页，记录 URL 中 `id=` 后的数字。用于服务端和普通客户端分发时，确认它们可以访问该作品。

[项目中已使用的官方上传流程](https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER/blob/000c0f492761e0b396fa0eb264f0e679a23a18a7/server/workshop/fifteen-models/README.md)

## 社区服

把作品链接和 SSH 服务器信息交给 Skill，即可按 [SSH 部署](https://github.com/HifumiDaisuki01/CS2-Model-Workshop/blob/main/references/server.md) 自动执行下载、挂载、配置和服务端验证。以下步骤也可手动执行。

1. 先在测试服把作品 ID 合并进 MultiAddonManager 的 `mm_extra_addons`。服务器继续使用原地图。检查当前挂载的 addon 是否占用相同资源路径，尤其是更新同一角色时。
2. 等待 Workshop 实际下载完成。使用上游 `verify_vpk.py` 对实际下载的 VPK 目录和分卷做 CRC 校验，并与 `resources.sha256.json` 核对模型、材质和贴图条目。Workshop Tools 可能重新封装，服务端的 catalog 应以实际下载归档的路径和 SHA256 生成。
3. 按 [服务端配置及校验流程](https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER/blob/000c0f492761e0b396fa0eb264f0e679a23a18a7/server/README.md) 用 `stage_model.py` 准备 MAM、PlayerModelChanger 配置和 `resource-catalog.json`。`PlayerModelChanger.merge.json` 是本角色的配置片段。保留已有设置和玩家选择数据库。
4. 由你用普通客户端连接测试服，确认自动下载，输入 `!model {{ID}}`。分别在 T 和 CT 测试持刀、持枪、开火、换弹、蹲跳、重生与重连。请另一位玩家检查第三人称显示，最后用 `!model default` 验证可以恢复原版。
