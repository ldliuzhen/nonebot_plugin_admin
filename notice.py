# python3
# -*- coding: utf-8 -*-
# @Time    : 2022/1/16 22:02
# @Author  : yzyyz
# @Email   :  youzyyz1384@qq.com
# @File    : notice.py
# @Software: PyCharm
import re

from nonebot import on_command
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from . import approve
from .message import *


def _parse_deputy_targets(event: GroupMessageEvent, args: Message) -> tuple[list[int], bool, list[str]]:
    targets = []
    invalid = []
    has_all = False

    def add(value) -> None:
        nonlocal has_all
        qq = str(value).strip()
        if not qq:
            return
        if qq == 'all':
            has_all = True
            return
        if qq.isdigit():
            targets.append(int(qq))
        else:
            invalid.append(qq)

    for seg in event.message:
        if seg.type == 'at':
            add(seg.data.get('qq') or seg.data.get('user_id'))

    text = str(args).strip()
    if text:
        for qq in re.findall(r'\[CQ:at,qq=([^,\]]+)', text):
            add(qq)
        text = re.sub(r'\[CQ:at,qq=[^\]]+\]', ' ', text)
        for qq in re.split(r'[\s,，]+', text):
            add(qq)

    deduped = []
    seen = set()
    for qq in targets:
        if qq not in seen:
            seen.add(qq)
            deduped.append(qq)
    return deduped, has_all, invalid

# 查看当前群分管
gad = on_command('分管', priority=2, aliases={'/gad', '/分群管理', '查看分管'}, block=True,
                 permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
@gad.handle()
async def _(matcher: Matcher, event: GroupMessageEvent):
    gid = str(event.group_id)
    admins = approve.g_admin()
    try:
        rely = str(admins[gid])
        await matcher.finish(f"本群分管：{rely}")
    except KeyError:
        await matcher.finish('查询不到呢，使用 分管+@xx 来添加分管')

# 查看所有分管
su_g_admin = on_command('所有分管', priority=2, aliases={'/sugad', '/su分群管理'}, block=True, permission=SUPERUSER)
@su_g_admin.handle()
async def _(matcher: Matcher):
    admins = approve.g_admin()
    await matcher.finish(str(admins))

# 添加分群管理员
g_admin = on_command('分管+', priority=2, aliases={'/gad+', '分群管理+', '分管加', '分群管理加', 'fg+'}, block=True,
                     permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
@g_admin.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    gid = str(event.group_id)
    targets, has_all, invalid = _parse_deputy_targets(event, args)
    if has_all:
        await matcher.finish('不能使用@全体成员')
    if not targets and not invalid:
        await matcher.finish('请输入用户QQ号或@某人')
    for qq in invalid:
        await matcher.send(f'"{qq}" 不是有效的QQ号')
    for qq in targets:
        g_admin_handle = await approve.g_admin_add(gid, qq)
        if g_admin_handle:
            await matcher.send(f"{qq}已成为本群分群管理：将接收加群处理结果，同时具有群管权限，但分管不能任命超管")
        else:
            await matcher.send(f"用户{qq}已存在")

# 开启superuser接收处理结果
su_gad = on_command('接收', priority=2, aliases={'群管接收'}, block=True, permission=SUPERUSER)
@su_gad.handle()
async def _(matcher: Matcher):
    status = await approve.su_on_off()
    await matcher.finish('已开启审批消息接收' if status else '已关闭审批消息接收')

# 删除分群管理
g_admin_ = on_command('分管-', priority=2, aliases={'/gad-', '分群管理-', '分管减', '分群管理减', 'fg-'}, block=True,
                      permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)
@g_admin_.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    gid = str(event.group_id)
    targets, has_all, invalid = _parse_deputy_targets(event, args)
    if has_all:
        await matcher.finish('不能使用@全体成员')
    if not targets and not invalid:
        await matcher.finish('请输入用户QQ号或@某人')
    for qq in invalid:
        await matcher.send(f'"{qq}" 不是有效的QQ号')
    for qq in targets:
        g_admin_del_handle = await approve.g_admin_del(gid, qq)
        if g_admin_del_handle:
            await matcher.send(f"{qq}删除成功")
        elif g_admin_del_handle is False:
            await matcher.send(f"{qq}还不是分群管理")
        elif g_admin_del_handle is None:
            await matcher.send(f"群{gid}未添加过分群管理\n使用 分管+@某人 来添加分群管理")

# ==================== 分管权限管理 ====================

from .utils import get_all_deputy_perms, set_deputy_perm, _DEPUTY_OPS

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

deputy_perm_cmd = on_command('分管权限', priority=2, block=True,
                             permission=GROUP_ADMIN | GROUP_OWNER | SUPERUSER)


@deputy_perm_cmd.handle()
async def _(matcher: Matcher, event: GroupMessageEvent, args: Message = CommandArg()):
    gid = str(event.group_id)
    text = str(args).strip()

    if not text:
        perms = get_all_deputy_perms(gid)
        lines = [f'群{gid}分管权限状态：']
        for op_key in _DEPUTY_OPS:
            cn = _OP_KEY_TO_CN.get(op_key, op_key)
            status = '允许' if perms[op_key] else '禁止'
            lines.append(f'  {cn}({op_key})：{status}')
        lines.append(f'\n修改：/分管权限 操作名 开/关')
        lines.append(f'操作名可用：{"、".join(_OP_KEY_TO_CN.values())}')
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
    await matcher.finish(f'已{"开启" if enabled else "关闭"}分管「{cn}」权限')
