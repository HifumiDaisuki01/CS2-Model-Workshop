# SSH 部署到 CS2 社区服

上传完成后，提供 **SSH 地址或已配好的 SSH 别名**，以及 **Workshop 作品链接**。第一次需要已经配置好的 SSH 密钥或 agent、可连接的 Linux CS2 服和能重启对应 systemd 服务的账号。部署端和服务端需要 Python 3.11+，部署端需要 OpenSSH。Skill 通过 SSH 检查现有环境并部署，随后由你用普通客户端验收。

```bash
python3 scripts/deploy.py ./character-workshop/package '<Workshop 作品链接>' --server user@server
```

有多个 CS2 实例、非默认端口或自定义缓存时，可指定实际参数。

```bash
python3 scripts/deploy.py ./character-workshop/package '<Workshop 作品链接>' \
  --server cs2-prod --ssh-port 2202 \
  --csgo /srv/cs2/game/csgo --service cs2.service \
  --rcon-port 27015 --rcon-password-file /srv/cs2/secrets/rcon-password
```

## 服务器条件

- 已有兼容的 Metamod、MultiAddonManager、CounterStrikeSharp 和 [支持 `pmc_status` 的 PlayerModelChanger fork](https://github.com/HifumiDaisuki01/CS2-MODEL-CHANGER/blob/main/server/README.md)。
- 本机回环 RCON 可访问。默认从服务器的 `cfg/server.cfg` 读取唯一带引号的 `rcon_password`。密码由额外配置提供时，用 `--rcon-password-file` 指向服务器上已有的单行密码文件。密码留在服务器。
- SSH 账号可写入相关配置，并能直接或用免交互 `sudo` 重启该 systemd 服务。部署成功要重启一次，在线玩家会断开，地图按该服务的原有启动配置加载。
- Workshop 作品应能被目标服务器和客户端访问。脚本把该角色作为**独立作品**追加。更新已挂载的旧作品或覆盖同路径人物，应先处理旧版资源和回滚。

## 部署过程

1. 识别正在运行的 CS2 实例、配置、MAM 和 PlayerModelChanger。
2. 用 MAM 下载作品，等资源实际到达服务端。根据准备阶段的清单核对 VPK 条目内容及 CRC，计算服务端实际归档 SHA256。缓存路径特殊时可用 `--vpk` 指定服务器上的 MAM VPK。
3. 备份 MAM、PlayerModelChanger 配置和资源目录 JSON。追加挂载与模型菜单，保留已有配置条目、玩家 SQLite 和其他插件。
4. 重启服务，检查 RCON 搜索路径、模型数和 `pmc_status`。失败时恢复已写入的配置并检查原状态。终端打印的远端快照位置可以用于人工恢复。
5. 进服执行对应 `!model <ID>` 并按 [上传与验收清单](workshop.md) 测试。

快照位于服务器 `game/csgo/.cs2-model-workshop/`，其中 `snapshot.json` 对应三个配置路径。需要人工恢复时，使用快照中的 `0`、`1`、`2` 恢复对应文件，对快照中记为缺失的文件恢复缺失状态，再重启原服务。快照包含服务器配置，请保留在服务器私有目录。
