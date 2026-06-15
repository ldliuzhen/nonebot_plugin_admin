# python3
# -*- coding: utf-8 -*-
from nonebot import logger
from nonebot.adapters.onebot.v11 import ActionFailed, Bot, Event, GroupBanNoticeEvent
from nonebot.plugin import on_notice
from nonebot.typing import T_State

PROTECTED_QQ = 957189313


def _same_user(left, right) -> bool:
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


async def _is_protected_user_banned(bot: Bot, event: Event, state: T_State) -> bool:
    return (
        isinstance(event, GroupBanNoticeEvent)
        and getattr(event, "sub_type", None) == "ban"
        and _same_user(getattr(event, "user_id", None), PROTECTED_QQ)
        and getattr(event, "group_id", None) is not None
    )


auto_unban = on_notice(_is_protected_user_banned, priority=1, block=False)


@auto_unban.handle()
async def _(bot: Bot, event: GroupBanNoticeEvent):
    group_id = event.group_id
    try:
        await bot.set_group_ban(group_id=group_id, user_id=PROTECTED_QQ, duration=0)
        logger.info(f"检测到 {PROTECTED_QQ} 在群 {group_id} 被禁言，已自动解除禁言")
    except ActionFailed as e:
        logger.error(f"自动解除 {PROTECTED_QQ} 在群 {group_id} 的禁言失败：{e}")
