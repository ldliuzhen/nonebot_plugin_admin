from __future__ import annotations

import asyncio
import base64
import contextvars
import inspect
import logging
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Iterable, Optional

class _StdCompatLogger:
    def __init__(self) -> None:
        self._logger = logging.getLogger("nonebot_plugin_admin")

    def _format(self, message: Any, args: tuple[Any, ...]) -> str:
        text = str(message)
        if args and "{}" in text:
            for arg in args:
                text = text.replace("{}", str(arg), 1)
            return text
        if args:
            try:
                return text % args
            except Exception:
                return " ".join([text, *(str(arg) for arg in args)])
        return text

    def debug(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._format(message, args), **kwargs)

    def info(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._format(message, args), **kwargs)

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._format(message, args), **kwargs)

    def error(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._format(message, args), **kwargs)

    def exception(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self._logger.exception(self._format(message, args), **kwargs)


try:
    from astrbot.api import logger as logger
except Exception:  # pragma: no cover - AstrBot is not installed in local checks.
    logger = _StdCompatLogger()


class ActionFailed(Exception):
    pass


class NetworkError(Exception):
    pass


class FinishedException(Exception):
    pass


class IgnoredException(Exception):
    pass


class RejectedException(Exception):
    pass


class _Config(SimpleNamespace):
    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def dict(self) -> dict[str, Any]:
        return dict(vars(self))


class Driver:
    def __init__(self) -> None:
        self.config = _Config(
            superusers=set(),
            host="127.0.0.1",
            port=8080,
        )
        self._bot_connect_hooks: list[Callable[..., Awaitable[Any]]] = []

    def on_bot_connect(self, func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        self._bot_connect_hooks.append(func)
        return func


driver = Driver()
_context: Any = None
_plugin_dir: Optional[Path] = None
_bots: dict[str, "Bot"] = {}
_loaded_modules = False


def _to_plain_config(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return dict(config)
    try:
        return dict(config)
    except Exception:
        pass
    data: dict[str, Any] = {}
    for name in dir(config):
        if name.startswith("_"):
            continue
        value = getattr(config, name)
        if not callable(value):
            data[name] = value
    return data


def _normalize_superusers(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        parts = value.replace(",", " ").split()
        return {part.strip() for part in parts if part.strip()}
    if isinstance(value, Iterable):
        return {str(item).strip() for item in value if str(item).strip()}
    return {str(value)}


def configure_runtime(context: Any = None, config: Any = None, plugin_dir: Any = None) -> None:
    global _context, _plugin_dir
    _context = context
    if plugin_dir is not None:
        _plugin_dir = Path(plugin_dir)
    data = _to_plain_config(config)
    defaults = {
        "host": "127.0.0.1",
        "port": 8080,
        "send_group_id": [],
        "send_switch_morning": False,
        "send_switch_night": False,
        "send_mode": 2,
        "send_sentence_morning": [],
        "send_sentence_night": [],
        "send_time_morning": "7 0",
        "send_time_night": "22 0",
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    data["superusers"] = _normalize_superusers(data.get("superusers"))
    driver.config = _Config(**data)


async def run_bot_connect_hooks(bot: Optional["Bot"] = None) -> None:
    bot = bot or Bot(context=_context)
    _bots[str(bot.self_id)] = bot
    for hook in list(driver._bot_connect_hooks):
        await _call_with_kwargs(hook, bot=bot)


def get_driver() -> Driver:
    return driver


def get_plugin_config(model: type) -> Any:
    data = driver.config.dict()
    if hasattr(model, "model_validate"):
        return model.model_validate(data)
    return model.parse_obj(data)


def get_bots() -> dict[str, "Bot"]:
    return dict(_bots)


def require(_: str) -> None:
    return None


class PluginMetadata:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def get_available_plugin_names() -> set[str]:
    return set()


class Permission:
    def __init__(self, *checkers: Callable[..., Any], mode: str = "all") -> None:
        self.checkers = list(checkers)
        self.mode = mode

    def __or__(self, other: "Permission") -> "Permission":
        return Permission(self, other, mode="any")

    async def __call__(self, event: "Event") -> bool:
        if not self.checkers:
            return True
        if self.mode == "any":
            for checker in self.checkers:
                try:
                    if bool(await _maybe_await(_call_checker(checker, event=event))):
                        return True
                except Exception:
                    continue
            return False
        for checker in self.checkers:
            try:
                if not bool(await _maybe_await(_call_checker(checker, event=event))):
                    return False
            except Exception:
                return False
        return True


class Rule:
    def __init__(self, *checkers: Callable[..., Any]) -> None:
        self.checkers = list(checkers)

    async def __call__(self, event: "Event", bot: Optional["Bot"] = None, state: Optional[dict] = None) -> bool:
        for checker in self.checkers:
            result = await _maybe_await(_call_checker(checker, event=event, bot=bot, state=state or {}))
            if not result:
                return False
        return True


async def _superuser_checker(event: "Event") -> bool:
    uid = getattr(event, "user_id", None)
    return str(uid) in driver.config.superusers


async def _group_admin_checker(event: "Event") -> bool:
    sender = getattr(event, "sender", None)
    return getattr(sender, "role", None) == "admin"


async def _group_owner_checker(event: "Event") -> bool:
    sender = getattr(event, "sender", None)
    return getattr(sender, "role", None) == "owner"


SUPERUSER = Permission(_superuser_checker)
GROUP_ADMIN = Permission(_group_admin_checker)
GROUP_OWNER = Permission(_group_owner_checker)


class DependsMarker:
    def __init__(self, dependency: Callable[..., Any]) -> None:
        self.dependency = dependency


class CommandArgMarker:
    pass


class ArgMarker:
    def __init__(self, key: Optional[str] = None, as_str: bool = False) -> None:
        self.key = key
        self.as_str = as_str


def Depends(dependency: Callable[..., Any]) -> DependsMarker:
    return DependsMarker(dependency)


def CommandArg() -> CommandArgMarker:
    return CommandArgMarker()


def Arg(key: Optional[str] = None) -> ArgMarker:
    return ArgMarker(key=key, as_str=False)


def ArgStr(key: Optional[str] = None) -> ArgMarker:
    return ArgMarker(key=key, as_str=True)


class MessageSegment:
    def __init__(self, type_: str, data: Optional[dict[str, Any]] = None) -> None:
        self.type = type_
        self.data = data or {}

    @classmethod
    def text(cls, text: Any) -> "MessageSegment":
        return cls("text", {"text": str(text)})

    @classmethod
    def at(cls, user_id: Any) -> "MessageSegment":
        return cls("at", {"qq": str(user_id)})

    @classmethod
    def image(cls, file: Any = None, **kwargs: Any) -> "MessageSegment":
        data = dict(kwargs)
        if file is not None:
            if isinstance(file, bytes):
                data["file"] = "base64://" + base64.b64encode(file).decode("ascii")
            else:
                data["file"] = str(file)
        return cls("image", data)

    def __add__(self, other: Any) -> "Message":
        return Message([self]) + other

    def __radd__(self, other: Any) -> "Message":
        return Message(other) + self

    def __str__(self) -> str:
        if self.type == "text":
            return str(self.data.get("text", ""))
        params = ",".join(f"{key}={value}" for key, value in self.data.items())
        return f"[CQ:{self.type},{params}]" if params else f"[CQ:{self.type}]"

    def to_onebot(self) -> dict[str, Any]:
        return {"type": self.type, "data": dict(self.data)}


class Message(list):
    def __init__(self, value: Any = None) -> None:
        if value is None:
            segments: list[MessageSegment] = []
        elif isinstance(value, Message):
            segments = list(value)
        elif isinstance(value, MessageSegment):
            segments = [value]
        elif isinstance(value, list):
            segments = [self._coerce_segment(item) for item in value]
        else:
            segments = [MessageSegment.text(value)]
        super().__init__(segments)

    @staticmethod
    def _coerce_segment(value: Any) -> MessageSegment:
        if isinstance(value, MessageSegment):
            return value
        if isinstance(value, dict):
            return MessageSegment(value.get("type", "text"), value.get("data") or {})
        return MessageSegment.text(value)

    def __add__(self, other: Any) -> "Message":
        return Message(list(self) + list(Message(other)))

    def __radd__(self, other: Any) -> "Message":
        return Message(other) + self

    def __str__(self) -> str:
        return "".join(str(segment) for segment in self)

    def extract_plain_text(self) -> str:
        return "".join(str(seg.data.get("text", "")) for seg in self if seg.type == "text")

    def to_onebot(self) -> list[dict[str, Any]]:
        return [segment.to_onebot() for segment in self]


class Event:
    post_type = ""

    def __init__(self, **data: Any) -> None:
        for key, value in data.items():
            setattr(self, key, value)
        self.time = getattr(self, "time", int(time.time()))
        self.self_id = str(getattr(self, "self_id", "astrbot"))

    def get_user_id(self) -> str:
        return str(getattr(self, "user_id", ""))

    def get_session_id(self) -> str:
        gid = getattr(self, "group_id", "")
        uid = getattr(self, "user_id", "")
        return f"group:{gid}:{uid}" if gid else f"private:{uid}"

    def is_tome(self) -> bool:
        return False


class MessageEvent(Event):
    post_type = "message"

    def __init__(self, **data: Any) -> None:
        message = data.pop("message", None)
        super().__init__(**data)
        self.message = Message(message)
        self.raw_message = getattr(self, "raw_message", None)
        if self.raw_message is None:
            self.raw_message = self.message.extract_plain_text()
        self.message_id = getattr(self, "message_id", None)
        self.sender = _as_namespace(getattr(self, "sender", {}) or {})
        self.reply = getattr(self, "reply", None)

    def get_plaintext(self) -> str:
        return self.message.extract_plain_text()

    def get_message(self) -> Message:
        return self.message


class GroupMessageEvent(MessageEvent):
    message_type = "group"


class PrivateMessageEvent(MessageEvent):
    message_type = "private"


class GroupRequestEvent(Event):
    post_type = "request"
    request_type = "group"


class NoticeEvent(Event):
    post_type = "notice"


class PokeNotifyEvent(NoticeEvent):
    pass


class HonorNotifyEvent(NoticeEvent):
    pass


class GroupUploadNoticeEvent(NoticeEvent):
    pass


class GroupDecreaseNoticeEvent(NoticeEvent):
    pass


class GroupIncreaseNoticeEvent(NoticeEvent):
    pass


class GroupAdminNoticeEvent(NoticeEvent):
    pass


class LuckyKingNotifyEvent(NoticeEvent):
    pass


class GroupRecallNoticeEvent(NoticeEvent):
    pass


def _as_namespace(data: Any) -> Any:
    if isinstance(data, SimpleNamespace):
        return data
    if isinstance(data, dict):
        return SimpleNamespace(**data)
    return data


def _as_dict(data: Any) -> dict[str, Any]:
    if data is None:
        return {}
    if isinstance(data, dict):
        return dict(data)
    try:
        return dict(data)
    except Exception:
        pass
    result: dict[str, Any] = {}
    for key in dir(data):
        if key.startswith("_"):
            continue
        try:
            value = getattr(data, key)
        except Exception:
            continue
        if not callable(value):
            result[key] = value
    return result


class Bot:
    def __init__(self, astr_event: Any = None, context: Any = None) -> None:
        self._astr_event = astr_event
        self._context = context if context is not None else _context
        message_obj = getattr(astr_event, "message_obj", None)
        self.self_id = str(getattr(message_obj, "self_id", "astrbot"))

    def __getattr__(self, api_name: str) -> Callable[..., Awaitable[Any]]:
        async def caller(**params: Any) -> Any:
            return await self.call_api(api_name, **params)

        return caller

    async def call_api(self, api: Optional[str] = None, **params: Any) -> Any:
        action = api or params.pop("api", None)
        if not action:
            raise ActionFailed("missing api name")
        params = _normalize_api_params(params)
        client = self._get_api_client()
        try:
            if client is not None:
                api_obj = getattr(client, "api", None)
                if api_obj is not None and hasattr(api_obj, "call_action"):
                    return await api_obj.call_action(action, **params)
                if hasattr(client, "call_action"):
                    return await client.call_action(action, **params)
            raise ActionFailed(f"OneBot API client is unavailable: {action}")
        except ActionFailed:
            raise
        except Exception as exc:
            raise ActionFailed(str(exc)) from exc

    def _get_api_client(self) -> Any:
        event_client = getattr(self._astr_event, "bot", None)
        if event_client is not None:
            return event_client
        context = self._context
        if context is None:
            return None
        try:
            manager = getattr(context, "platform_manager", None)
            if manager is not None and hasattr(manager, "get_insts"):
                for platform in manager.get_insts():
                    client = getattr(platform, "get_client", lambda: None)()
                    if client is not None:
                        return client
        except Exception:
            pass
        try:
            if hasattr(context, "get_platform_inst"):
                for platform_id in ("aiocqhttp", "AIOCQHTTP"):
                    try:
                        platform = context.get_platform_inst(platform_id)
                    except Exception:
                        continue
                    client = getattr(platform, "get_client", lambda: None)()
                    if client is not None:
                        return client
        except Exception:
            pass
        return None

    async def send(self, event: Optional[Event] = None, message: Any = None, **kwargs: Any) -> Any:
        target_event = event or getattr(_current.get(None), "event", None)
        if target_event is not None and isinstance(target_event, GroupMessageEvent):
            if kwargs.get("at_sender"):
                message = Message([MessageSegment.at(target_event.user_id)]) + message
            if getattr(target_event, "_astr_event", None) is not None and _message_has_segment(message, "at"):
                return await self.send_group_msg(group_id=target_event.group_id, message=message)
        if target_event is not None and getattr(target_event, "_astr_event", None) is not None:
            return await _send_astr(target_event._astr_event, message)
        if isinstance(target_event, GroupMessageEvent):
            return await self.send_group_msg(group_id=target_event.group_id, message=message)
        if isinstance(target_event, PrivateMessageEvent):
            return await self.send_private_msg(user_id=target_event.user_id, message=message)
        return await self.call_api("send_msg", message=message, **kwargs)

    async def send_group_msg(self, group_id: Any, message: Any) -> Any:
        return await self.call_api("send_group_msg", group_id=int(group_id), message=message)

    async def send_private_msg(self, user_id: Any, message: Any) -> Any:
        return await self.call_api("send_private_msg", user_id=int(user_id), message=message)


def _normalize_api_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    for key in ("message", "messages"):
        if key in normalized:
            normalized[key] = _to_onebot_message(normalized[key])
    return normalized


def _to_onebot_message(message: Any) -> Any:
    if isinstance(message, Message):
        return message.to_onebot()
    if isinstance(message, MessageSegment):
        return [message.to_onebot()]
    if isinstance(message, list):
        return Message(message).to_onebot()
    return str(message)


def _message_has_segment(message: Any, segment_type: str) -> bool:
    try:
        return any(segment.type == segment_type for segment in Message(message))
    except Exception:
        return False


async def _send_astr(astr_event: Any, message: Any) -> Any:
    if message is None:
        return None
    try:
        result = _to_astr_result(astr_event, message)
        send_result = astr_event.send(result)
        return await _maybe_await(send_result)
    except Exception:
        client = getattr(astr_event, "bot", None)
        if client is None:
            raise
        message_obj = getattr(astr_event, "message_obj", None)
        raw = _as_dict(getattr(message_obj, "raw_message", None))
        group_id = getattr(message_obj, "group_id", "") or raw.get("group_id", "")
        sender = getattr(message_obj, "sender", None)
        user_id = getattr(sender, "user_id", "") or raw.get("user_id", "")
        action = "send_group_msg" if group_id else "send_private_msg"
        params = {"message": _to_onebot_message(message)}
        if group_id:
            params["group_id"] = int(group_id)
        elif user_id:
            params["user_id"] = int(user_id)
        return await client.api.call_action(action, **params)


def _to_astr_result(astr_event: Any, message: Any) -> Any:
    chain = _to_astr_chain(message)
    if len(chain) == 1 and chain[0].__class__.__name__ == "Plain":
        text = getattr(chain[0], "text", str(message))
        return astr_event.plain_result(text)
    return astr_event.chain_result(chain)


def _to_astr_chain(message: Any) -> list[Any]:
    try:
        import astrbot.api.message_components as Comp
    except Exception as exc:
        raise ActionFailed("AstrBot message components are unavailable") from exc
    chain: list[Any] = []
    for segment in Message(message):
        if segment.type == "text":
            chain.append(Comp.Plain(str(segment.data.get("text", ""))))
        elif segment.type == "at":
            chain.append(Comp.At(qq=str(segment.data.get("qq") or segment.data.get("user_id"))))
        elif segment.type == "image":
            file_value = segment.data.get("file") or segment.data.get("url")
            chain.append(_astr_image_component(Comp, file_value))
        else:
            chain.append(Comp.Plain(str(segment)))
    return chain


def _astr_image_component(Comp: Any, file_value: Any) -> Any:
    text = str(file_value or "")
    if text.startswith("http://") or text.startswith("https://"):
        return Comp.Image.fromURL(text)
    if text.startswith("base64://"):
        data = base64.b64decode(text[len("base64://"):])
        suffix = ".png"
        if _plugin_dir is not None:
            tmp_dir = _plugin_dir / "resource" / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=tmp_dir)
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        with tmp:
            tmp.write(data)
        return Comp.Image.fromFileSystem(tmp.name)
    return Comp.Image.fromFileSystem(text)


@dataclass
class HandlerSpec:
    func: Callable[..., Any]
    kind: str
    key: Optional[str] = None
    prompt: Optional[str] = None


@dataclass
class PendingSession:
    matcher: "Matcher"
    state: dict[str, Any]
    index: int


@dataclass
class DispatchContext:
    bot: Bot
    event: Event
    astr_event: Any
    matcher: "Matcher"
    state: dict[str, Any]
    command_arg: Message = field(default_factory=Message)
    handled: bool = False
    output: bool = False
    stopped: bool = False


_current: contextvars.ContextVar[Optional[DispatchContext]] = contextvars.ContextVar("nonebot_compat_current", default=None)
_matchers: list["Matcher"] = []
_preprocessors: list[Callable[..., Any]] = []
_pending: dict[str, PendingSession] = {}
_order = 0


class Matcher:
    def __init__(
        self,
        type_: str,
        *,
        commands: Optional[set[str]] = None,
        priority: int = 1,
        block: bool = False,
        permission: Optional[Permission] = None,
        rule: Optional[Any] = None,
        module_name: Optional[str] = None,
    ) -> None:
        global _order
        self.type = type_
        self.commands = commands or set()
        self.priority = priority
        self.block = block
        self.permission = permission
        self.rule = rule
        self.module_name = module_name or _caller_module()
        self.handlers: list[HandlerSpec] = []
        self.order = _order
        self._last_stopped = False
        _order += 1
        _matchers.append(self)

    def handle(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers.append(HandlerSpec(func=func, kind="handle"))
            if not self.module_name:
                self.module_name = getattr(func, "__module__", "")
            return func

        return decorator

    def got(self, key: str, prompt: Optional[str] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers.append(HandlerSpec(func=func, kind="got", key=key, prompt=prompt))
            if not self.module_name:
                self.module_name = getattr(func, "__module__", "")
            return func

        return decorator

    async def send(self, message: Any = None, **kwargs: Any) -> None:
        ctx = _current.get()
        if ctx is None:
            raise ActionFailed("send called without an active event")
        if message is not None:
            await ctx.bot.send(ctx.event, message, **kwargs)
            ctx.output = True

    async def finish(self, message: Any = None, **kwargs: Any) -> None:
        if message is not None:
            await self.send(message, **kwargs)
        raise FinishedException()

    async def reject(self, prompt: Any = None) -> None:
        if prompt is not None:
            await self.send(prompt)
        raise RejectedException()

    def stop_propagation(self) -> None:
        self._last_stopped = True
        ctx = _current.get()
        if ctx is not None:
            ctx.stopped = True


def on_command(
    cmd: str,
    *,
    aliases: Optional[set[str]] = None,
    priority: int = 1,
    block: bool = False,
    permission: Optional[Permission] = None,
    rule: Optional[Any] = None,
    **_: Any,
) -> Matcher:
    commands = {cmd}
    if aliases:
        commands.update(str(alias) for alias in aliases)
    return Matcher(
        "command",
        commands=commands,
        priority=priority,
        block=block,
        permission=permission,
        rule=rule,
        module_name=_caller_module(),
    )


def on_message(*, priority: int = 1, block: bool = False, permission: Optional[Permission] = None, rule: Any = None, **_: Any) -> Matcher:
    return Matcher("message", priority=priority, block=block, permission=permission, rule=rule, module_name=_caller_module())


def on_notice(rule: Any = None, *, priority: int = 1, block: bool = False, permission: Optional[Permission] = None, **_: Any) -> Matcher:
    return Matcher("notice", priority=priority, block=block, permission=permission, rule=rule, module_name=_caller_module())


def on_request(rule: Any = None, *, priority: int = 1, block: bool = False, permission: Optional[Permission] = None, **_: Any) -> Matcher:
    return Matcher("request", priority=priority, block=block, permission=permission, rule=rule, module_name=_caller_module())


def run_preprocessor(func: Callable[..., Any]) -> Callable[..., Any]:
    _preprocessors.append(func)
    return func


def _caller_module() -> str:
    frame = inspect.currentframe()
    if frame is None:
        return ""
    try:
        caller = frame.f_back.f_back
        return caller.f_globals.get("__name__", "") if caller is not None else ""
    finally:
        del frame


async def dispatch_astr_event(astr_event: Any) -> bool:
    event = _event_from_astr(astr_event)
    if event is None:
        return False
    bot = Bot(astr_event=astr_event, context=_context)
    event._astr_event = astr_event
    _bots[str(bot.self_id)] = bot
    session_id = event.get_session_id()
    if session_id in _pending and isinstance(event, MessageEvent):
        return await _resume_pending(session_id, bot, event, astr_event)

    any_handled = False
    for matcher in sorted(_matchers, key=lambda item: (item.priority, item.order)):
        matched, command_arg = await _match(matcher, bot, event)
        if not matched:
            continue
        state = {"_prefix": {"command_arg": command_arg}}
        handled = await _run_matcher(matcher, bot, event, astr_event, state, 0, command_arg)
        any_handled = any_handled or handled
        should_break = matcher.block or matcher._last_stopped
        if should_break:
            break
    return any_handled


async def _resume_pending(session_id: str, bot: Bot, event: Event, astr_event: Any) -> bool:
    pending = _pending.pop(session_id)
    spec = pending.matcher.handlers[pending.index]
    if spec.key:
        pending.state[spec.key] = event.get_message() if isinstance(event, MessageEvent) else Message()
    return await _run_matcher(
        pending.matcher,
        bot,
        event,
        astr_event,
        pending.state,
        pending.index,
        event.get_message() if isinstance(event, MessageEvent) else Message(),
    )


async def _match(matcher: Matcher, bot: Bot, event: Event) -> tuple[bool, Message]:
    if matcher.type in {"command", "message"} and not isinstance(event, MessageEvent):
        return False, Message()
    if matcher.type == "notice" and not isinstance(event, NoticeEvent):
        return False, Message()
    if matcher.type == "request" and not isinstance(event, GroupRequestEvent):
        return False, Message()
    command_arg = Message()
    if matcher.type == "command":
        matched, command_arg = _match_command(matcher, event)
        if not matched:
            return False, Message()
    if matcher.rule is not None:
        rule_ok = await _eval_rule(matcher.rule, bot, event, {})
        if not rule_ok:
            return False, Message()
    if matcher.permission is not None:
        try:
            if not await matcher.permission(event):
                return False, Message()
        except Exception:
            return False, Message()
    return True, command_arg


def _match_command(matcher: Matcher, event: Event) -> tuple[bool, Message]:
    text = str(getattr(event, "raw_message", "") or "")
    stripped = text.lstrip()
    prefixes = ("/",)
    for command in sorted(matcher.commands, key=len, reverse=True):
        candidates: list[str] = []
        if str(command).startswith("/"):
            candidates.append(str(command))
            candidates.append("/" + str(command))
        else:
            candidates.extend(prefix + str(command) for prefix in prefixes)
        for candidate in sorted(set(candidates), key=len, reverse=True):
            if stripped.startswith(candidate):
                rest = stripped[len(candidate):]
                return True, Message(rest.lstrip())
    return False, Message()


async def _eval_rule(rule: Any, bot: Bot, event: Event, state: dict[str, Any]) -> bool:
    if isinstance(rule, Rule):
        return await rule(event, bot=bot, state=state)
    if callable(rule):
        return bool(await _maybe_await(_call_checker(rule, bot=bot, event=event, state=state)))
    return bool(rule)


async def _run_matcher(
    matcher: Matcher,
    bot: Bot,
    event: Event,
    astr_event: Any,
    state: dict[str, Any],
    start_index: int,
    command_arg: Message,
) -> bool:
    ctx = DispatchContext(bot=bot, event=event, astr_event=astr_event, matcher=matcher, state=state, command_arg=command_arg)
    matcher._last_stopped = False
    token = _current.set(ctx)
    session_id = event.get_session_id()
    try:
        try:
            await _run_preprocessors(matcher, bot, event)
        except IgnoredException:
            return False
        index = start_index
        while index < len(matcher.handlers):
            spec = matcher.handlers[index]
            if spec.kind == "got" and spec.key and spec.key not in state:
                if spec.prompt:
                    await matcher.send(spec.prompt)
                _pending[session_id] = PendingSession(matcher=matcher, state=state, index=index)
                return True
            try:
                await _call_handler(spec.func, matcher, bot, event, state, command_arg)
            except RejectedException:
                _pending[session_id] = PendingSession(matcher=matcher, state=state, index=index)
                return True
            except FinishedException:
                _pending.pop(session_id, None)
                return True
            index += 1
        _pending.pop(session_id, None)
        return ctx.output or matcher.type == "command" or ctx.handled
    except Exception as exc:
        log = getattr(logger, "exception", None)
        if callable(log):
            log(f"nonebot compatibility matcher failed: {matcher.module_name}: {exc}")
        else:
            print(f"nonebot compatibility matcher failed: {matcher.module_name}: {exc}")
        return matcher.type == "command"
    finally:
        _current.reset(token)


async def _run_preprocessors(matcher: Matcher, bot: Bot, event: Event) -> None:
    for processor in _preprocessors:
        await _call_with_kwargs(processor, matcher=matcher, bot=bot, event=event)


async def _call_handler(func: Callable[..., Any], matcher: Matcher, bot: Bot, event: Event, state: dict[str, Any], command_arg: Message) -> Any:
    kwargs = await _build_kwargs(func, matcher=matcher, bot=bot, event=event, state=state, command_arg=command_arg)
    return await _maybe_await(func(**kwargs))


async def _build_kwargs(
    func: Callable[..., Any],
    *,
    matcher: Optional[Matcher] = None,
    bot: Optional[Bot] = None,
    event: Optional[Event] = None,
    state: Optional[dict[str, Any]] = None,
    command_arg: Optional[Message] = None,
) -> dict[str, Any]:
    state = state or {}
    command_arg = command_arg or Message()
    signature = inspect.signature(func)
    kwargs: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        default = param.default
        if isinstance(default, DependsMarker):
            kwargs[name] = await _resolve_dependency(default.dependency, matcher, bot, event, state, command_arg)
        elif isinstance(default, CommandArgMarker):
            kwargs[name] = command_arg
        elif isinstance(default, ArgMarker):
            key = default.key or name
            value = state.get(key, Message())
            kwargs[name] = str(value) if default.as_str else value
        elif name == "matcher":
            kwargs[name] = matcher
        elif name == "bot":
            kwargs[name] = bot
        elif name == "event":
            kwargs[name] = event
        elif name == "state":
            kwargs[name] = state
        elif default is not inspect.Parameter.empty:
            kwargs[name] = default
    return kwargs


async def _resolve_dependency(
    dependency: Callable[..., Any],
    matcher: Optional[Matcher],
    bot: Optional[Bot],
    event: Optional[Event],
    state: dict[str, Any],
    command_arg: Message,
) -> Any:
    kwargs = await _build_kwargs(dependency, matcher=matcher, bot=bot, event=event, state=state, command_arg=command_arg)
    return await _maybe_await(dependency(**kwargs))


def _call_checker(checker: Callable[..., Any], **available: Any) -> Any:
    signature = inspect.signature(checker)
    kwargs = {name: available[name] for name in signature.parameters if name in available}
    return checker(**kwargs)


async def _call_with_kwargs(func: Callable[..., Any], **available: Any) -> Any:
    signature = inspect.signature(func)
    kwargs = {name: available[name] for name in signature.parameters if name in available}
    return await _maybe_await(func(**kwargs))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _event_from_astr(astr_event: Any) -> Optional[Event]:
    message_obj = getattr(astr_event, "message_obj", None)
    raw = _as_dict(getattr(message_obj, "raw_message", None))
    if raw.get("post_type") == "request":
        return GroupRequestEvent(**raw)
    if raw.get("post_type") == "notice":
        return _notice_from_raw(raw)
    if message_obj is None and not raw:
        return None
    data = _message_data_from_astr(message_obj, raw, astr_event)
    if data.get("message_type") == "private":
        return PrivateMessageEvent(**data)
    return GroupMessageEvent(**data)


def _message_data_from_astr(message_obj: Any, raw: dict[str, Any], astr_event: Any) -> dict[str, Any]:
    sender_obj = getattr(message_obj, "sender", None)
    sender = _as_dict(raw.get("sender") or sender_obj)
    if "user_id" not in sender:
        sender["user_id"] = getattr(sender_obj, "user_id", None) or getattr(astr_event, "get_sender_id", lambda: "")()
    message = raw.get("message")
    if message is None:
        message = _segments_from_astr(getattr(message_obj, "message", []) or [])
    group_id = raw.get("group_id") or getattr(message_obj, "group_id", "")
    message_type = raw.get("message_type") or ("group" if group_id else "private")
    raw_message = raw.get("raw_message") or getattr(message_obj, "message_str", "") or getattr(astr_event, "message_str", "")
    return {
        "self_id": raw.get("self_id") or getattr(message_obj, "self_id", "astrbot"),
        "message_type": message_type,
        "group_id": int(group_id) if str(group_id).isdigit() else group_id,
        "user_id": int(raw.get("user_id") or sender.get("user_id") or 0),
        "message_id": raw.get("message_id") or getattr(message_obj, "message_id", None),
        "message": message,
        "raw_message": raw_message,
        "sender": sender,
        "reply": _reply_from_raw_or_components(raw, message_obj),
    }


def _segments_from_astr(components: list[Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for component in components:
        name = component.__class__.__name__.lower()
        if name == "plain":
            segments.append({"type": "text", "data": {"text": getattr(component, "text", "")}})
        elif name == "at":
            qq = getattr(component, "qq", None) or getattr(component, "uin", None)
            segments.append({"type": "at", "data": {"qq": str(qq)}})
        elif name == "image":
            url = getattr(component, "url", None) or getattr(component, "file", None) or getattr(component, "path", None)
            segments.append({"type": "image", "data": {"url": url, "file": url}})
        else:
            text = getattr(component, "text", None)
            if text is not None:
                segments.append({"type": "text", "data": {"text": str(text)}})
    return segments


def _reply_from_raw_or_components(raw: dict[str, Any], message_obj: Any) -> Any:
    reply = raw.get("reply")
    if isinstance(reply, dict):
        return SimpleNamespace(**reply)
    for segment in raw.get("message") or []:
        if isinstance(segment, dict) and segment.get("type") == "reply":
            data = segment.get("data") or {}
            return SimpleNamespace(message_id=data.get("id") or data.get("message_id"))
    for component in getattr(message_obj, "message", []) or []:
        if component.__class__.__name__.lower() == "reply":
            return SimpleNamespace(message_id=getattr(component, "id", None) or getattr(component, "message_id", None))
    return None


def _notice_from_raw(raw: dict[str, Any]) -> NoticeEvent:
    notice_type = raw.get("notice_type")
    sub_type = raw.get("sub_type")
    mapping = {
        "group_recall": GroupRecallNoticeEvent,
        "group_upload": GroupUploadNoticeEvent,
        "group_decrease": GroupDecreaseNoticeEvent,
        "group_increase": GroupIncreaseNoticeEvent,
        "group_admin": GroupAdminNoticeEvent,
        "notify": NoticeEvent,
    }
    if notice_type == "notify":
        mapping_notify = {
            "poke": PokeNotifyEvent,
            "honor": HonorNotifyEvent,
            "lucky_king": LuckyKingNotifyEvent,
        }
        return mapping_notify.get(sub_type, NoticeEvent)(**raw)
    return mapping.get(notice_type, NoticeEvent)(**raw)


T_State = dict[str, Any]
