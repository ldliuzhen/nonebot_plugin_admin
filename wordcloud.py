# python3
# -*- coding: utf-8 -*-
# @Time    : 2022/6/25 18:26
# @Author  : yzyyz
# @Email   :  youzyyz1384@qq.com
# @File    : wordcloud.py
# @Software: PyCharm
import asyncio
import json
import os
import random

try:
    import httpx
except ModuleNotFoundError:
    from . import compat_httpx as httpx
from nonebot import on_command, logger
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageSegment
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER

from .path import *
from .utils import participle_simple_handle, json_load, json_upload, resolve_group_alias

cloud = on_command('群词云', priority=2, block=True)


def _load_wc_block(gid: str) -> list[str]:
    data = json_load(wc_block_path) or {}
    return data.get(gid, [])


def _save_wc_block(gid: str, uids: list[str]):
    data = json_load(wc_block_path) or {}
    if uids:
        data[gid] = uids
    elif gid in data:
        del data[gid]
    json_upload(wc_block_path, data)


def is_wc_blocked(gid: str, uid: str) -> bool:
    return uid in _load_wc_block(gid)


@cloud.handle()
async def _(bot, event: GroupMessageEvent, matcher: Matcher, args: Message = CommandArg()):
    gid = str(event.group_id)
    text = str(args).strip()
    cross_group_name = None

    if text.startswith('屏蔽列表'):
        blocked = _load_wc_block(gid)
        if not blocked:
            await matcher.finish('当前群没有屏蔽任何人')
        lines = ['词云屏蔽列表：']
        for uid in blocked:
            try:
                info = await bot.get_group_member_info(group_id=event.group_id, user_id=int(uid))
                name = info.get('card') or info.get('nickname') or uid
            except Exception:
                name = uid
            lines.append(f'  {name}({uid})')
        await matcher.finish('\n'.join(lines))

    if text.startswith('解除屏蔽'):
        perm = await (SUPERUSER | GROUP_ADMIN | GROUP_OWNER)(bot, event)
        if not perm:
            await matcher.finish('权限不足')
        qq = text[len('解除屏蔽'):].strip()
        if not qq or not qq.isdigit():
            await matcher.finish('格式：/群词云 解除屏蔽 QQ号')
        blocked = _load_wc_block(gid)
        if qq not in blocked:
            await matcher.finish(f'{qq}不在屏蔽列表中')
        blocked.remove(qq)
        _save_wc_block(gid, blocked)
        await matcher.finish(f'已解除屏蔽{qq}的词云记录')

    if text.startswith('屏蔽'):
        perm = await (SUPERUSER | GROUP_ADMIN | GROUP_OWNER)(bot, event)
        if not perm:
            await matcher.finish('权限不足')
        qq = text[len('屏蔽'):].strip()
        if not qq or not qq.isdigit():
            await matcher.finish('格式：/群词云 屏蔽 QQ号')
        blocked = _load_wc_block(gid)
        if qq in blocked:
            await matcher.finish(f'{qq}已在屏蔽列表中')
        blocked.append(qq)
        _save_wc_block(gid, blocked)
        await matcher.finish(f'已屏蔽{qq}的词云记录')

    target_gid_str = None
    if text and text.isdigit():
        target_gid_str = text
    elif text:
        resolved = resolve_group_alias(text)
        if resolved:
            target_gid_str = resolved
    if target_gid_str:
        try:
            info = await bot.get_group_info(group_id=int(target_gid_str))
            cross_group_name = info.get('group_name', target_gid_str)
        except Exception:
            await matcher.finish(f'无法查询群{target_gid_str}，可能机器人不在该群中')
        gid = target_gid_str

    try:
        from wordcloud import WordCloud, ImageColorGenerator
    except ModuleNotFoundError:
        await cloud.finish('未安装wordcloud库，请执行 pip install wordcloud')

    background_img = os.listdir(wordcloud_bg_path)
    if background_img:
        try:
            async with httpx.AsyncClient() as client:
                num = int((await client.get(
                    'https://fastly.jsdelivr.net/gh/yzyyz1387/blogimages/nonebot/wordcloud/num.txt')).read())
                if num > len(background_img):
                    await cloud.send(
                        f"开发者新提供了{num - len(background_img)}张图片，您可以发送【更新mask】下载新的图片")
        except:
            pass
    else:
        try:
            async with httpx.AsyncClient() as client:
                range_ = int((await client.get(
                    'https://fastly.jsdelivr.net/gh/yzyyz1387/blogimages/nonebot/wordcloud/num.txt')).read())
                logger.info(f"获取到{range_}张mask图片")
                for i in range(range_):
                    wordcloud_bg = await client.get(
                        f"https://fastly.jsdelivr.net/gh/yzyyz1387/blogimages/nonebot/wordcloud/bg{i}.png")
                    logger.info(f"正下载{i}张mask图片")
                    with open(wordcloud_bg_path / f"{i}.png", 'wb') as f:
                        f.write(wordcloud_bg.content)
                    f.close()
        except:
            logger.error('下载词云mask图片出现错误')
            return

    from .word_analyze import flush_freq
    flush_freq(gid)

    freq_path = words_contents_path / f"{gid}.json"
    old_txt_path = words_contents_path / f"{gid}.txt"

    freq = None
    if freq_path.exists():
        with open(freq_path, 'r', encoding='utf-8') as f:
            freq = json.load(f)
    elif old_txt_path.exists():
        await cloud.send("正在迁移旧数据格式，请稍候...")
        freq = await asyncio.to_thread(_migrate_txt_to_freq, old_txt_path)
        if freq:
            with open(freq_path, 'w', encoding='utf-8') as f:
                json.dump(freq, f, ensure_ascii=False, separators=(',', ':'))
            old_txt_path.rename(old_txt_path.with_suffix('.txt.bak'))
            logger.info(f"群{gid}词频数据迁移完成")

    if not freq:
        if cross_group_name:
            await cloud.finish(f"群「{cross_group_name}」未被记录")
        else:
            await cloud.finish("当前群未被记录，请先在群内发送【记录本群】")

    this_stop_ = stop_words_path / f"{gid}.txt"
    if this_stop_.exists():
        stop_ = set(this_stop_.read_text(encoding='utf-8').split('\n') + participle_simple_handle())
    else:
        stop_ = set(participle_simple_handle())

    freq_filtered = {k: v for k, v in freq.items() if k not in stop_ and len(k) > 1}
    if not freq_filtered:
        await cloud.finish("数据不足，无法生成词云")

    img_path = Path(re_img_path / f"wordcloud_{gid}.png")
    out = await asyncio.to_thread(
        _generate_cloud_from_freq, freq_filtered, img_path, str(ttf_path.resolve())
    )
    if out[0]:
        if cross_group_name:
            await cloud.send(f"群「{cross_group_name}」的词云：")
        await cloud.send(MessageSegment.image(out[1]))
    else:
        await cloud.send(out[1])


def _migrate_txt_to_freq(txt_path: Path) -> dict:
    try:
        import jieba
        text = txt_path.read_text(encoding='utf-8')
        words = jieba.lcut(text)
        freq = {}
        for w in words:
            w = w.strip()
            if len(w) <= 1:
                continue
            freq[w] = freq.get(w, 0) + 1
        return freq
    except Exception as e:
        logger.error(f"迁移词频数据失败: {e}")
        return {}


def _generate_cloud_from_freq(freq: dict, img_path: Path, font_path: str):
    try:
        from wordcloud import WordCloud, ImageColorGenerator
        from imageio import imread

        bg_file = random.choice(os.listdir(wordcloud_bg_path))
        background_image = imread(wordcloud_bg_path / bg_file)

        wc = WordCloud(
            font_path=font_path,
            width=1920, height=1080, mode='RGBA',
            background_color='#ffffff',
            mask=background_image,
        ).generate_from_frequencies(freq)
        img_colors = ImageColorGenerator(background_image, default_color=(255, 255, 255))
        wc.recolor(color_func=img_colors)
        wc.to_file(img_path)
        return True, img_path.read_bytes()
    except Exception as err:
        logger.info(f"出现错误{type(err)}:{err}")
        return False, f"出现错误{type(err)}:{err}"
