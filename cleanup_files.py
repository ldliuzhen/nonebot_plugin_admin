# python3
# -*- coding: utf-8 -*-
# @File    : cleanup_files.py
import asyncio
import os
from datetime import datetime
from random import randint

from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.adapters.onebot.v11.exception import ActionFailed
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot.adapters import Message

from .path import kick_lock_path
from .utils import fi

PROTECTED_EXTS = {'.sc2replay'}
MAX_DISPLAY = 30
SORT_BY_SIZE = 'size'
SORT_TIME_ASC = 'time_asc'
SORT_TIME_DESC = 'time_desc'
SORT_ALIASES = {
    'time': SORT_TIME_ASC,
    'time_asc': SORT_TIME_ASC,
    'asc': SORT_TIME_ASC,
    'old': SORT_TIME_ASC,
    'oldest': SORT_TIME_ASC,
    '时间': SORT_TIME_ASC,
    '按时间': SORT_TIME_ASC,
    '时间顺序': SORT_TIME_ASC,
    '时间正序': SORT_TIME_ASC,
    '正序': SORT_TIME_ASC,
    '旧到新': SORT_TIME_ASC,
    '由旧到新': SORT_TIME_ASC,
    '最旧': SORT_TIME_ASC,
    '最早': SORT_TIME_ASC,
    '上传正序': SORT_TIME_ASC,
    'time_desc': SORT_TIME_DESC,
    'desc': SORT_TIME_DESC,
    'new': SORT_TIME_DESC,
    'newest': SORT_TIME_DESC,
    '时间倒序': SORT_TIME_DESC,
    '倒序': SORT_TIME_DESC,
    '新到旧': SORT_TIME_DESC,
    '由新到旧': SORT_TIME_DESC,
    '最新': SORT_TIME_DESC,
    '最近': SORT_TIME_DESC,
    '上传倒序': SORT_TIME_DESC,
}


def _parse_args(text: str):
    exts = []
    min_size = 0
    sort_mode = SORT_BY_SIZE
    for part in text.split():
        part = part.strip()
        if not part:
            continue
        normalized = part.lower()
        if normalized in SORT_ALIASES:
            sort_mode = SORT_ALIASES[normalized]
            continue
        if part.startswith('>') and part[1:].replace('.', '', 1).isdigit():
            min_size = float(part[1:]) * 1024 * 1024
        elif part.startswith('.'):
            exts.append(part.lower())
        else:
            return None, None, None, f'无法识别参数「{part}」'
    return exts, min_size, sort_mode, None


def _get_ext(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return ext.lower()


def _format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024**3):.1f}GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024**2):.1f}MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes}B"


PAGE_SIZE = 50
MAX_FOLDER_FILE_COUNT = 10000


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unwrap_response(res: dict) -> dict:
    if isinstance(res, dict) and isinstance(res.get('data'), dict):
        data = res['data']
        if any(k in data for k in (
            'files', 'folders', 'FileList', 'FolderList', 'file_list',
            'folder_list', 'items'
        )):
            return data
    return res or {}


def _normalize_file(item: dict, folder_name: str):
    name = item.get('file_name') or item.get('name') or item.get('fileName')
    if not name:
        return None

    normalized = dict(item)
    normalized['file_name'] = str(name)
    normalized['file_id'] = normalized.get('file_id') or normalized.get('fileId')
    normalized['busid'] = normalized.get(
        'busid', normalized.get('bus_id', normalized.get('busId', 0))
    )
    normalized['file_size'] = _as_int(
        normalized.get('file_size',
                       normalized.get('size',
                                      normalized.get('fileSize', 0)))
    )
    normalized['_folder'] = folder_name
    return normalized


def _normalize_folder(item: dict, parent_folder: str):
    folder_id = item.get('folder_id') or item.get('folderId') or item.get('folder')
    folder_name = (
        item.get('folder_name') or item.get('folderName') or item.get('name')
        or item.get('folder') or folder_id
    )
    if not folder_id and not folder_name:
        return None

    normalized = dict(item)
    normalized['folder_id'] = folder_id
    normalized['folder_name'] = str(folder_name)
    normalized['_parent_folder'] = parent_folder
    return normalized


def _file_size(file: dict) -> int:
    return _as_int(file.get('file_size', file.get('size', file.get('fileSize', 0))))


def _parse_timestamp(value) -> int:
    if value is None or value == '':
        return 0
    try:
        ts = float(value)
    except (TypeError, ValueError):
        try:
            ts = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00')).timestamp()
        except (TypeError, ValueError):
            return 0
    if ts > 10_000_000_000:
        ts = ts / 1000
    if ts < 0:
        return 0
    return int(ts)


def _file_timestamp(file: dict) -> int:
    for key in (
        'upload_time', 'uploadTime', 'uploaded_at', 'uploadedAt',
        'create_time', 'createTime', 'created_at', 'createdAt',
        'modify_time', 'modifyTime', 'last_modify_time', 'lastModifyTime',
        'update_time', 'updateTime', 'updated_at', 'updatedAt',
        'time',
    ):
        ts = _parse_timestamp(file.get(key))
        if ts:
            return ts
    return 0


def _format_file_date(file: dict) -> str:
    ts = _file_timestamp(file)
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d') if ts else '未知'


def _time_asc_key(file: dict):
    ts = _file_timestamp(file)
    return (ts <= 0, ts)


def _time_desc_key(file: dict):
    ts = _file_timestamp(file)
    return (ts <= 0, -ts)


def _sort_files(files: list[dict], sort_mode: str) -> list[dict]:
    if sort_mode == SORT_TIME_ASC:
        return sorted(files, key=_time_asc_key)
    if sort_mode == SORT_TIME_DESC:
        return sorted(files, key=_time_desc_key)
    return sorted(files, key=_file_size, reverse=True)


def _sort_desc(sort_mode: str) -> str:
    if sort_mode == SORT_TIME_ASC:
        return '按时间旧到新'
    if sort_mode == SORT_TIME_DESC:
        return '按时间新到旧'
    return '按大小从大到小'


def _file_key(file: dict):
    return (
        file.get('file_id')
        or file.get('fileId')
        or (
            file.get('_folder'),
            file.get('file_name'),
            file.get('upload_time'),
            _file_size(file),
        )
    )


def _folder_key(folder: dict):
    return (
        folder.get('folder_id')
        or folder.get('folderId')
        or (folder.get('_parent_folder'), folder.get('folder_name'))
    )


def _dedupe_files(files: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for file in files:
        key = _file_key(file)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(file)
    return deduped


def _dedupe_folders(folders: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for folder in folders:
        key = _folder_key(folder)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(folder)
    return deduped


def _extract_files_and_folders(res: dict, folder_name: str):
    res = _unwrap_response(res)
    files = []
    folders = []

    raw_files = (
        res.get('files') or res.get('FileList') or res.get('file_list')
        or res.get('items') or []
    )
    raw_folders = (
        res.get('folders') or res.get('FolderList') or res.get('folder_list')
        or []
    )

    for item in raw_files:
        if not isinstance(item, dict):
            continue
        is_file = any(k in item for k in (
            'file_name', 'fileName', 'file_id', 'fileId', 'busid', 'bus_id',
            'file_size', 'fileSize', 'size'
        ))
        is_folder = any(k in item for k in (
            'folder_name', 'folderName', 'folder_id', 'folderId'
        ))
        if is_folder and not is_file:
            folder = _normalize_folder(item, folder_name)
            if folder:
                folders.append(folder)
        elif is_file or 'name' in item:
            file = _normalize_file(item, folder_name)
            if file:
                files.append(file)

    for item in raw_folders:
        if not isinstance(item, dict):
            continue
        folder = _normalize_folder(item, folder_name)
        if folder:
            folders.append(folder)

    return files, folders


async def _list_folder(bot: Bot, gid: int, folder_id: str,
                       folder_name: str, folder_token: str = '') -> tuple[list[dict], list[dict]]:
    all_files = []
    all_folders = []

    # --- 策略1: NapCat / go-cqhttp 标准群文件 API ---
    try:
        if not folder_id:
            res = await bot.call_api(
                'get_group_root_files',
                group_id=gid,
                file_count=MAX_FOLDER_FILE_COUNT,
            )
        else:
            params_list = [{
                'group_id': gid,
                'folder_id': folder_id,
                'file_count': MAX_FOLDER_FILE_COUNT,
            }]
            if folder_token:
                params_list[0]['folder'] = folder_token
            params_list.append({'group_id': gid, 'folder_id': folder_id})

            last_error = None
            for params in params_list:
                try:
                    res = await bot.call_api('get_group_files_by_folder', **params)
                    break
                except Exception as e:
                    last_error = e
            else:
                raise last_error
        files, folders = _extract_files_and_folders(res, folder_name)
        all_files.extend(files)
        all_folders.extend(folders)
        logger.debug(f"群{gid} 标准群文件API(folder={folder_id or '根'}) "
                     f"取到 {len(files)} 文件, {len(folders)} 文件夹")
    except Exception as e:
        logger.debug(f"群{gid} 标准群文件API(folder={folder_id or '根'}) 失败：{e}")

    # --- 策略2: get_group_file_list + 分页（兼容部分 OneBot 实现） ---
    for fid in ([folder_id] if folder_id else ['', '/']):
        try:
            start = 0
            page_files = []
            page_folders = []
            for _ in range(100):
                await asyncio.sleep(randint(0, 1))
                res = await bot.call_api('get_group_file_list',
                                         group_id=gid,
                                         folder_id=fid,
                                         start_index=start,
                                         file_count=PAGE_SIZE)
                data = _unwrap_response(res)
                raw_items = data.get('files') or data.get('FileList') or []
                files, folders = _extract_files_and_folders(res, folder_name)
                page_files.extend(files)
                page_folders.extend(folders)
                if not raw_items or data.get('is_end', False) or len(raw_items) < PAGE_SIZE:
                    break
                start += len(raw_items)
            if page_files or page_folders:
                all_files.extend(page_files)
                all_folders.extend(page_folders)
                logger.debug(f"群{gid} get_group_file_list(folder={fid}) "
                             f"取到 {len(page_files)} 文件, {len(page_folders)} 文件夹")
                break
        except Exception as e:
            logger.debug(f"群{gid} get_group_file_list(folder={fid}) 失败：{e}")

    # --- 策略2b: get_group_file_list 不带分页参数 ---
    for fid in ([folder_id] if folder_id else ['', '/']):
        try:
            res = await bot.call_api('get_group_file_list',
                                     group_id=gid, folder_id=fid)
            files, folders = _extract_files_and_folders(res, folder_name)
            if files or folders:
                all_files.extend(files)
                all_folders.extend(folders)
                logger.debug(f"群{gid} get_group_file_list(无分页, folder={fid}) "
                             f"取到 {len(files)} 文件, {len(folders)} 文件夹")
                break
        except Exception as e:
            logger.debug(f"群{gid} get_group_file_list(无分页, folder={fid}) 失败：{e}")

    return _dedupe_files(all_files), _dedupe_folders(all_folders)


async def _get_expected_file_count(bot: Bot, gid: int) -> int:
    try:
        res = await bot.call_api('get_group_file_system_info', group_id=gid)
        return _as_int(_unwrap_response(res).get('file_count'))
    except Exception as e:
        logger.debug(f"群{gid} 获取群文件总数失败：{e}")
        return 0


async def _collect_files(bot: Bot, gid: int) -> list[dict]:
    all_files = []
    expected_count = await _get_expected_file_count(bot, gid)

    root_files, root_folders = await _list_folder(bot, gid, '', '/')
    all_files.extend(root_files)

    folders_queue = list(root_folders)
    seen_folders = set()
    while folders_queue:
        folder = folders_queue.pop(0)
        key = _folder_key(folder)
        if key in seen_folders:
            continue
        seen_folders.add(key)

        fid = folder.get('folder_id') or folder.get('folderId')
        fname = folder.get('folder_name', fid)
        if not fid:
            continue

        parent = folder.get('_parent_folder') or '/'
        folder_path = f"{parent.rstrip('/')}/{fname}" if parent != '/' else f"/{fname}"
        folder_token = folder.get('folder') or ''
        sub_files, sub_folders = await _list_folder(
            bot, gid, fid, folder_path, folder_token
        )
        all_files.extend(sub_files)
        folders_queue.extend(_dedupe_folders(sub_folders))

    deduped = _dedupe_files(all_files)
    logger.info(f"群{gid}共扫描到 {len(deduped)} 个文件"
                f"（去重前{len(all_files)}）")
    if expected_count and len(deduped) < expected_count:
        logger.warning(f"群{gid}文件扫描数量少于系统总数："
                       f"{len(deduped)}/{expected_count}")
    return deduped


def _filter_files(files: list[dict], exts: list[str], min_size: float,
                  sort_mode: str = SORT_BY_SIZE) -> list[dict]:
    result = []
    for f in files:
        ext = _get_ext(f.get('file_name', ''))
        if ext in PROTECTED_EXTS:
            continue
        if exts and ext not in exts:
            continue
        if min_size and _file_size(f) < min_size:
            continue
        result.append(f)
    return _sort_files(result, sort_mode)


cleanup_files_cmd = on_command('清理群文件', priority=2, block=True,
                               permission=SUPERUSER | GROUP_ADMIN | GROUP_OWNER)

HELP_TEXT = (
    '【清理群文件】用法：\n'
    '  /清理群文件 >10        — 清理所有 >10MB 的文件\n'
    '  /清理群文件 .exe >5    — 清理 .exe 且 >5MB\n'
    '  /清理群文件 .exe .zip  — 清理所有 .exe 和 .zip\n'
    '  /清理群文件 .exe .zip .apk >5 — 组合使用\n\n'
    '  /清理群文件 >10 时间正序 — 按上传时间从旧到新清理\n'
    '  /清理群文件 .zip 时间倒序 — 按上传时间从新到旧清理\n\n'
    '注意：.SC2Replay 文件始终受保护，不会被清理'
)


@cleanup_files_cmd.handle()
async def handle_first(bot: Bot, event: GroupMessageEvent, matcher: Matcher,
                       state: T_State, args: Message = CommandArg()):
    text = str(args).strip()
    if not text:
        await matcher.finish(HELP_TEXT)

    exts, min_size, sort_mode, err = _parse_args(text)
    if err:
        await matcher.finish(f'{err}\n\n{HELP_TEXT}')

    gid = event.group_id
    lock = kick_lock_path / f"{gid}_files.lock"
    if lock.exists():
        await matcher.finish('当前群正在执行文件清理，请稍后再试')
    lock.touch()
    state['lock_path'] = str(lock)

    await matcher.send('正在扫描群文件，请稍候...')

    all_files = await _collect_files(bot, gid)
    if not all_files:
        lock.unlink(missing_ok=True)
        await matcher.finish('未获取到任何群文件')

    to_delete = _filter_files(all_files, exts, min_size, sort_mode)
    if not to_delete:
        lock.unlink(missing_ok=True)
        cond = []
        if exts:
            cond.append(f'格式：{" ".join(exts)}')
        if min_size:
            cond.append(f'大于{_format_size(int(min_size))}')
        if sort_mode != SORT_BY_SIZE:
            cond.append(_sort_desc(sort_mode))
        await matcher.finish(f'没有找到符合条件的文件（{", ".join(cond) if cond else "无限制"}）')

    total_size = sum(_file_size(f) for f in to_delete)
    lines = [f'找到 {len(to_delete)} 个文件，共 {_format_size(total_size)}（{_sort_desc(sort_mode)}）：\n']
    for i, f in enumerate(to_delete[:MAX_DISPLAY], 1):
        name = f['file_name']
        size = _format_size(_file_size(f))
        folder = f.get('_folder', '/')
        date_str = _format_file_date(f)
        lines.append(f"{i}. [{folder}] {name} ({size}) {date_str}")
    if len(to_delete) > MAX_DISPLAY:
        lines.append(f'\n...还有 {len(to_delete) - MAX_DISPLAY} 个文件未显示')
    lines.append(f'\n回复「确认」执行清理，回复其他内容取消')

    state['delete_list'] = [{
        'file_id': f['file_id'],
        'busid': f.get('busid', f.get('bus_id', 0)),
        'file_name': f['file_name'],
    } for f in to_delete if f.get('file_id')]
    await matcher.send('\n'.join(lines))


@cleanup_files_cmd.got('confirm')
async def handle_confirm(bot: Bot, event: GroupMessageEvent,
                         matcher: Matcher, state: T_State):
    from pathlib import Path
    confirm = str(state['confirm']).strip()
    lock = Path(state.get('lock_path', ''))

    if confirm != '确认':
        lock.unlink(missing_ok=True)
        await matcher.finish('已取消清理操作')

    delete_list = state.get('delete_list', [])
    if not delete_list:
        lock.unlink(missing_ok=True)
        await matcher.finish('没有需要清理的文件')

    await matcher.send(f'开始清理 {len(delete_list)} 个文件，请稍候...')

    success = 0
    fail = 0
    gid = event.group_id
    for item in delete_list:
        try:
            await asyncio.sleep(randint(1, 3))
            try:
                await bot.call_api('delete_group_file',
                                   group_id=gid,
                                   file_id=item['file_id'])
            except Exception:
                try:
                    await bot.call_api('delete_group_file',
                                       group_id=gid,
                                       file_id=item['file_id'],
                                       busid=item['busid'])
                except Exception:
                    await bot.call_api('del_group_file',
                                       group_id=gid,
                                       file_id=item['file_id'])
            success += 1
            logger.info(f"清理群文件：群{gid} 删除 {item['file_name']}")
        except Exception as e:
            fail += 1
            logger.error(f"清理群文件：群{gid} 删除 {item['file_name']} 失败：{e}")

    lock.unlink(missing_ok=True)

    result = f'清理完成！成功删除 {success} 个文件'
    if fail:
        result += f'，失败 {fail} 个'
    await fi(matcher, result)
