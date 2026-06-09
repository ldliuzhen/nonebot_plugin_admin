# python3
# -*- coding: utf-8 -*-
# @File    : private_cmd.py
import asyncio
import time as time_module
from datetime import datetime
from random import randint
from typing import Optional

from nonebot import on_command, logger
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, PrivateMessageEvent
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.typing import T_State

from . import approve
from .auto_reply import add_custom_reply, del_custom_reply, list_all_replies
from .cleanup_selection import parse_cleanup_selection
from .config import global_config
from .path import (pm_bindings_path, switcher_path, admin_funcs,
                   kick_lock_path, config_admin)
from .utils import (json_load, json_upload, mute_sb,
                    get_all_deputy_perms, set_deputy_perm, _DEPUTY_OPS)

su = global_config.superusers
NEW_MEMBER_DAYS = 30


def _is_private():
    async def _checker(event: PrivateMessageEvent) -> bool:
        return True
    return Rule(_checker)


_rule = _is_private()


# ==================== 辅助函数 ====================

def _get_binding(uid: str) -> Optional[str]:
    data = json_load(pm_bindings_path) or {}
    return data.get(uid)


def _set_binding(uid: str, gid: str):
    data = json_load(pm_bindings_path) or {}
    data[uid] = gid
    json_upload(pm_bindings_path, data)


def _del_binding(uid: str) -> bool:
    data = json_load(pm_bindings_path) or {}
    if uid in data:
        del data[uid]
        json_upload(pm_bindings_path, data)
        return True
    return False


def _is_su(uid) -> bool:
    return str(uid) in su or uid in su


async def _check_perm(bot: Bot, uid: int, gid: str) -> bool:
    if _is_su(uid):
        return True
    try:
        info = await bot.get_group_member_info(group_id=int(gid), user_id=uid)
        return info.get('role') in ('admin', 'owner')
    except Exception:
        return False


async def _bound_gid(bot: Bot, matcher: Matcher, event: PrivateMessageEvent) -> str:
    """获取已绑定的单个群号，未绑定/all模式/无权限时自动 finish。"""
    uid = str(event.user_id)
    binding = _get_binding(uid)
    if not binding:
        await matcher.finish('请先绑定群：/绑群 群号')
    if binding == 'all':
        await matcher.finish('当前绑定为all模式，此指令需绑定单个群号')
    if not await _check_perm(bot, event.user_id, binding):
        await matcher.finish(f'你不是群{binding}的管理员，无法操作')
    return binding


async def _bound_gid_owner(bot: Bot, matcher: Matcher, event: PrivateMessageEvent) -> str:
    """同 _bound_gid，但要求群主或超级用户。"""
    gid = await _bound_gid(bot, matcher, event)
    if not _is_su(event.user_id):
        try:
            info = await bot.get_group_member_info(group_id=int(gid), user_id=event.user_id)
            if info.get('role') != 'owner':
                await matcher.finish('此操作仅限群主或超级用户')
        except Exception:
            await matcher.finish('权限验证失败')
    return gid


# ==================== 绑群管理 ====================
# NOTE: 绑群系列命令必须在「解」命令之前定义，确保「解绑」优先于「解」匹配

pm_bind = on_command('绑群', priority=1, rule=_rule, block=True)


@pm_bind.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    text = str(args).strip()
    if not text:
        await matcher.finish('格式：/绑群 群号\n超级用户可使用：/绑群 all')
    uid = str(event.user_id)
    if text == 'all':
        if not _is_su(event.user_id):
            await matcher.finish('绑定all模式仅限超级用户')
        _set_binding(uid, 'all')
        await matcher.finish('已绑定全部群（开关指令将批量操作）')
    if not text.isdigit():
        await matcher.finish('群号必须为数字')
    try:
        await bot.get_group_info(group_id=int(text))
    except ActionFailed:
        await matcher.finish(f'机器人不在群{text}中')
    _set_binding(uid, text)
    await matcher.finish(f'已绑定群{text}')


pm_unbind = on_command('解绑', priority=1, rule=_rule, block=True)


@pm_unbind.handle()
async def _(matcher: Matcher, event: PrivateMessageEvent):
    if _del_binding(str(event.user_id)):
        await matcher.finish('已解除绑定')
    else:
        await matcher.finish('当前未绑定任何群')


pm_show_bind = on_command('查看绑群', priority=1, rule=_rule, block=True)


@pm_show_bind.handle()
async def _(matcher: Matcher, event: PrivateMessageEvent):
    binding = _get_binding(str(event.user_id))
    if binding:
        await matcher.finish(f'当前绑定：{"全部群" if binding == "all" else "群" + binding}')
    else:
        await matcher.finish('当前未绑定任何群')


# ==================== 禁言 / 解禁 ====================

pm_ban = on_command('禁', priority=1, rule=_rule, block=True)


@pm_ban.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    parts = str(args).strip().split()
    if not parts or not parts[0].isdigit():
        await matcher.finish('格式：/禁 QQ号 [时间(秒)]')
    target = int(parts[0])
    time = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    try:
        async for action in mute_sb(bot, int(gid), lst=[target], time=time):
            if action:
                await action
        await matcher.finish('禁言操作成功' if time is not None else '已禁言随机时长')
    except ActionFailed:
        await matcher.finish('权限不足')


pm_unban = on_command('解', priority=1, rule=_rule, block=True)


@pm_unban.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    text = str(args).strip()
    if not text.isdigit():
        await matcher.finish('格式：/解 QQ号')
    try:
        async for action in mute_sb(bot, int(gid), lst=[int(text)], time=0):
            if action:
                await action
        await matcher.finish('解禁操作成功')
    except ActionFailed:
        await matcher.finish('权限不足')


# ==================== 全员禁言 ====================

pm_ban_all = on_command('/all', priority=1, aliases={'/全员'}, rule=_rule, block=True)


@pm_ban_all.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    text = str(args).strip()
    enable = '解' not in text
    try:
        await bot.set_group_whole_ban(group_id=int(gid), enable=enable)
        await matcher.finish(f'全体{"禁言" if enable else "解禁"}操作成功')
    except ActionFailed:
        await matcher.finish('权限不足')


# ==================== 踢人 / 拉黑 ====================

pm_kick = on_command('踢', priority=1, rule=_rule, block=True)


@pm_kick.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    targets = str(args).strip().split()
    if not targets:
        await matcher.finish('格式：/踢 QQ号 [QQ号2 ...]')
    for qq in targets:
        if not qq.isdigit():
            await matcher.send(f'"{qq}"不是有效QQ号')
            continue
        uid = int(qq)
        if _is_su(uid):
            await matcher.send('超级用户不能被踢')
            continue
        try:
            await bot.set_group_kick(group_id=int(gid), user_id=uid,
                                     reject_add_request=False)
        except ActionFailed:
            await matcher.send(f'踢出{qq}失败，权限不足')
    await matcher.finish('踢人操作执行完毕')


pm_kick_black = on_command('黑', priority=1, rule=_rule, block=True)


@pm_kick_black.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    targets = str(args).strip().split()
    if not targets:
        await matcher.finish('格式：/黑 QQ号 [QQ号2 ...]')
    for qq in targets:
        if not qq.isdigit():
            await matcher.send(f'"{qq}"不是有效QQ号')
            continue
        uid = int(qq)
        if _is_su(uid):
            await matcher.send('超级用户不能被踢')
            continue
        try:
            await bot.set_group_kick(group_id=int(gid), user_id=uid,
                                     reject_add_request=True)
        except ActionFailed:
            await matcher.send(f'踢出{qq}失败，权限不足')
    await matcher.finish('踢出并拉黑操作执行完毕')


# ==================== 改名片 ====================

pm_change = on_command('改', priority=1, rule=_rule, block=True)


@pm_change.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    parts = str(args).strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await matcher.finish('格式：/改 QQ号 新名片')
    target, card = int(parts[0]), parts[1]
    try:
        await bot.set_group_card(group_id=int(gid), user_id=target, card=card)
        await matcher.finish('改名片操作成功')
    except ActionFailed:
        await matcher.finish('权限不足')


# ==================== 管理员 +/- ====================

pm_set_admin = on_command('管理员+', priority=1,
                          aliases={'加管理', '管理加'}, rule=_rule, block=True)


@pm_set_admin.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid_owner(bot, matcher, event)
    targets = str(args).strip().split()
    if not targets:
        await matcher.finish('格式：/管理员+ QQ号')
    for qq in targets:
        if not qq.isdigit():
            await matcher.send(f'"{qq}"不是有效QQ号')
            continue
        try:
            await bot.set_group_admin(group_id=int(gid), user_id=int(qq), enable=True)
        except ActionFailed:
            await matcher.send(f'设置{qq}为管理员失败')
    await matcher.finish('设置管理员操作完毕')


pm_unset_admin = on_command('管理员-', priority=1,
                            aliases={'减管理', '管理减'}, rule=_rule, block=True)


@pm_unset_admin.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid_owner(bot, matcher, event)
    targets = str(args).strip().split()
    if not targets:
        await matcher.finish('格式：/管理员- QQ号')
    for qq in targets:
        if not qq.isdigit():
            await matcher.send(f'"{qq}"不是有效QQ号')
            continue
        try:
            await bot.set_group_admin(group_id=int(gid), user_id=int(qq), enable=False)
        except ActionFailed:
            await matcher.send(f'取消{qq}管理员失败')
    await matcher.finish('取消管理员操作完毕')


# ==================== 分管 +/- ====================

pm_deputy_add = on_command('分管+', priority=1,
                           aliases={'fg+'}, rule=_rule, block=True)


@pm_deputy_add.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    targets = str(args).strip().split()
    if not targets:
        await matcher.finish('格式：/分管+ QQ号')
    for qq in targets:
        if not qq.isdigit():
            await matcher.send(f'"{qq}"不是有效QQ号')
            continue
        result = await approve.g_admin_add(gid, int(qq))
        if result:
            await matcher.send(f'{qq}已成为群{gid}的分群管理')
        else:
            await matcher.send(f'用户{qq}已存在')
    await matcher.finish()


pm_deputy_del = on_command('分管-', priority=1,
                           aliases={'fg-'}, rule=_rule, block=True)


@pm_deputy_del.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    targets = str(args).strip().split()
    if not targets:
        await matcher.finish('格式：/分管- QQ号')
    for qq in targets:
        if not qq.isdigit():
            await matcher.send(f'"{qq}"不是有效QQ号')
            continue
        result = await approve.g_admin_del(gid, int(qq))
        if result:
            await matcher.send(f'{qq}删除成功')
        elif result is False:
            await matcher.send(f'{qq}还不是分群管理')
        elif result is None:
            await matcher.send(f'群{gid}未添加过分群管理')
    await matcher.finish()


# ==================== 分管权限管理 ====================

_OP_CN_MAP = {
    '禁言': 'ban', '禁': 'ban', '解禁': 'ban', '全员禁言': 'ban',
    '踢人': 'kick', '踢': 'kick',
    '拉黑': 'black', '黑': 'black',
    '改名片': 'change', '改': 'change',
    '撤回': 'recall',
    '精华': 'essence', '加精': 'essence', '取消精华': 'essence',
    '自动回复': 'auto_reply',
}

_OP_KEY_TO_CN = {
    'ban': '禁言', 'kick': '踢人', 'black': '拉黑',
    'change': '改名片', 'recall': '撤回', 'essence': '精华',
    'auto_reply': '自动回复',
}

pm_deputy_perm = on_command('分管权限', priority=1, rule=_rule, block=True)


@pm_deputy_perm.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    text = str(args).strip()

    if not text:
        perms = get_all_deputy_perms(gid)
        lines = [f'群{gid}分管权限状态：']
        for op_key in _DEPUTY_OPS:
            cn = _OP_KEY_TO_CN.get(op_key, op_key)
            status = '允许' if perms[op_key] else '禁止'
            lines.append(f'  {cn}({op_key})：{status}')
        lines.append(f'\n修改：/分管权限 操作名 开/关')
        await matcher.finish('\n'.join(lines))

    parts = text.split()
    if len(parts) < 2 or parts[-1] not in ('开', '关'):
        await matcher.finish('格式：/分管权限 操作名 开/关\n'
                             f'操作名可用：{"、".join(_OP_KEY_TO_CN.values())}')
    op_input = parts[0]
    enabled = parts[-1] == '开'
    op_key = _OP_CN_MAP.get(op_input, op_input)
    if op_key not in _DEPUTY_OPS:
        await matcher.finish(f'未知操作「{op_input}」\n'
                             f'可用：{"、".join(_OP_KEY_TO_CN.values())}')
    set_deputy_perm(gid, op_key, enabled)
    cn = _OP_KEY_TO_CN.get(op_key, op_key)
    await matcher.finish(f'已{"开启" if enabled else "关闭"}群{gid}分管「{cn}」权限')


# ==================== 词条 +/- ====================

pm_approve_add = on_command('词条+', priority=1,
                            aliases={'ct+', '审批+'}, rule=_rule, block=True)


@pm_approve_add.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    text = str(args).strip()
    if not text:
        await matcher.finish('格式：/词条+ 审批词条内容')
    result = await approve.write(gid, text)
    if result:
        await matcher.finish(f'已添加审批词条：{text}')
    elif result is False:
        await matcher.finish(f'词条「{text}」已存在')
    else:
        await matcher.finish('添加失败')


pm_approve_del = on_command('词条-', priority=1,
                            aliases={'ct-', '审批-'}, rule=_rule, block=True)


@pm_approve_del.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    text = str(args).strip()
    if not text:
        await matcher.finish('格式：/词条- 审批词条内容')
    result = await approve.delete(gid, text)
    if result:
        await matcher.finish(f'已删除审批词条：{text}')
    elif result is False:
        await matcher.finish(f'词条「{text}」不存在')
    else:
        await matcher.finish(f'群{gid}从未配置过词条')


pm_approve_list = on_command('查看词条', priority=1, rule=_rule, block=True)


@pm_approve_list.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent):
    gid = await _bound_gid(bot, matcher, event)
    contents = json_load(config_admin)
    if contents and gid in contents:
        await matcher.finish(f'群{gid}审批词条：\n' + '\n'.join(contents[gid]))
    else:
        await matcher.finish(f'群{gid}暂无审批词条')


# ==================== 开关 ====================

pm_switcher = on_command('开关', priority=1, rule=_rule, block=True)


@pm_switcher.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    func_name = str(args).strip()
    if not func_name:
        names = '、'.join(v[0] for v in admin_funcs.values())
        await matcher.finish(f'格式：/开关 功能名\n可用功能：{names}')

    target_func = None
    for func_key, aliases in admin_funcs.items():
        if func_name in aliases:
            target_func = func_key
            break
    if not target_func:
        await matcher.finish(f'未找到功能「{func_name}」')

    uid = str(event.user_id)
    binding = _get_binding(uid)
    if not binding:
        await matcher.finish('请先绑定群：/绑群 群号')

    funcs_status = json_load(switcher_path)
    if not funcs_status:
        await matcher.finish('开关配置文件不存在')

    if binding == 'all':
        if not _is_su(event.user_id):
            await matcher.finish('all模式仅限超级用户')
        first_state = None
        for gid_key in funcs_status:
            if target_func in funcs_status[gid_key]:
                first_state = funcs_status[gid_key][target_func]
                break
        new_state = not first_state if first_state is not None else True
        count = 0
        for gid_key in funcs_status:
            if target_func in funcs_status[gid_key]:
                funcs_status[gid_key][target_func] = new_state
                count += 1
        json_upload(switcher_path, funcs_status)
        state_str = '开启' if new_state else '关闭'
        await matcher.finish(f'已在{count}个群{state_str}「{func_name}」')
    else:
        if not await _check_perm(bot, event.user_id, binding):
            await matcher.finish(f'你不是群{binding}的管理员')
        if binding not in funcs_status:
            await matcher.finish(f'群{binding}尚未初始化开关配置')
        current = funcs_status[binding].get(target_func, False)
        funcs_status[binding][target_func] = not current
        json_upload(switcher_path, funcs_status)
        await matcher.finish(f'已{"关闭" if current else "开启"}「{func_name}」(群{binding})')


pm_switcher_status = on_command('开关状态', priority=1, rule=_rule, block=True)


@pm_switcher_status.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent):
    gid = await _bound_gid(bot, matcher, event)
    funcs_status = json_load(switcher_path)
    if not funcs_status or gid not in funcs_status:
        await matcher.finish(f'群{gid}尚未初始化开关配置')
    lines = [f'群{gid}开关状态：']
    for func_key, aliases in admin_funcs.items():
        status = funcs_status[gid].get(func_key, False)
        lines.append(f'  {aliases[0]}：{"开启" if status else "关闭"}')
    await matcher.finish('\n'.join(lines))


# ==================== 自动回复配置 ====================

pm_reply_add = on_command('自动回复+', priority=1,
                          aliases={'自动回复加', '添加自动回复'}, rule=_rule, block=True)


@pm_reply_add.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    text = str(args).strip()
    if '||' not in text:
        await matcher.finish('格式：/自动回复+ 关键词||回复内容')
    keyword, reply = text.split('||', 1)
    keyword, reply = keyword.strip(), reply.strip()
    if not keyword or not reply:
        await matcher.finish('关键词和回复内容不能为空')
    if add_custom_reply(gid, keyword, reply):
        await matcher.finish(f'已添加自动回复：{keyword}')
    else:
        await matcher.finish(f'关键词「{keyword}」已存在')


pm_reply_del = on_command('自动回复-', priority=1,
                          aliases={'自动回复减', '删除自动回复'}, rule=_rule, block=True)


@pm_reply_del.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            args: Message = CommandArg()):
    gid = await _bound_gid(bot, matcher, event)
    keyword = str(args).strip()
    if not keyword:
        await matcher.finish('格式：/自动回复- 关键词')
    if del_custom_reply(gid, keyword):
        await matcher.finish(f'已删除自动回复：{keyword}')
    else:
        await matcher.finish(f'未找到关键词「{keyword}」')


pm_reply_list = on_command('自动回复列表', priority=1,
                           aliases={'查看自动回复'}, rule=_rule, block=True)


@pm_reply_list.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent):
    gid = await _bound_gid(bot, matcher, event)
    lines = list_all_replies(gid)
    await matcher.finish('\n'.join(lines))


# ==================== 自动清理 ====================

pm_cleanup = on_command('自动清理', priority=1, rule=_rule, block=True)


@pm_cleanup.handle()
async def _(bot: Bot, matcher: Matcher, event: PrivateMessageEvent,
            state: T_State, args: Message = CommandArg()):
    gid = await _bound_gid_owner(bot, matcher, event)
    arg_text = str(args).strip()
    if not arg_text.isdigit() or int(arg_text) <= 0:
        await matcher.finish('格式：/自动清理 N（N为清理人数）')

    n = int(arg_text)
    gid_int = int(gid)

    this_lock = kick_lock_path / f"{gid}.lock"
    if this_lock.exists():
        await matcher.finish('当前群正在执行清理任务')
    this_lock.touch()
    state['lock_path'] = str(this_lock)
    state['gid'] = gid

    await matcher.send('正在获取群成员信息...')

    try:
        member_list = await bot.get_group_member_list(group_id=gid_int)
    except ActionFailed as e:
        this_lock.unlink(missing_ok=True)
        await matcher.finish(f'获取成员列表失败：{e}')

    now = int(time_module.time())
    protection_threshold = now - (NEW_MEMBER_DAYS * 86400)
    bot_id = int(bot.self_id)

    candidates = []
    for member in member_list:
        uid = member['user_id']
        role = member.get('role', 'member')
        join_time = member.get('join_time', 0)
        last_sent_time = member.get('last_sent_time', 0)

        if role in ('admin', 'owner'):
            continue
        if uid == bot_id or _is_su(uid):
            continue
        if join_time > protection_threshold:
            continue

        effective = last_sent_time if last_sent_time > 0 else join_time
        candidates.append({
            'uid': uid,
            'join_time': join_time,
            'last_sent_time': last_sent_time,
            'inactivity': now - effective,
            'nickname': member.get('card') or member.get('nickname') or str(uid),
        })

    candidates.sort(key=lambda x: x['inactivity'], reverse=True)
    to_kick = candidates[:n]

    if not to_kick:
        this_lock.unlink(missing_ok=True)
        await matcher.finish('没有符合条件的不活跃成员')

    lines = [f'群{gid}最不活跃的{len(to_kick)}名成员：\n']
    for i, m in enumerate(to_kick, 1):
        join_str = datetime.fromtimestamp(m['join_time']).strftime('%Y-%m-%d')
        last_str = (datetime.fromtimestamp(m['last_sent_time']).strftime('%Y-%m-%d')
                    if m['last_sent_time'] > 0 else '从未发言')
        lines.append(
            f"{i}. {m['nickname']}({m['uid']}) "
            f"入群:{join_str} 最后发言:{last_str}"
        )
    lines.append(
        f'\n共{len(to_kick)}人，回复「确认」全部清理；'
        f'回复「确认清理 2」或「确认清理 2-10」按序号清理；'
        f'回复其他内容取消'
    )

    state['kick_list'] = [m['uid'] for m in to_kick]
    await matcher.send('\n'.join(lines))


@pm_cleanup.got('confirm')
async def _(bot: Bot, matcher: Matcher, state: T_State):
    from pathlib import Path
    confirm = str(state['confirm']).strip()
    lock_path = Path(state.get('lock_path', ''))
    gid = state.get('gid', '')

    kick_list = state.get('kick_list', [])
    if not kick_list:
        lock_path.unlink(missing_ok=True)
        await matcher.finish('没有需要清理的成员')

    selected_indexes, error = parse_cleanup_selection(confirm, len(kick_list))
    if error:
        await matcher.reject(error)
    if selected_indexes is None:
        lock_path.unlink(missing_ok=True)
        await matcher.finish('已取消清理')

    kick_list = [kick_list[index] for index in selected_indexes]

    await matcher.send(f'开始清理{len(kick_list)}名成员...')

    success, fail = [], []
    for uid in kick_list:
        try:
            await asyncio.sleep(randint(1, 5))
            await bot.set_group_kick(group_id=int(gid), user_id=uid,
                                     reject_add_request=False)
            success.append(uid)
            logger.info(f"PM清理：群{gid} 踢出 {uid}")
        except ActionFailed as e:
            logger.error(f"PM清理：群{gid} 踢出 {uid} 失败：{e}")
            fail.append(uid)

    lock_path.unlink(missing_ok=True)
    result = f'清理完成！成功：{len(success)}人'
    if fail:
        result += f'，失败：{len(fail)}人'
    await matcher.finish(result)
