# python3
# -*- coding: utf-8 -*-
# @Time    : 2022/2/5 16:25
# @Author  : yzyyz (Modified for Slim Caching & Politics)
# @File    : img_check.py
# @Software: PyCharm
import json
import os
import hashlib
import time
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11.exception import ActionFailed, NetworkError
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import Depends

from .message import *
from .path import *
from .config import plugin_config
from .utils import mute_sb, image_moderation_async, get_user_violation, sd, fi, recall_event_message

# ================= 配置缓存路径 =================
CONFIG_DIR = str(config_path)

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)

CACHE_FILE = os.path.join(CONFIG_DIR, "img_check_cache.json")
IMG_CACHE = {}
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


def _cache_now() -> int:
    return int(time.time())


def _cache_timestamp(value, default: int) -> int:
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return default
    return ts if ts > 0 else default


def _is_cache_wrapper(value) -> bool:
    return isinstance(value, dict) and "cached_at" in value and "result" in value


def _normalize_cache_entry(value, now: int):
    if _is_cache_wrapper(value):
        cached_at = _cache_timestamp(value.get("cached_at"), now)
        result = value.get("result")
    else:
        cached_at = now
        result = value
    if not isinstance(result, dict):
        return None
    return {"cached_at": cached_at, "result": result}


def _normalize_cache_on_load(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    now = _cache_now()
    normalized = {}
    for key, value in raw.items():
        entry = _normalize_cache_entry(value, now)
        if entry is not None:
            normalized[str(key)] = entry
    return normalized


def _cleanup_expired_cache() -> int:
    now = _cache_now()
    cutoff = now - CACHE_TTL_SECONDS
    removed = 0
    for key, value in list(IMG_CACHE.items()):
        entry = _normalize_cache_entry(value, now)
        if entry is None or entry["cached_at"] < cutoff:
            IMG_CACHE.pop(key, None)
            removed += 1
            continue
        if value is not entry:
            IMG_CACHE[key] = entry
    return removed


def _write_cache_file():
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(IMG_CACHE, f, ensure_ascii=False, separators=(',', ':'))


def save_cache():
    """保存缓存到本地文件，并清除超过30天的旧记录"""
    try:
        removed = _cleanup_expired_cache()
        _write_cache_file()
        if removed:
            logger.info(f"已清理 {removed} 条超过30天的图片审核缓存")
    except Exception as e:
        logger.error(f"保存缓存失败: {e}")


def get_cached_result(img_key: str):
    entry = IMG_CACHE.get(img_key)
    if entry is None:
        return None
    now = _cache_now()
    normalized = _normalize_cache_entry(entry, now)
    if normalized is None or normalized["cached_at"] < now - CACHE_TTL_SECONDS:
        IMG_CACHE.pop(img_key, None)
        save_cache()
        return None
    IMG_CACHE[img_key] = normalized
    return normalized["result"]


def set_cached_result(img_key: str, result: dict):
    if not isinstance(result, dict):
        return
    IMG_CACHE[img_key] = {"cached_at": _cache_now(), "result": result}
    save_cache()

# 加载缓存
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            raw_cache = json.load(f)
            IMG_CACHE = _normalize_cache_on_load(raw_cache)
        removed = _cleanup_expired_cache()
        if removed or raw_cache != IMG_CACHE:
            _write_cache_file()
        if removed:
            logger.info(f"已清理 {removed} 条超过30天的图片审核缓存")
        logger.info(f"成功加载图片审核缓存，路径: {CACHE_FILE}，共 {len(IMG_CACHE)} 条记录")
    except Exception as e:
        logger.error(f"加载缓存失败: {e}")
        IMG_CACHE = {}

def get_img_key(img_url: str) -> str:
    """生成图片的唯一Key (MD5)"""
    return hashlib.md5(img_url.encode('utf-8')).hexdigest()
# ===========================================

DEFAULT_IMG_CHECK_RULES = [
    {"name": "色情", "label": "Porn", "score": 90, "recall": True, "mute": True, "mute_seconds": 0},
    {"name": "涉政", "label": "Politics", "score": 90, "recall": True, "mute": True, "mute_seconds": 0},
    {"name": "性感", "label": "Sexy", "score": 90, "recall": True, "mute": True, "mute_seconds": 0, "enabled": False},
]


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "关", "关闭", "否")
    return bool(value)


def _as_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_img_check_rules() -> list[dict]:
    raw = getattr(plugin_config, "img_check_rules_json", "")
    if not raw:
        return DEFAULT_IMG_CHECK_RULES
    try:
        rules = json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        logger.error(f"图片检测规则解析失败，使用默认规则: {e}")
        return DEFAULT_IMG_CHECK_RULES
    if not isinstance(rules, list):
        logger.error("图片检测规则必须是 JSON 数组，使用默认规则")
        return DEFAULT_IMG_CHECK_RULES
    return [rule for rule in rules if isinstance(rule, dict)]


def _compact_moderation_result(raw: dict) -> dict:
    return {
        "Suggestion": raw.get("Suggestion", "Pass"),
        "Label": raw.get("Label", "Normal"),
        "SubLabel": raw.get("SubLabel", ""),
        "Score": raw.get("Score", 0),
        "LabelResults": raw.get("LabelResults", []) or [],
        "ObjectResults": raw.get("ObjectResults", []) or [],
        "OcrResults": raw.get("OcrResults", []) or [],
        "LibResults": raw.get("LibResults", []) or [],
    }


def _iter_moderation_hits(result: dict):
    yield {
        "scene": "",
        "label": result.get("Label", "Normal"),
        "sub_label": result.get("SubLabel", ""),
        "score": _as_int(result.get("Score"), 0),
        "suggestion": result.get("Suggestion", "Pass"),
    }
    for section in ("LabelResults", "ObjectResults", "OcrResults", "LibResults"):
        for item in result.get(section, []) or []:
            if not isinstance(item, dict):
                continue
            yield {
                "scene": item.get("Scene", ""),
                "label": item.get("Label", "Normal"),
                "sub_label": item.get("SubLabel", ""),
                "score": _as_int(item.get("Score"), 0),
                "suggestion": item.get("Suggestion", "Pass"),
            }


def _rule_matches_hit(rule: dict, hit: dict) -> bool:
    if not _as_bool(rule.get("enabled", True), True):
        return False
    threshold = _as_int(rule.get("score"), 90)
    if hit["score"] < threshold:
        return False
    for rule_key, hit_key in (("scene", "scene"), ("label", "label"), ("sub_label", "sub_label")):
        expected = str(rule.get(rule_key, "")).strip()
        if expected and expected.lower() != str(hit.get(hit_key, "")).strip().lower():
            return False
    return bool(
        str(rule.get("scene", "")).strip()
        or str(rule.get("label", "")).strip()
        or str(rule.get("sub_label", "")).strip()
    )


def _match_img_rule(result: dict):
    matches = []
    for rule in _load_img_check_rules():
        for hit in _iter_moderation_hits(result):
            if _rule_matches_hit(rule, hit):
                matches.append((hit["score"], rule, hit))
    if not matches:
        return None
    _, rule, hit = max(matches, key=lambda item: item[0])
    return rule, hit


def _mute_time_for_level(level) -> int:
    level = max(0, min(_as_int(level), max(time_scop_map)))
    return time_scop_map[level]

find_pic = on_message(priority=2, block=False)
@find_pic.handle()
async def check_pic(bot: Bot, matcher: Matcher, event: GroupMessageEvent, img_lst: list = Depends(msg_img)):
    uid = [event.get_user_id()]
    gid = event.group_id
    
    for img in img_lst:
        img_key = get_img_key(img)
        result = None
        
        # 1. 检查缓存
        cached_result = get_cached_result(img_key)
        if cached_result is not None:
            logger.info(f"图片命中缓存，跳过API")
            result = cached_result
        else:
            # 2. 缓存未命中，调用 API
            try:
                # result = await pic_ban_cof(url = img)
                raw_result = await image_moderation_async(img)
                logger.info(f"API原始返回: {raw_result}")
                
                if raw_result:
                    result = _compact_moderation_result(raw_result)
                    set_cached_result(img_key, result)
            except TypeError:
                logger.error("请求图片安全接口失败")
                continue
            except Exception as e:
                logger.error(f"API调用或数据清洗出错: {e}")
                continue

        try:
            if not result:
                continue

            match = _match_img_rule(result)
            if match:
                rule, hit = match
                label = hit.get("label") or hit.get("scene") or "Unknown"
                level = await get_user_violation(gid, event.user_id, label, event.raw_message)
                mute_seconds = _as_int(rule.get("mute_seconds"), 0)
                if mute_seconds <= 0:
                    mute_seconds = _mute_time_for_level(level)
                recall = _as_bool(rule.get("recall", True), True)
                mute = _as_bool(rule.get("mute", True), True)
                logger.info(
                    f"{uid}发送的内容命中图片检测规则「{rule.get('name', label)}」:"
                    f" scene={hit.get('scene')}, label={hit.get('label')}, "
                    f"sub_label={hit.get('sub_label')}, 分值{hit.get('score')}, "
                    f"违规等级{level}级, recall={recall}, mute={mute}, mute_seconds={mute_seconds}"
                )
                await sd(matcher, f"检测到违规图片：{label}，分值{hit.get('score')}，违规等级{level}级")
                await send_pics_ban(
                    bot,
                    event,
                    time=mute_seconds,
                    recall=recall,
                    mute=mute,
                    notice='发送了违规图片，已按群规处理，有异议请联系管理员',
                )
                continue

            if result.get('Suggestion') != 'Pass':
                top_score = _as_int(result.get('Score'), 0)
                top_label = result.get('Label', 'Unknown')
                if top_score <= 90 and top_label == 'Porn':
                    await fi(matcher, '色色不规范，群主两行泪，请群友小心驾驶')
                else:
                    level = await get_user_violation(gid, event.user_id, top_label, event.raw_message, add_=False)
                    logger.info(f"{uid}发送的内容涉及{top_label}, 分值{top_score}, 违规等级{level}级，未命中处置规则")
            continue
        except FinishedException:
            raise
        except Exception as e:
            logger.error(
                f"处理图片审核规则出错: {type(e).__name__}: {e!r}, "
                f"gid={gid}, uid={event.user_id}, result={result}"
            )
            continue

        # ==========================================================
        # 4. 核心逻辑：增加 Politics 检测
        # ==========================================================
        try:
            if result and result['Suggestion'] != 'Pass':
                
                # ------ 高置信度处理 (Score >= 90) ------
                if result['Score'] >= 90:
                    
                    # === 分支 A: 色情 (Porn) ===
                    if result['Label'] == 'Porn':
                        level = await get_user_violation(gid, event.user_id, 'Porn', event.raw_message)
                        await sd(matcher, f"你的违规等级为{level}，色色不规范，群主两行泪，请群友小心驾驶")
                        await send_pics_ban(bot, event, time=time_scop_map[level])
                    
                    # === 分支 B: 政治 (Politics) ===
                    elif result['Label'] == 'Politics':
                        # 注意：这里将违规类型记录为 'Politics'，以便与色图区分统计
                        level = await get_user_violation(gid, event.user_id, 'Politics', event.raw_message)
                        logger.info(f"{uid}发送涉政内容，分值{result['Score']}，违规等级{level}")
                        
                        # 发送警告提示
                        await sd(matcher, f"检测到违规内容，违规等级{level}级")
                        # 执行撤回和禁言
                        await send_pics_ban(bot, event, time=time_scop_map[level])

                    # === 分支 C: 其他高风险内容 (比如恐怖主义等) ===
                    else:
                        # 记录一下，但暂时不自动禁言，防止误判
                        level = (await get_user_violation(gid, event.user_id, result['Label'], event.raw_message, add_=False))
                        logger.info(f"{uid}发送的内容涉及{result['Label']}, 分值{result['Score']}, 违规等级{level}级")

                # ------ 低置信度处理 (Score < 90) ------
                elif result['Score'] <= 90 and result['Label'] == 'Porn':
                    # 仅针对低分值色情提示，低分值政治内容通常误判率高，建议忽略
                    await fi(matcher, '色色不规范，群主两行泪，请群友小心驾驶')
                
                else:
                    # 其他情况 pass
                    pass
                    
        except Exception as e:
            logger.error(f"处理图片审核结果出错: {e}")

async def send_pics_ban(
        bot: Bot,
        event: GroupMessageEvent,
        time: int = None,
        recall: bool = True,
        mute: bool = True,
        notice: str = '发送了违规图片,现对你进行处罚,有异议请联系管理员'):
    gid = event.group_id
    uid = [event.user_id]
    if recall:
        await recall_event_message(bot, event, log_prefix="检测到违规图片", retries=1)
    if not mute:
        return
    baning = mute_sb(bot, gid, lst=uid, time=time)
    async for baned in baning:
        if baned:
            try:
                await baned
                await bot.send(event=event, message=notice, at_sender=True)
                logger.info(f"检测到违规图片，禁言操作成功，用户: {uid[0]}")
            except ActionFailed:
                logger.info('检测到违规图片，但权限不足，禁言失败')
            except NetworkError:
                logger.info('检测到违规图片，但网络超时，禁言失败')
