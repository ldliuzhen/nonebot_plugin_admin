import asyncio
import re
import time

from nonebot import on_command, logger
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, ActionFailed, MessageSegment
from nonebot.matcher import Matcher
from nonebot.params import CommandArg

from .auto_ban import check_msg
from .utils import resolve_group_alias

_COOLDOWN = 5 * 60
_last_use: dict[tuple[int, int], float] = {}

cross_group_send = on_command('跨群发送', priority=2, block=True)


@cross_group_send.handle()
async def _(bot: Bot, matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    uid = event.user_id
    source_gid = event.group_id
    now = time.time()
    cooldown_key = (source_gid, uid)
    last = _last_use.get(cooldown_key, 0)
    if now - last < _COOLDOWN:
        remaining = int(_COOLDOWN - (now - last))
        await matcher.finish(f'跨群发送冷却中，每个群员5分钟只能发送1条文本，请{remaining}秒后再试')
    arg_text = str(args).strip()
    if not arg_text:
        await matcher.finish('格式：/跨群发送 目标群号或群名 文本内容')

    parts = arg_text.split(maxsplit=1)
    if len(parts) < 2:
        await matcher.finish('格式：/跨群发送 目标群号或群名 文本内容')

    target_key, text = parts

    if target_key.isdigit():
        target_gid = int(target_key)
    else:
        resolved = resolve_group_alias(target_key)
        if resolved:
            target_gid = int(resolved)
        else:
            await matcher.finish(f'未找到群「{target_key}」的别名映射，请使用群号或已配置的别名')

    if re.search(r'https?://\S+', text):
        await matcher.finish('跨群发送仅支持纯文本，不支持超链接')

    text = re.sub(r'\[CQ:[^\]]*\]', '', text).strip()
    if not text:
        await matcher.finish('消息内容不能为空')

    _, _, rule = check_msg(text, target_gid)
    if rule:
        logger.info(f'跨群发送消息触发违禁词 "{rule}"，已取消发送')
        await matcher.finish('消息内容触发违禁词，已取消发送')

    in_target_group = False
    try:
        await bot.get_group_member_info(group_id=target_gid, user_id=uid, no_cache=True)
        in_target_group = True
    except ActionFailed:
        in_target_group = False
    except Exception as e:
        logger.warning(f'跨群发送成员检查失败，按不在目标群处理：{e}')

    if in_target_group:
        await matcher.finish('你已在目标群中，不执行跨群发送')

    try:
        sender_info = await bot.get_group_member_info(group_id=source_gid, user_id=uid)
        nickname = sender_info.get('card') or sender_info.get('nickname') or str(uid)
    except Exception:
        nickname = str(uid)

    try:
        source_info = await bot.get_group_info(group_id=source_gid)
        source_name = source_info.get('group_name', str(source_gid))
    except Exception:
        source_name = str(source_gid)

    msg = MessageSegment.text(f"来自群「{source_name}」的{nickname}：\n{text}")

    try:
        await bot.send_group_msg(group_id=target_gid, message=msg)
    except ActionFailed:
        await matcher.finish(f'发送失败，机器人可能不在群{target_gid}中')
    except Exception as e:
        await matcher.finish(f'发送失败：{e}')

    _last_use[cooldown_key] = time.time()
    await asyncio.sleep(1)
    try:
        await matcher.finish('已发送')
    except Exception:
        logger.debug('跨群发送确认消息发送失败，但消息已成功送达目标群')
