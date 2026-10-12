"""Наследование параметров в иерархическом конфиге [openai.*].

Подсекция наследует параметры родителя, но не соседние подсекции:
иначе в ChatOpenAI уходят лишние аргументы вроде captcha={...}.
"""

from __future__ import annotations

from types import SimpleNamespace

from hh_applicant_tool.ai.openai import ChatOpenAI
from hh_applicant_tool.tool import HHApplicantTool


def _section(config: dict, section: str) -> dict:
    tool = SimpleNamespace(config=config)
    return HHApplicantTool.get_section_config(tool, section)


CONFIG = {
    "openai": {
        "api_key": "k",
        "base_url": "https://example.test/v1/chat/completions",
        "temperature": 0.3,
        "captcha": {"model": "vision"},
        "chat": {"model": "chat", "temperature": 0.5},
    }
}


def test_child_inherits_parent_params() -> None:
    assert _section(CONFIG, "openai.captcha") == {
        "api_key": "k",
        "base_url": "https://example.test/v1/chat/completions",
        "temperature": 0.3,
        "model": "vision",
    }


def test_child_overrides_parent_params() -> None:
    assert _section(CONFIG, "openai.chat")["temperature"] == 0.5


def test_sibling_sections_do_not_reach_client() -> None:
    ChatOpenAI(**_section(CONFIG, "openai.chat"))


def test_missing_child_falls_back_to_parent_without_children() -> None:
    assert "captcha" not in _section(CONFIG, "openai.reply_chat")
