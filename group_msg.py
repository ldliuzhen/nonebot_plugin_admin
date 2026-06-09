"""
额外依赖pip install nonebot_plugin_apscheduler
定时推送群消息需要在.evn中配置:
send_group_id = ["xxx", "xxx"]                    # 必填 群号
send_switch_morning = False                       # 选填 True/False 默认开启 早上消息推送是否开启
send_switch_night = False                         # 选填 True/False 默认开启 晚上消息推送是否开启
send_mode = 1                                     # 选填 默认模式2 模式1发送自定义句子，模式2随机调用一句
send_sentence_morning = ["句子1", "句子2", "..."]  # 如果是模式1 此项必填，早上随机发送该字段中的一句
send_sentence_night = ["句子1", "句子2", "..."]   # 如果是模式1 此项必填，晚上随机发送该字段中的一句
send_time_morning = "8 0"                          # 选填 早上发送时间默认为7:00
send_time_night = "23 0"                          # 选填 晚上发送时间默认为22:00              
"""
# FIXME 此功能为用户PR，目前先用配置形式，后续修改为动态配置
import asyncio
import json
import random
import urllib.request

from nonebot import require, get_bots, get_driver
from nonebot.log import logger
from nonebot.plugin import get_available_plugin_names

from .func_hook import check_func_status


def _config_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ('0', 'false', 'no', 'off', '关', '关闭')
    return bool(value)


def _config_group_ids(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, int)):
        return [gid for gid in str(value).replace(',', ' ').split() if gid]
    return [str(gid) for gid in value if str(gid).strip()]

# 获取QQ群号
try:
    send_group_id = _config_group_ids(get_driver().config.send_group_id)  # <-填写需要收发的QQ群号,利用for循环遍历发送
except Exception as e:
    send_group_id = []
    logger.error(f"ValueError: {e}")
    logger.error('请配置send_group_id')

# 开关 默认全开
try:
    send_switch_morning = _config_bool(get_driver().config.send_switch_morning)
except(AttributeError, AssertionError):
    send_switch_morning = True
try:
    send_switch_night = _config_bool(get_driver().config.send_switch_night)
except(AttributeError, AssertionError):
    send_switch_night = True

# 获取模式 默认模式2 如果是模式1就读取自定义句子，模式2使用API
try:
    send_mode = int(get_driver().config.send_mode)
except(AttributeError, AssertionError):
    send_mode = 2
except (TypeError, ValueError):
    send_mode = 2
if send_mode == 1:
    send_sentence_morning = get_driver().config.send_sentence_morning
    send_sentence_night = get_driver().config.send_sentence_night

# 获取自定义时间，默认早上七点，晚上十点
try:
    send_time_morning = get_driver().config.send_time_morning
    send_time_night = get_driver().config.send_time_night
    assert send_time_morning is not None
except(AttributeError, AssertionError):
    send_time_morning = '7 0'
    send_time_night = '22 0'
m_hour, m_minute = send_time_morning.split(' ')
n_hour, n_minute = send_time_night.split(' ')

# 随机一言API
def hitokoto():
    url = "https://v1.hitokoto.cn?c=a&c=b&c=c&c=d&c=h"
    with urllib.request.urlopen(url, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    msg = data['hitokoto']
    add = ""
    if works := data['from']:
        add += f"《{works}》"
    if from_who := data['from_who']:
        add += f"{from_who}"
    if add:
        msg += f"\n——{add}"
    return msg

async def send_morning():
    # 如果False直接退出函数
    if not send_switch_morning:
        logger.info('send_morning()关闭，跳出函数')
        return
    if not send_group_id:
        logger.info('send_group_id未配置，跳过早安推送')
        return
    sendSuccess = False
    while not sendSuccess:
        try:
            await asyncio.sleep(random.randint(1, 10))
            # await get_bot().send_private_msg(user_id = fire_user_id, message = "🌞早，又是元气满满的一天")  #
            # 当未连接到onebot.v11协议端时会抛出异常
            bots = get_bots()
            for bot in bots.values():
                for gid in send_group_id:
                    if await check_func_status('group_msg', gid):
                        if send_mode == 1:
                            try:
                                await bot.send_group_msg(group_id=gid,
                                                         message=f"{random.choice(send_sentence_morning)}")
                            except Exception:
                                # 这个机器人没有加这个群
                                pass
                        if send_mode == 2:
                            try:
                                await bot.send_group_msg(group_id=gid, message=hitokoto())
                            except Exception:
                                # 这个机器人没有加这个群
                                pass
                logger.info('群聊推送消息')
                sendSuccess = True
        except ValueError as E:
            logger.error(f"ValueError: {E}")
            logger.error('群聊推送消息插件获取bot失败，1s后重试')
            await asyncio.sleep(1)  # 重试前时延，防止阻塞

async def send_night():
    # 如果False直接退出函数
    if not send_switch_night:
        logger.info('send_night()关闭，跳出函数')
        return
    if not send_group_id:
        logger.info('send_group_id未配置，跳过晚安推送')
        return
    sendSuccess = False
    while not sendSuccess:
        try:
            await asyncio.sleep(random.randint(1, 10))
            # await get_bot().send_private_msg(user_id = fire_user_id, message = "🌛今天续火花了么，晚安啦")  #
            # 当未连接到onebot.v11协议端时会抛出异常
            bots = get_bots()
            for bot in bots.values():
                for gid in send_group_id:
                    if await check_func_status('group_msg', gid):
                        if send_mode == 1:
                            try:
                                await bot.send_group_msg(group_id=gid, message=f"{random.choice(send_sentence_night)}")
                            except Exception:
                                # 这个机器人没有加这个群
                                pass
                        if send_mode == 2:
                            try:
                                await bot.send_group_msg(group_id=gid, message=hitokoto())
                            except Exception:
                                # 这个机器人没有加这个群
                                pass
                logger.info('群聊推送消息')
                sendSuccess = True
        except ValueError as E:
            logger.error(f"ValueError: {E}")
            logger.error('群聊推送消息插件获取bot失败，1s后重试')
            await asyncio.sleep(1)  # 重试前时延，防止阻塞

try:
    assert 'nonebot_plugin_apscheduler' in get_available_plugin_names()
    require('nonebot_plugin_apscheduler')
    from nonebot_plugin_apscheduler import scheduler
    logger.info('已检测到软依赖nonebot_plugin_apscheduler，开启定时任务功能')
    scheduler.add_job(send_morning, 'cron', hour=m_hour, minute=m_minute,
                      id='send_morning', replace_existing=True)  # 早上推送
    scheduler.add_job(send_night, 'cron', hour=n_hour, minute=n_minute,
                      id='send_night', replace_existing=True)  # 晚上推送
except:
    logger.error('未检测到软依赖nonebot_plugin_apscheduler，禁用定时任务功能')
