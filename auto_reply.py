# python3
# -*- coding: utf-8 -*-
# @File    : auto_reply.py
import time as time_module

from nonebot import on_command, on_message, logger
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from .admin_role import DEPUTY_AUTO_REPLY
from .path import auto_reply_path
from .utils import json_load, json_upload, fi

# ==================== 预设回复 ====================

SAVE_REPLY = (
    "【存档相关问题解答】\n"
    "\n"
    "星际2的存档保存在本地电脑，重装系统、换电脑、网吧玩等都可能导致存档丢失。\n"
    "\n"
    "【如何找回/备份存档】\n"
    "1. 存档位置：文档\\StarCraft II\\Accounts\\你的账号ID\\...\\Banks 文件夹\n"
    "2. 将 Banks 文件夹备份到手机、网盘或U盘\n"
    "3. 推荐使用云存档功能，可自动备份和恢复\n"
    "4. 建议电脑至少16G内存、C盘留20G以上空间，避免存档损坏\n"
    "\n"
    "详细教程：https://zergsea.com/archives/46\n"
    "亚服转国服：https://zergsea.com/archives/909"
)

REPORT_REPLY = (
    "【举报流程】\n"
    "\n"
    "1. 在群文件「审判庭」文件夹中上传录像文件(.SC2Replay)\n"
    "2. 如有录屏片段，鼠标需放在违规玩家的单位上，展示控制者光圈\n"
    "3. 恶劣行为出现两次将进入虫海联Ban系统\n"
    "\n"
    "当前受理范围：A桥、影响全局的恶劣行为\n"
    "仅攻击队友建筑暂不在受理范围内\n"
    "\n"
    "注意：请提供完整证据（录像文件 + 录屏片段），仅截图不予受理。\n"
    "\n"
    "详情参考：https://zergsea.com/archives/100"
)

PRESET_REPLIES = [
    (['存档丢了', '战绩不见了', '存档找回', '备份存档', '存档没了',
      '怎么备份', '存档恢复', '存档丢失', '数据丢了'], SAVE_REPLY),
    (['怎么举报', '我要举报', '举报玩家', 'A桥'], REPORT_REPLY),
]

# ==================== 冷却机制 ====================

_cooldown: dict[tuple, float] = {}
COOLDOWN_SEC = 60


def _on_cooldown(gid: str, key: str) -> bool:
    return (time_module.time() - _cooldown.get((gid, key), 0)) < COOLDOWN_SEC


def _set_cooldown(gid: str, key: str):
    _cooldown[(gid, key)] = time_module.time()
    if len(_cooldown) > 10000:
        now = time_module.time()
        expired = [k for k, v in _cooldown.items() if now - v > 120]
        for k in expired:
            del _cooldown[k]

# ==================== CRUD 函数（供 private_cmd 导入） ====================


def load_custom_replies(gid: str) -> dict:
    data = json_load(auto_reply_path) or {}
    result = dict(data.get('global', {}))
    result.update(data.get(gid, {}))
    return result


def add_custom_reply(scope: str, keyword: str, reply: str) -> bool:
    data = json_load(auto_reply_path) or {}
    if scope not in data:
        data[scope] = {}
    if keyword in data[scope]:
        return False
    data[scope][keyword] = reply
    json_upload(auto_reply_path, data)
    return True


def del_custom_reply(scope: str, keyword: str) -> bool:
    data = json_load(auto_reply_path) or {}
    if scope in data and keyword in data[scope]:
        del data[scope][keyword]
        if scope != 'global' and not data[scope]:
            del data[scope]
        json_upload(auto_reply_path, data)
        return True
    return False


def list_all_replies(gid: str) -> list[str]:
    lines = ['[预设关键词]']
    for keywords, _ in PRESET_REPLIES:
        lines.append('  ' + '、'.join(keywords))
    data = json_load(auto_reply_path) or {}
    g_replies = data.get('global', {})
    if g_replies:
        lines.append('[全局自定义]')
        for kw, rp in g_replies.items():
            lines.append(f'  {kw} → {rp[:30]}{"..." if len(rp) > 30 else ""}')
    local = data.get(gid, {})
    if local:
        lines.append('[本群自定义]')
        for kw, rp in local.items():
            lines.append(f'  {kw} → {rp[:30]}{"..." if len(rp) > 30 else ""}')
    if not g_replies and not local:
        lines.append('[暂无自定义关键词]')
    return lines

# ==================== 消息监听 ====================

auto_reply_listener = on_message(priority=4, block=False)


@auto_reply_listener.handle()
async def _(bot: Bot, event: GroupMessageEvent):
    msg = event.get_plaintext()
    if not msg or len(msg) < 2:
        return

    gid = str(event.group_id)

    for keywords, reply in PRESET_REPLIES:
        for kw in keywords:
            if kw in msg:
                if _on_cooldown(gid, kw):
                    return
                _set_cooldown(gid, kw)
                await bot.send(event=event, message=reply)
                return

    custom = load_custom_replies(gid)
    for kw, reply in custom.items():
        if kw in msg:
            if _on_cooldown(gid, kw):
                return
            _set_cooldown(gid, kw)
            await bot.send(event=event, message=reply)
            return

# ==================== 管理指令（群内） ====================

_perm = SUPERUSER | GROUP_ADMIN | GROUP_OWNER | DEPUTY_AUTO_REPLY

auto_reply_add = on_command('自动回复+', priority=2,
                            aliases={'自动回复加', '添加自动回复'}, block=True, permission=_perm)


@auto_reply_add.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    text = str(args).strip()
    if '||' not in text:
        await matcher.finish('格式：/自动回复+ 关键词||回复内容')
    keyword, reply = text.split('||', 1)
    keyword, reply = keyword.strip(), reply.strip()
    if not keyword or not reply:
        await matcher.finish('关键词和回复内容不能为空')
    if add_custom_reply(str(event.group_id), keyword, reply):
        await fi(matcher, f'已添加自动回复：{keyword}')
    else:
        await fi(matcher, f'关键词「{keyword}」已存在')


auto_reply_del = on_command('自动回复-', priority=2,
                            aliases={'自动回复减', '删除自动回复'}, block=True, permission=_perm)


@auto_reply_del.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    keyword = str(args).strip()
    if not keyword:
        await matcher.finish('格式：/自动回复- 关键词')
    if del_custom_reply(str(event.group_id), keyword):
        await fi(matcher, f'已删除自动回复：{keyword}')
    else:
        await fi(matcher, f'未找到关键词「{keyword}」')


auto_reply_list = on_command('自动回复列表', priority=2,
                             aliases={'查看自动回复'}, block=True, permission=_perm)


@auto_reply_list.handle()
async def _(matcher: Matcher, event: GroupMessageEvent):
    lines = list_all_replies(str(event.group_id))
    await fi(matcher, '\n'.join(lines))


# 全局回复（仅超管）
global_reply_add = on_command('全局回复+', priority=2,
                              aliases={'全局回复加'}, block=True, permission=SUPERUSER)


@global_reply_add.handle()
async def _(matcher: Matcher, args: Message = CommandArg()):
    text = str(args).strip()
    if '||' not in text:
        await matcher.finish('格式：/全局回复+ 关键词||回复内容')
    keyword, reply = text.split('||', 1)
    keyword, reply = keyword.strip(), reply.strip()
    if not keyword or not reply:
        await matcher.finish('关键词和回复内容不能为空')
    if add_custom_reply('global', keyword, reply):
        await fi(matcher, f'已添加全局回复：{keyword}')
    else:
        await fi(matcher, f'全局关键词「{keyword}」已存在')


global_reply_del = on_command('全局回复-', priority=2,
                              aliases={'全局回复减'}, block=True, permission=SUPERUSER)


@global_reply_del.handle()
async def _(matcher: Matcher, args: Message = CommandArg()):
    keyword = str(args).strip()
    if not keyword:
        await matcher.finish('格式：/全局回复- 关键词')
    if del_custom_reply('global', keyword):
        await fi(matcher, f'已删除全局回复：{keyword}')
    else:
        await fi(matcher, f'未找到全局关键词「{keyword}」')
