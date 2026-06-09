from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

_PLUGIN_DIR = Path(__file__).resolve().parent
_PLUGIN_PARENT = _PLUGIN_DIR.parent

for _path in (str(_PLUGIN_DIR), str(_PLUGIN_PARENT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from nonebot import configure_runtime, dispatch_astr_event, run_bot_connect_hooks
from nonebot._compat import Bot, logger

_PIP_MIRRORS = [
    (
        "腾讯云 PyPI 镜像",
        "https://mirrors.cloud.tencent.com/pypi/simple",
        "mirrors.cloud.tencent.com",
    ),
    (
        "清华大学 PyPI 镜像",
        "https://pypi.tuna.tsinghua.edu.cn/simple",
        "pypi.tuna.tsinghua.edu.cn",
    ),
]

_DEPENDENCIES = {
    "httpx": "httpx",
    "pydantic": "pydantic",
    "jieba": "jieba",
    "wordcloud": "wordcloud",
    "imageio": "imageio",
    "PIL": "pillow",
    "jinja2": "jinja2",
    "pyppeteer": "pyppeteer",
    "tencentcloud": "tencentcloud-sdk-python",
    "fuzzyfinder": "fuzzyfinder",
}

try:
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.star import Context, Star, register
except Exception:  # pragma: no cover - only used when AstrBot is installed.
    AstrMessageEvent = Any
    Context = Any

    class Star:  # type: ignore[no-redef]
        def __init__(self, context: Any = None) -> None:
            self.context = context

    class _Filter:
        class EventMessageType:
            ALL = "all"

        @staticmethod
        def event_message_type(*_: Any, **__: Any):
            return lambda func: func

    filter = _Filter()  # type: ignore[assignment]

    def register(*_: Any, **__: Any):
        return lambda cls: cls


def _config_to_dict(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    try:
        return dict(config)
    except Exception:
        pass
    data: dict[str, Any] = {}
    for key in dir(config):
        if key.startswith("_"):
            continue
        value = getattr(config, key)
        if not callable(value):
            data[key] = value
    return data


def _auto_install_dependencies(config: dict[str, Any]) -> None:
    enabled = config.get("auto_install_deps", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {"0", "false", "no", "off", "关", "关闭"}
    if not enabled:
        return

    missing = [
        package
        for import_name, package in _DEPENDENCIES.items()
        if importlib.util.find_spec(import_name) is None
    ]
    if not missing:
        return

    logger.info(f"检测到缺少依赖，准备自动安装: {', '.join(missing)}")
    if _install_packages(missing):
        return

    logger.error(
        "依赖自动安装失败。插件会继续加载，但部分功能可能不可用；"
        f"请手动安装: {sys.executable} -m pip install {' '.join(missing)}"
    )


def _install_packages(packages: list[str]) -> bool:
    for mirror_name, index_url, trusted_host in _PIP_MIRRORS:
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--index-url",
            index_url,
            "--trusted-host",
            trusted_host,
            *packages,
        ]
        logger.info(f"正在使用{mirror_name}安装依赖: {' '.join(packages)}")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(_PLUGIN_DIR),
                text=True,
                capture_output=True,
                timeout=600,
            )
        except Exception as exc:
            logger.error(f"使用{mirror_name}安装依赖时启动 pip 失败: {exc}")
            continue
        if result.returncode == 0:
            logger.info(f"依赖安装完成，使用源: {mirror_name}")
            importlib.invalidate_caches()
            return True
        stderr = (result.stderr or result.stdout or "").strip()
        logger.error(f"使用{mirror_name}安装依赖失败: {stderr[-1200:]}")
    return False


@register(
    "nonebot_plugin_admin",
    "ldliuzhen",
    "A migrated AstrBot wrapper for the original NoneBot group admin plugin.",
    "0.3.0-astrbot",
)
class NoneBotAdminPlugin(Star):
    def __init__(self, context: Context, config: Optional[Any] = None) -> None:
        super().__init__(context)
        self.context = context
        self.config = _config_to_dict(config)
        self._legacy_loaded = False
        self._connect_hooks_done = False
        configure_runtime(context=context, config=self.config, plugin_dir=_PLUGIN_DIR)
        _auto_install_dependencies(self.config)
        self._load_legacy_package()

    def _load_legacy_package(self) -> None:
        if self._legacy_loaded:
            return
        package_name = _PLUGIN_DIR.name
        importlib.import_module(package_name)
        legacy_modules = [
            "approve",
            "config",
            "path",
            "utils",
            "admin_role",
            "message",
            "switcher",
            "admin",
            "auto_ban",
            "auto_reply",
            "broadcast",
            "cleanup",
            "cleanup_files",
            "cross_group",
            "func_hook",
            "group_msg",
            "group_request_verify",
            "group_recall",
            "help_cmd",
            "img_check",
            "kick_member_by_rule",
            "notice",
            "particular_e_notice",
            "private_cmd",
            "requests",
            "request_manual",
            "word_analyze",
            "wordcloud",
            "util",
        ]
        for module_name in legacy_modules:
            importlib.import_module(f"{package_name}.{module_name}")
        self._legacy_loaded = True

    async def _ensure_started(self, event: Optional[AstrMessageEvent] = None) -> None:
        if self._connect_hooks_done:
            return
        bot = Bot(astr_event=event, context=self.context)
        await run_bot_connect_hooks(bot)
        self._connect_hooks_done = True

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_any_message(self, event: AstrMessageEvent):
        await self._ensure_started(event)
        handled = await dispatch_astr_event(event)
        if handled:
            self._stop_astr_event(event)

    @staticmethod
    def _stop_astr_event(event: AstrMessageEvent) -> None:
        for method_name in ("should_call_llm", "set_call_llm"):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    method(False)
                except Exception:
                    pass
        for method_name in ("stop_event", "stop_propagation"):
            method = getattr(event, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass

    async def terminate(self) -> None:
        return None
