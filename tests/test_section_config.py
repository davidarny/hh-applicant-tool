"""Наследование параметров в конфиге [openai.*].

С 2.1.0 общие параметры лежат в [openai.default], а секции вроде
[openai.chat] их переопределяют. В ChatOpenAI уходят только известные ему
аргументы, и ключ API в их числе: без него клиента не создать.
"""

from __future__ import annotations

from pathlib import Path

import tomli_w

from hh_applicant_tool.ai.openai import ChatOpenAI
from hh_applicant_tool.tool import HHApplicantTool

CONFIG = {
    "openai": {
        "default": {
            "api_key": "k",
            "base_url": "https://example.test/v1",
            "temperature": 0.3,
            "proxy_url": "socks5://127.0.0.1:1080",
        },
        "captcha": {"model": "vision"},
        "chat": {"model": "chat", "temperature": 0.5},
    }
}


def _tool(tmp_path: Path) -> HHApplicantTool:
    (tmp_path / "config.toml").write_text(tomli_w.dumps(CONFIG))
    return HHApplicantTool(config_dir=tmp_path, profile_id=".")


def test_section_inherits_default_params(tmp_path: Path) -> None:
    assert _tool(tmp_path).get_openai_settings("openai.captcha") == {
        "api_key": "k",
        "base_url": "https://example.test/v1",
        "temperature": 0.3,
        "proxy_url": "socks5://127.0.0.1:1080",
        "model": "vision",
    }


def test_section_overrides_default_params(tmp_path: Path) -> None:
    settings = _tool(tmp_path).get_openai_settings("openai.chat")

    assert settings["temperature"] == 0.5


def test_settings_build_client(tmp_path: Path) -> None:
    """В 2.1.0 ключ отфильтровывался, и ChatOpenAI падал с TypeError."""
    client = ChatOpenAI(**_tool(tmp_path).get_openai_settings("openai.chat"))

    assert client.api_key == "k"
    assert client.model == "chat"
