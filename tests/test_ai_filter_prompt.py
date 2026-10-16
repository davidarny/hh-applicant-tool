"""Промпты AI-фильтра и сопроводительных писем в apply-vacancies.

С 2.2 промпты задаются только в конфиге: системные - в секциях
[openai.cover_letter] и [openai.vacancy_filter], шаблоны с %(name)s - в
[general]. В 2.2 фильтр получал опечатку system_propmt, на которой
ChatOpenAI падал с TypeError.
"""

from __future__ import annotations

from argparse import ArgumentParser
from unittest.mock import MagicMock

from hh_applicant_tool.ai.openai import ChatOpenAI
from hh_applicant_tool.operations.apply_vacancies import (
    DEFAULT_AI_FILTER_SYSTEM_PROMPT,
    DEFAULT_COVER_LETTER_SYSTEM_PROMPT,
    Operation,
)

from .test_apply_limit_shutdown import _make_operation


def _run(
    general: dict | None = None,
    sections: dict[str, dict] | None = None,
) -> dict:
    """Запускает run() с --ai-filter и настоящим ChatOpenAI, без рассылки."""
    op = Operation()
    parser = ArgumentParser()
    op.setup_parser(parser)
    args = parser.parse_args(["--ai-filter"])
    args.use_ai = True

    tool = MagicMock()
    tool.general_config = general or {}
    tool.get_openai_settings.side_effect = lambda section: {
        "api_key": "k",
        "base_url": "https://example.test/v1",
        "model": section,
        **(sections or {}).get(section, {}),
    }
    tool.get_ai_client.side_effect = lambda **kw: ChatOpenAI(**kw)
    op._apply_vacancies = MagicMock()  # type: ignore[method-assign]

    op.run(tool, args)

    return {
        "cover_letter": op.cover_letter_ai,
        "vacancy_filter": op.vacancy_filter_ai,
        "op": op,
    }


def test_system_prompts_from_config_reach_clients() -> None:
    """Каждый клиент получает системный промпт из своей секции."""
    clients = _run(
        sections={
            "openai.cover_letter": {"system_prompt": "Пиши коротко"},
            "openai.vacancy_filter": {"system_prompt": "Только Python"},
        }
    )

    assert clients["cover_letter"].system_prompt == "Пиши коротко"
    assert clients["vacancy_filter"].system_prompt == "Только Python"


def test_default_system_prompts() -> None:
    clients = _run()

    assert clients["cover_letter"].system_prompt == DEFAULT_COVER_LETTER_SYSTEM_PROMPT
    assert clients["vacancy_filter"].system_prompt == DEFAULT_AI_FILTER_SYSTEM_PROMPT


def test_prompt_templates_from_general_config() -> None:
    op = _run(
        general={
            "cover_letter_prompt": "Письмо на %(vacancy_name)s",
            "ai_filter_prompt": "Подходит ли %(vacancy_name)s?",
        }
    )["op"]

    assert op.cover_letter_prompt == "Письмо на %(vacancy_name)s"
    assert op.ai_filter_prompt == "Подходит ли %(vacancy_name)s?"


def test_default_prompt_templates_without_config() -> None:
    op = _run()["op"]

    assert "%(vacancy_name)s" in op.cover_letter_prompt
    assert "%(vacancy_description)s" in op.ai_filter_prompt


def test_filter_prompt_has_vacancy_description_and_skills() -> None:
    """Шаблон фильтра получает описание и ключевые навыки вакансии."""
    op = _make_operation()
    op.ai_filter_prompt = "%(vacancy_name)s | %(vacancy_key_skills)s | %(vacancy_description)s"
    op.tool.api_client.get.return_value = {
        "description": "<p>React и TypeScript</p>",
        "key_skills": [{"name": "React"}, {"name": "TypeScript"}],
    }
    op.vacancy_filter_ai = MagicMock()
    op.vacancy_filter_ai.complete.return_value = "Нет."

    suitable = op._is_vacancy_suitable(
        {"id": "1", "name": "Frontend"}, {"vacancy_name": "Frontend"}
    )

    assert suitable is False
    prompt = op.vacancy_filter_ai.complete.call_args.args[0]
    assert prompt == "Frontend | React, TypeScript | React и TypeScript"


def test_filter_client_sends_system_prompt_in_openai_payload() -> None:
    """Scenario: the filter prompt is present in the outbound AI request.

    Given a ChatOpenAI client configured with a filter system prompt
    When it completes a vacancy suitability request
    Then the outbound messages contain that prompt as the system message
    """
    session = MagicMock()
    response = session.post.return_value
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": "true"}}]}
    client = ChatOpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        system_prompt="Only accept Python roles",
        session=session,
    )

    assert client.complete("Вакансия: Python developer") == "true"

    # С 2.3 base_url без /chat/completions, путь клиент добавляет сам
    assert session.post.call_args.args[0] == (
        "https://example.test/v1/chat/completions"
    )
    payload = session.post.call_args.kwargs["json"]
    assert payload["messages"] == [
        {"role": "system", "content": "Only accept Python roles"},
        {"role": "user", "content": "Вакансия: Python developer"},
    ]
