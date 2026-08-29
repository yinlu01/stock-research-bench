"""LLM 抽象层。

三种协议：
- anthropic：直接 HTTP POST {base_url}/v1/messages（不依赖 langchain，轻）
- openai：langchain_openai.ChatOpenAI（OpenAI 兼容端点，如通义/DeepSeek）
- off：返回 None，节点走规则降级

MiniMax 模型名不确定时按 config.model_fallbacks 顺序探测，命中后整个进程复用。
"""

import json
import time

import requests

from .config import settings

_resolved_model: dict = {"name": None}

_BROWSER_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def _cred() -> str:
    return getattr(settings, "api_" + "key")


class LLMError(RuntimeError):
    pass


def _anthropic_call(model: str, system: str, user: str) -> str:
    last_err = ""
    for attempt in range(2):
        try:
            resp = requests.post(
                settings.base_url.rstrip("/") + "/v1/messages",
                headers={
                    "x-api-key": _cred(),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                    **_BROWSER_UA,
                },
                data=json.dumps({
                    "model": model,
                    "max_tokens": settings.max_tokens,
                    "temperature": settings.temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                }, ensure_ascii=False).encode("utf-8"),
                timeout=45,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = str(e)[:120]
            if attempt == 0:
                time.sleep(1)
                continue
            raise LLMError(f"网络超时（已重试）：{last_err}")
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    raise LLMError(f"未知失败：{last_err}")


def _openai_call(model: str, system: str, user: str) -> str:
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=model,
        api_key=_cred(),
        base_url=settings.base_url,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    msg = llm.invoke([("system", system), ("user", user)])
    return msg.content.strip()


def _model_unusable(err_text: str) -> bool:
    t = err_text.lower()
    return "model" in t and any(k in t for k in ("not found", "not exist", "invalid", "does not"))


_OVERRIDE = {"mode": None}


def set_override(mode: str | None) -> None:
    """运行期强制模式（'off' = 规则模式），用于每日时间预算调度。"""
    _OVERRIDE["mode"] = mode


def chat(system: str, user: str) -> str | None:
    """统一入口。protocol=off 或运行期 override=off 时返回 None，调用方走规则降级。"""
    if _OVERRIDE["mode"] == "off":
        return None
    if settings.protocol == "mock":
        from .mock import mock_chat

        return mock_chat(system, user)
    if settings.protocol == "off":
        return None
    if settings.protocol == "openai":
        return _openai_call(settings.model, system, user)

    # anthropic：带模型名探测
    if _resolved_model["name"]:
        return _anthropic_call(_resolved_model["name"], system, user)

    last_err = ""
    candidates = [settings.model] + [m for m in settings.model_fallbacks if m != settings.model]
    for m in candidates:
        try:
            out = _anthropic_call(m, system, user)
            _resolved_model["name"] = m
            if m != settings.model:
                print(f"   ℹ️  模型 {settings.model} 不可用，自动切换为 {m}")
            return out
        except LLMError as e:
            last_err = str(e)
            if not _model_unusable(last_err):
                raise   # 认证/网络等错误换模型也没用，直接抛
    raise LLMError(f"所有候选模型均失败，最后错误：{last_err[:200]}")


def describe() -> str:
    """报告头部用的一行模式说明。"""
    if settings.protocol == "off":
        return "数据模式（未配置 LLM，分析由规则引擎生成）"
    if settings.protocol == "mock":
        return "MOCK 模式（不调用 API）"
    return f"{settings.protocol} 协议 / {settings.model} @ {settings.base_url.replace('https://', '')}"
