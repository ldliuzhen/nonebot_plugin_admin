# python3
# -*- coding: utf-8 -*-
# @Time    : 2023/1/19 3:34
# @Author  : yzyyz
# @Email   :  youzyyz1384@qq.com
# @File    : admin_role.py
# @Software: PyCharm
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.permission import Permission

from .approve import g_admin


async def _deputy_admin(event: GroupMessageEvent) -> bool:
    admins = g_admin()
    gid = str(event.group_id)
    if admins.get(gid):
        return event.user_id in admins[gid]
    else:
        return False


DEPUTY_ADMIN: Permission = Permission(_deputy_admin)
"""匹配分管事件"""


from .utils import get_deputy_perm


def deputy_with_perm(operation: str) -> Permission:
    async def _checker(event: GroupMessageEvent) -> bool:
        admins = g_admin()
        gid = str(event.group_id)
        if not (admins.get(gid) and event.user_id in admins[gid]):
            return False
        return get_deputy_perm(gid, operation)
    _checker.__name__ = f"_deputy_{operation}"
    return Permission(_checker)


DEPUTY_BAN = deputy_with_perm("ban")
DEPUTY_KICK = deputy_with_perm("kick")
DEPUTY_BLACK = deputy_with_perm("black")
DEPUTY_CHANGE = deputy_with_perm("change")
DEPUTY_RECALL = deputy_with_perm("recall")
DEPUTY_ESSENCE = deputy_with_perm("essence")
DEPUTY_AUTO_REPLY = deputy_with_perm("auto_reply")
