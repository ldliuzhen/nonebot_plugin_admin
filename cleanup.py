# python3
# -*- coding: utf-8 -*-
# @File    : cleanup.py
import asyncio
import time as time_module
from datetime import datetime
from random import randint

from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.adapters.onebot.v11.permission import GROUP_OWNER
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot.adapters import Message

from .config import global_config
from .cleanup_selection import parse_cleanup_selection
from .path import kick_lock_path
from .utils import fi

su = global_config.superusers

NEW_MEMBER_DAYS = 30

auto_cleanup = on_command('自动清理', priority=2, block=True,
                          permission=SUPERUSER | GROUP_OWNER)


@auto_cleanup.handle()
async def handle_first(bot: Bot, event: GroupMessageEvent, matcher: Matcher,
                       state: T_State, args: Message = CommandArg()):
    arg_text = str(args).strip()
    if not arg_text.isdigit() or int(arg_text) <= 0:
        await matcher.finish('请输入正确的清理人数，例如：/自动清理 20')

    n = int(arg_text)
    gid = event.group_id

    this_lock = kick_lock_path / f"{gid}.lock"
    if this_lock.exists():
        await matcher.finish('当前群正在执行清理任务，如需解锁请发送【清理解锁】')
    this_lock.touch()
    state['lock_path'] = str(this_lock)

    await matcher.send('正在获取群成员信息，请稍候...')

    try:
        member_list = await bot.get_group_member_list(group_id=gid)
    except ActionFailed as e:
        this_lock.unlink(missing_ok=True)
        await matcher.finish(f'获取群成员列表失败：{e}')

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
        if uid == bot_id or uid in su or str(uid) in su:
            continue
        if join_time > protection_threshold:
            continue

        effective_last_active = last_sent_time if last_sent_time > 0 else join_time
        inactivity = now - effective_last_active

        candidates.append({
            'uid': uid,
            'join_time': join_time,
            'last_sent_time': last_sent_time,
            'effective_last_active': effective_last_active,
            'inactivity': inactivity,
            'nickname': member.get('card') or member.get('nickname') or str(uid),
        })

    candidates.sort(key=lambda x: x['inactivity'], reverse=True)
    to_kick = candidates[:n]

    if not to_kick:
        this_lock.unlink(missing_ok=True)
        await matcher.finish('没有找到符合条件的不活跃成员')

    lines = [f'以下是最不活跃的 {len(to_kick)} 名成员：\n']
    for i, m in enumerate(to_kick, 1):
        join_str = datetime.fromtimestamp(m['join_time']).strftime('%Y-%m-%d')
        if m['last_sent_time'] > 0:
            last_str = datetime.fromtimestamp(m['last_sent_time']).strftime('%Y-%m-%d')
        else:
            last_str = '从未发言'
        lines.append(
            f"{i}. {m['nickname']}({m['uid']}) "
            f"入群:{join_str} 最后发言:{last_str}"
        )
    lines.append(
        f'\n共 {len(to_kick)} 人，回复「确认」全部清理；'
        f'回复「确认清理 2」或「确认清理 2-10」按序号清理；'
        f'回复其他内容取消'
    )

    state['kick_list'] = [m['uid'] for m in to_kick]
    await matcher.send('\n'.join(lines))


@auto_cleanup.got('confirm')
async def handle_confirm(bot: Bot, event: GroupMessageEvent,
                         matcher: Matcher, state: T_State):
    from pathlib import Path
    confirm = str(state['confirm']).strip()
    lock_path = Path(state.get('lock_path', ''))

    kick_list = state.get('kick_list', [])
    if not kick_list:
        lock_path.unlink(missing_ok=True)
        await matcher.finish('没有需要清理的成员')

    selected_indexes, error = parse_cleanup_selection(confirm, len(kick_list))
    if error:
        await matcher.reject(error)
    if selected_indexes is None:
        lock_path.unlink(missing_ok=True)
        await matcher.finish('已取消清理操作')

    kick_list = [kick_list[index] for index in selected_indexes]

    await matcher.send(f'开始清理 {len(kick_list)} 名成员，请稍候...')

    success = []
    fail = []
    for uid in kick_list:
        try:
            await asyncio.sleep(randint(1, 5))
            await bot.set_group_kick(group_id=event.group_id, user_id=uid,
                                     reject_add_request=False)
            success.append(uid)
            logger.info(f"自动清理：群{event.group_id} 踢出 {uid}")
        except ActionFailed as e:
            logger.error(f"自动清理：群{event.group_id} 踢出 {uid} 失败：{e}")
            fail.append(uid)

    lock_path.unlink(missing_ok=True)

    result = f'清理完成！成功：{len(success)} 人'
    if fail:
        result += f'，失败：{len(fail)} 人'
    await fi(matcher, result)
