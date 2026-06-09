# python3
# -*- coding: utf-8 -*-
# @Time    : 2022/12/19 3:57
# @Author  : yzyyz
# @Email   :  youzyyz1384@qq.com
# @File    : group_recall.py
# @Software: PyCharm
from nonebot import on_notice
from nonebot.adapters.onebot.v11 import GroupRecallNoticeEvent, Bot, Message, MessageSegment, Event
from nonebot.adapters.onebot.v11.exception import ActionFailed
try:
    from pydantic import parse_obj_as
except ModuleNotFoundError:
    def parse_obj_as(model, obj):
        if model is MessageSegment and isinstance(obj, dict):
            return MessageSegment(obj.get("type", "text"), obj.get("data") or {})
        return obj

from .config import global_config

su = global_config.superusers


async def _is_group_recall(bot: Bot, event: Event, state: dict) -> bool:
    return isinstance(event, GroupRecallNoticeEvent) and getattr(event, "message_id", None) is not None


group_recall = on_notice(_is_group_recall, priority=5)
@group_recall.handle()
async def _(bot: Bot, event: GroupRecallNoticeEvent):
    user_id = event.user_id  # 消息发送者
    operator_id = event.operator_id  # 撤回消息的人
    group_id = event.group_id  # 群号
    message_id = event.message_id  # 消息 id

    if int(user_id) != int(operator_id): return  # 撤回人不是发消息人，是管理员撤回成员消息，不处理
    if int(operator_id) in su or str(operator_id) in su: return  # 发起撤回的人是超管，不处理
    # 管理员撤回自己的也不处理
    operator_info = await bot.get_group_member_info(group_id=group_id, user_id=operator_id, no_cache=True)
    if operator_info['role'] != 'member': return
    # 防撤回
    try:
        recalled_message = await bot.get_msg(message_id=message_id)
    except ActionFailed:
        await bot.send_group_msg(group_id=group_id, message='检测到成员撤回了一条消息，但原消息获取失败')
        return
    recall_notice = f"检测到{operator_info['card'] if operator_info['card'] else operator_info['nickname']}({operator_info['user_id']})撤回了一条消息：\n\n"
    message = recalled_message.get('message', '')
    if not isinstance(message, str):
        segments = [MessageSegment.text(recall_notice)]
        for seg in message:
            try:
                segments.append(parse_obj_as(MessageSegment, seg))
            except Exception:
                segments.append(MessageSegment.text(str(seg)))
        _message = Message(segments)
    else:
        _message = recall_notice + message
    await bot.send_group_msg(group_id=group_id, message=_message)
