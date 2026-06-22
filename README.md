# nonebot_plugin_admin AstrBot 版

这是将原 `nonebot_plugin_admin` 迁移到 AstrBot 的兼容版插件。插件主体逻辑仍复用原 NoneBot 插件代码，新增了 AstrBot 入口和一层本地 NoneBot 兼容层，因此原来的 `config.py` / `Config` 配置字段仍然可以继续使用。

## 功能概览

- 群管：禁言、解禁、全员禁言、踢人、拉黑、改群名片、设置管理员、撤回消息、精华消息、头衔管理。
- 入群审批：审批词条、拒绝词条、分管管理员、审批结果通知。
- 功能开关：按群开启或关闭不同模块。
- 私聊管理：绑定群后在私聊里执行部分群管操作。
- 自动回复：本群关键词回复和全局关键词回复。
- 违禁词检测：自动撤回、禁言，可按规则配置。
- 图片检测：接入腾讯云图片安全能力。
- 词云与发言统计：记录群消息、生成词云、查看发言排行。
- 广播、跨群发送、事件通知、防撤回、群成员清理、群文件清理等。

## 运行要求

- AstrBot。
- QQ 平台需要使用 OneBot / aiocqhttp 适配器。
- 机器人账号需要在目标群里拥有足够权限，否则禁言、踢人、撤回、管理员设置等操作会失败。

可选依赖按功能安装：

```bash
pip install wordcloud jieba pillow
pip install tencentcloud-sdk-python
pip install jinja2 pyppeteer
```

说明：

- 默认会在插件启动时自动检查并安装缺少的 pip 依赖。
- 自动安装会先使用腾讯云 PyPI 镜像：`https://mirrors.cloud.tencent.com/pypi/simple`。
- 腾讯云镜像安装失败时，会自动切换清华大学 PyPI 镜像：`https://pypi.tuna.tsinghua.edu.cn/simple`。
- 如果你的运行环境禁止联网或禁止插件调用 pip，可以在插件配置里关闭 `auto_install_deps`，再手动安装依赖。
- 基础群管命令不一定需要上述可选依赖。
- 词云功能需要 `wordcloud` 等依赖。
- 腾讯云图片检测需要 `tencentcloud-sdk-python`，并配置 `tenid` / `tenkeys`。
- 开关状态截图需要 `jinja2` / `pyppeteer`；缺少时会尽量退回文本发送。

## 安装方式

### 方式一：上传 zip

推荐压缩后的结构如下：

```text
nonebot_plugin_admin.zip
└─ nonebot_plugin_admin/
   ├─ main.py
   ├─ metadata.yaml
   ├─ _conf_schema.json
   ├─ config.py
   ├─ admin.py
   ├─ nonebot/
   └─ ...
```

在插件目录的上一级执行：

```powershell
Compress-Archive -Path .\nonebot_plugin_admin -DestinationPath .\nonebot_plugin_admin.zip -Force
```

然后在 AstrBot WebUI 的插件管理页上传 zip 并重启 / 重载插件。

如果上传后提示找不到 `main.py`，说明 AstrBot 当前安装方式要求 zip 根目录直接包含插件文件。此时进入插件目录内部执行：

```powershell
Compress-Archive -Path .\* -DestinationPath ..\nonebot_plugin_admin.zip -Force
```

这种 zip 解开后根目录会直接看到：

```text
main.py
metadata.yaml
_conf_schema.json
config.py
admin.py
nonebot/
...
```

### 方式二：手动放入插件目录

将整个文件夹放到 AstrBot 插件目录，例如：

```text
AstrBot/data/plugins/nonebot_plugin_admin/
```

确保该目录下直接存在：

```text
main.py
metadata.yaml
_conf_schema.json
```

然后重启 AstrBot 或在 WebUI 中重载插件。

## 配置项

插件使用 AstrBot 的 `_conf_schema.json` 生成配置界面，并把配置传回原插件的 `Config` 兼容层。

| 配置项 | 类型 | 说明 |
| --- | --- | --- |
| `auto_install_deps` | bool | 是否在插件启动时自动安装缺少的 pip 依赖。默认开启。 |
| `superusers` | list | 超级用户 QQ 号列表，例如 `["123456789"]`。 |
| `tenid` | string | 腾讯云图片安全 SecretId，对应原 `Config.tenid`。 |
| `tenkeys` | string | 腾讯云图片安全 SecretKey，对应原 `Config.tenkeys`。 |
| `img_check_rules_json` | string | 图片检测处置规则 JSON，可自定义标签、分值、撤回和禁言。 |
| `callback_notice` | bool | 操作完成后是否发送提示。 |
| `ban_rand_time_min` | int | 随机禁言最短时间，单位秒。 |
| `ban_rand_time_max` | int | 随机禁言最长时间，单位秒。 |
| `host` | string | 兼容旧代码读取 `get_driver().config.host`，通常不用改。 |
| `port` | int | 兼容旧代码读取 `get_driver().config.port`，通常不用改。 |
| `send_group_id` | list | 早晚安定时推送目标群。 |
| `send_switch_morning` | bool | 是否开启早安推送。 |
| `send_switch_night` | bool | 是否开启晚安推送。 |
| `send_mode` | int | 定时推送模式，`1` 为自定义句子，`2` 为一言接口。 |
| `send_sentence_morning` | list | 早安自定义句子。 |
| `send_sentence_night` | list | 晚安自定义句子。 |
| `send_time_morning` | string | 早安推送时间，例如 `"7 0"`。 |
| `send_time_night` | string | 晚安推送时间，例如 `"22 0"`。 |

## 常用命令

群消息命令统一使用 `/` 前缀，例如 `/帮助`、`/禁 @某人 60`。下方旧命令示例如果没有写 `/`，实际在群里使用时也请加上 `/`。

### 帮助

```text
/帮助
/帮助 群管
/help
```

### 基础群管

```text
禁 @某人 [秒数]
解 @某人
/all
/all 解
改 @某人 新名片
踢 @某人
黑 @某人
管理员+ @某人
管理员- @某人
头衔 头衔内容
删头衔
撤回
撤回 @某人 [检查倍数]
加精
取消精华
```

### 入群审批与分管

```text
查看词条
词条+ 审批词条
词条- 审批词条
拒绝词条+ 拒绝词条
拒绝词条- 拒绝词条
分管
分管+ @某人
分管- @某人
所有分管
接收
分管权限
分管权限 禁言 开
分管权限 踢人 关
```

### 功能开关

```text
开关 功能名
开关状态
```

常见功能名包括：

```text
基础群管
加群审批
词云
违禁词检测
图片检测
消息记录
广播
事件通知
防撤回
自动清理
自动回复
清理群文件
```

### 私聊管理

先私聊机器人绑定要管理的群：

```text
绑群 群号
查看绑群
解绑
```

绑定后可在私聊中使用部分群管命令，例如：

```text
禁 QQ号 [秒数]
解 QQ号
踢 QQ号
黑 QQ号
改 QQ号 新名片
管理员+ QQ号
管理员- QQ号
开关 功能名
自动回复+ 关键词||回复内容
自动回复- 关键词
自动清理 N
```

超级用户可使用：

```text
绑群 all
```

### 自动回复

```text
自动回复+ 关键词||回复内容
自动回复- 关键词
自动回复列表
全局回复+ 关键词||回复内容
全局回复- 关键词
```

### 违禁词与图片检测

```text
添加违禁词 词条
删除违禁词 词条
查看违禁词
开关 违禁词检测
开关 图片检测
```

违禁词配置文件会保存在插件运行目录下的 `config/` 中。支持原插件的规则格式。

图片检测规则在插件配置项 `img_check_rules_json` 中设置，格式是 JSON 数组。默认规则如下：

```json
[
  {"name":"色情","label":"Porn","score":90,"recall":true,"mute":true,"mute_seconds":0},
  {"name":"涉政","label":"Politics","score":90,"recall":true,"mute":true,"mute_seconds":0},
  {"name":"性感","label":"Sexy","score":90,"recall":true,"mute":true,"mute_seconds":0,"enabled":false}
]
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `name` | 规则名称，只用于日志显示。 |
| `scene` | 匹配腾讯云返回的 `Scene`，可选。 |
| `label` | 匹配腾讯云返回的 `Label`，可选。 |
| `sub_label` | 匹配腾讯云返回的 `SubLabel`，可选。 |
| `score` | 分值阈值，大于等于该值才触发。 |
| `recall` | 是否撤回消息。 |
| `mute` | 是否禁言。 |
| `mute_seconds` | 禁言秒数；填 `0` 表示使用插件原来的违规等级自动时长。 |
| `enabled` | 是否启用规则；不写时默认启用。 |

例如：Sexy 分值达到 90 就撤回并禁言，把默认配置里的 Sexy 规则改成：

```json
{"name":"性感","label":"Sexy","score":90,"recall":true,"mute":true,"mute_seconds":0,"enabled":true}
```

例如：只撤回不禁言：

```json
{"name":"性感仅撤回","label":"Sexy","score":90,"recall":true,"mute":false,"enabled":true}
```

例如：只针对 `WomenSexyChest` 子标签，分值 95 以上禁言 10 分钟：

```json
{"name":"性感胸部","sub_label":"WomenSexyChest","score":95,"recall":true,"mute":true,"mute_seconds":600,"enabled":true}
```

图片检测缓存保存在 `config/img_check_cache.json`，缓存只保留 30 天。插件加载缓存、命中缓存或写入新缓存时会自动清理超过 30 天的记录，避免缓存文件长期增大影响速度。

### 词云与发言统计

```text
记录本群
停止记录本群
群词云
更新mask
添加停用词 词语
删除停用词 词语
停用词列表
今日榜首
今日发言排行
昨日发言排行
排行
发言数 @某人
今日发言数 @某人
```

### 广播与跨群

```text
广播 消息内容
群列表
广播排除+ 群号
广播排除- 群号
排除列表
跨群发送 目标群号或群别名 文本内容
```

### 清理

```text
自动清理 N
确认
确认清理 2
确认清理 2-10
成员清理
清理解锁
/清理群文件 >10
/清理群文件 .zip >5
/清理群文件 >10 时间正序
/清理群文件 .zip 时间倒序
```

`/清理群文件` 默认按文件大小从大到小预览和清理。追加 `时间正序` 会按上传时间从旧到新处理，追加 `时间倒序` 会按上传时间从新到旧处理；群主、群管理员、超级用户可使用。

## 数据文件

插件运行时会自动创建 `config/`、`resource/` 等目录，用于保存：

- 各群功能开关。
- 审批词条。
- 分管管理员配置。
- 自动回复配置。
- 违禁词配置。
- 词云和发言统计数据。
- 清理锁文件。

迁移旧数据时，可以把原 NoneBot 插件运行目录中的 `config/` 和 `resource/` 复制到这个 AstrBot 插件目录下。

## 兼容说明

本版本不是把每个模块完全重写成 AstrBot 原生插件，而是：

1. `main.py` 接收 AstrBot 消息事件。
2. 本地 `nonebot/` 兼容层模拟原 NoneBot 的命令、权限、事件和 Bot API。
3. 原业务模块继续使用 `on_command`、`Matcher`、`Config`、`Bot.call_api` 等旧接口。

这样做的好处是迁移范围小，原来的配置和业务逻辑保留得更多；代价是部分边缘事件依赖 AstrBot 的 OneBot 适配器是否暴露原始事件。

## 已知限制

- 群消息命令已经通过兼容层接入。
- 入群申请、群通知、防撤回等非消息事件能否触发，取决于 AstrBot 当前 OneBot 适配器是否把 request / notice 原始事件交给插件层。
- 早晚安定时推送原本依赖 NoneBot APScheduler，当前 AstrBot 版保留配置和函数，但定时能力需要 AstrBot 环境提供调度支持后再接入。
- 如果某个功能提示缺少依赖，按报错安装对应 Python 包后重启 AstrBot。

## 快速排查

1. 插件不显示：检查插件目录下是否直接有 `main.py`、`metadata.yaml`、`_conf_schema.json`。
2. 命令无响应：先测试 `/help`；再检查是否启用了 QQ / OneBot 平台。
3. 群管操作失败：检查机器人是否是群管理员，且操作对象权限低于机器人。
4. 超级用户无权限：检查 `superusers` 是否填写为字符串列表，例如 `["123456789"]`。
5. 图片检测无效：检查 `tenid`、`tenkeys` 和 `tencentcloud-sdk-python`。
6. 词云无效：检查是否安装 `wordcloud`，并先执行 `记录本群`。

## 旧配置和记录文件迁移

这里分两类，不要混在一起：

1. `Config` 配置项：也就是 `superusers`、`tenid`、`tenkeys`、`callback_notice`、`ban_rand_time_min`、`ban_rand_time_max` 等。这些不要复制旧 `.env` 文件，直接在 AstrBot 插件配置页面里填写。
2. 插件运行记录文件：也就是原插件运行时生成的 `config/`、`resource/` 目录。这些可以直接复制到本 AstrBot 插件目录下。

迁移后的推荐结构：

```text
AstrBot/data/plugins/nonebot_plugin_admin/
  main.py
  metadata.yaml
  _conf_schema.json
  config/
    admin.json
    group_admin.json
    开关.json
    自动回复.json
    分管权限.json
    群消息数据/
    群内用户违规信息/
    words/
    ...
  resource/
    imgs/
    msyhblod.ttf
    ...
```

旧文件从哪里找：

```text
旧 NoneBot 项目根目录/config/
旧 NoneBot 项目根目录/resource/
```

复制到哪里：

```text
AstrBot/data/plugins/nonebot_plugin_admin/config/
AstrBot/data/plugins/nonebot_plugin_admin/resource/
```

如果你原来只想迁移部分数据，可以按需复制：

| 旧数据 | 复制的文件或目录 |
| --- | --- |
| 入群审批词条 | `config/admin.json` |
| 分管管理员 | `config/group_admin.json` |
| 功能开关 | `config/开关.json` |
| 自动回复 | `config/自动回复.json` |
| 分管权限 | `config/分管权限.json` |
| 违禁词 | `config/违禁词.txt` |
| 词云和发言统计 | `config/群消息数据/`、`config/words/`、`config/stop_words/`、`config/wordcloud_bg/` |
| 用户违规记录 | `config/群内用户违规信息/` |
| 广播排除列表 | `config/广播排除群聊.json` |
| 私聊绑群记录 | `config/pm_bindings.json` |
| 群别名 | `config/群别名.json` |
| 字体和图片资源 | `resource/` |

迁移后重启 AstrBot。如果插件已经先启动过并自动生成了新的空 `config/`，可以停掉 AstrBot 后用旧文件覆盖同名文件，再启动。
