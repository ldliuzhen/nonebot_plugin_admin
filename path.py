# python3
# -*- coding: utf-8 -*-
# @Time    : 2022/2/24 22:23
# @Author  : yzyyz
# @Email   :  youzyyz1384@qq.com
# @File    : path.py
# @Software: PyCharm
from pathlib import Path
from nonebot import get_driver
from .util.time_util import *

# FIXME 群配置文件目前都以配置文件的类型分文件夹，而不是以群分文件夹，后者是不是会更好，但是目前懒得改了
base_path = Path(__file__).resolve().parent
config_path = base_path / 'config'
config_admin = config_path / 'admin.json'
config_group_admin = config_path / 'group_admin.json'
word_path = config_path / 'word_config.txt'
words_contents_path = config_path / 'words'
res_path = base_path / 'resource'
re_img_path = res_path / 'imgs'
ttf_name = res_path / 'msyhblod.ttf'
limit_word_path = config_path / '违禁词.txt'
switcher_path = config_path / '开关.json'
template_path = config_path / 'template'
stop_words_path = config_path / 'stop_words'
wordcloud_bg_path = config_path / 'wordcloud_bg'
user_violation_info_path = config_path / '群内用户违规信息'
group_message_data_path = config_path / '群消息数据'
error_path = config_path / 'admin插件错误数据'
broadcast_avoid_path = config_path / '广播排除群聊.json'
ttf_path = res_path / 'msyhblod.ttf'
summary_path = config_path / 'summary'
kick_lock_path = config_path / 'kick_lock'
appr_bk = config_path / '加群验证信息黑名单.json'
pm_bindings_path = config_path / 'pm_bindings.json'
auto_reply_path = config_path / '自动回复.json'
deputy_perms_path = config_path / '分管权限.json'
wc_block_path = config_path / '词云屏蔽.json'
group_alias_path = config_path / '群别名.json'

admin_funcs = {
    'admin': ['管理', '踢', '禁', '改', '基础群管'],
    'requests': ['审批', '加群审批', '加群', '自动审批'],
    'wordcloud': ['群词云', '词云', 'wordcloud'],
    'auto_ban': ['违禁词', '违禁词检测'],
    'img_check': ['图片检测', '图片鉴黄', '涩图检测', '色图检测'],
    'word_analyze': ['消息记录', '群消息记录', '发言记录'],
    'group_msg': ['早安晚安', '早安', '晚安'],
    'broadcast': ['广播消息', '群广播', '广播'],
    'particular_e_notice': ['事件通知', '变动通知', '事件提醒'],
    'group_recall': ['防撤回', '防止撤回'],
    'cleanup': ['自动清理', '清理不活跃', '不活跃清理'],
    'auto_reply': ['自动回复', '关键词回复', '智能回复'],
    'cleanup_files': ['清理群文件', '文件清理'],
}
# TODO 后续在这里对功能加 {‘default': True} 以便于初始化时自动设置开关状态
funcs_name_cn = ['基础群管', '加群审批', '群词云', '违禁词检测', '图片检测']


GROUP_MUTE_MAX_TIME = 12 * TIME_HOUR  # 12小时（43200秒）
TOTAL_LEVELS = 999  # 0-998 共999个等级

# 二次缩放：等级0=1秒，等级998=43200秒（12小时）
# 公式: time = max(1, round((level/998)^2 * 43200))
time_scop_map = {
    n: max(1, round((n / (TOTAL_LEVELS - 1)) ** 2 * GROUP_MUTE_MAX_TIME))
    for n in range(TOTAL_LEVELS)
}
time_scop_map[0] = 1
time_scop_map[TOTAL_LEVELS - 1] = GROUP_MUTE_MAX_TIME

localhost = "http://" + str(get_driver().config.host) + ":" + str(get_driver().config.port)
