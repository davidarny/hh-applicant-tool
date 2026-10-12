from __future__ import annotations

from argparse import ArgumentParser
from types import SimpleNamespace
from unittest.mock import MagicMock

from hh_applicant_tool.ai.openai import ChatOpenAI
from hh_applicant_tool.operations.apply_vacancies import Operation


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "true"}}]}


def _make_operation() -> Operation:
    operation = Operation()
    operation._args = SimpleNamespace(
        ai_rate_limit=0,
        send_email=False,
        skip_tests=False,
    )
    operation.tool = MagicMock()
    operation.tool.storage = MagicMock()
    operation.ai_filter = "heavy"
    operation.ai_filter_prompt = None
    operation.vacancy_filter_ai = None
    operation.cover_letter_ai = None
    operation.max_responses = 0
    operation.dry_run = True
    operation.excluded_filter = None
    operation._get_vacancies = lambda resume_id=None, resume_title="": iter(())
    operation._analyze_resume_heavy = lambda resume: "resume details"
    return operation


def test_parser_accepts_custom_mode_with_prompt() -> None:
    """Scenario: the UI prompt is parsed as an AI-filter option.

    Given a custom AI filter with a filter prompt
    When the apply parser reads the parameters
    Then it stores the prompt separately from the cover-letter prompt
    """
    operation = Operation()
    parser = ArgumentParser()
    operation.setup_parser(parser)

    args = parser.parse_args(
        ["--ai-filter", "custom", "--ai-filter-prompt", "Only accept Python roles"]
    )

    assert args.ai_filter == "custom"
    assert args.ai_filter_prompt == "Only accept Python roles"
    assert args.system_prompt != args.ai_filter_prompt


def test_custom_mode_uses_prompt_for_filter_client() -> None:
    """Scenario: a custom-mode prompt reaches the filter client.

    Given a custom AI filter and a prompt
    When a resume starts processing
    Then the vacancy-filter client receives that prompt with the resume analysis
    """
    operation = _make_operation()
    operation.ai_filter = "custom"
    operation.ai_filter_prompt = "Only accept Python roles"

    operation._apply_resume(
        resume={"id": "resume-1", "title": "Developer", "alternate_url": "url"},
        user={"first_name": "A"},
        seen_employers=set(),
    )

    operation.tool.get_vacancy_filter_ai.assert_called_once()
    system_prompt = operation.tool.get_vacancy_filter_ai.call_args.args[0]
    assert system_prompt.startswith("Only accept Python roles")
    assert "Кандидат:" in system_prompt
    assert "resume details" in system_prompt


def test_custom_mode_requires_prompt() -> None:
    """Scenario: custom mode without a prompt is rejected.

    Given a custom AI filter without --ai-filter-prompt
    When a resume starts processing
    Then an error is raised
    """
    operation = _make_operation()
    operation.ai_filter = "custom"
    operation.ai_filter_prompt = None

    try:
        operation._apply_resume(
            resume={"id": "resume-1", "title": "Developer", "alternate_url": "url"},
            user={"first_name": "A"},
            seen_employers=set(),
        )
    except ValueError as e:
        assert "--ai-filter-prompt" in str(e)
    else:
        raise AssertionError("custom mode without prompt must raise")


def test_heavy_mode_ignores_prompt() -> None:
    """Scenario: the prompt is ignored outside custom mode.

    Given a heavy AI filter with a prompt from the UI
    When a resume starts processing
    Then the built-in heavy prompt is used, not the custom one
    """
    operation = _make_operation()
    operation.ai_filter = "heavy"
    operation.ai_filter_prompt = "Only accept Python roles"

    operation._apply_resume(
        resume={"id": "resume-1", "title": "Developer", "alternate_url": "url"},
        user={"first_name": "A"},
        seen_employers=set(),
    )

    system_prompt = operation.tool.get_vacancy_filter_ai.call_args.args[0]
    assert "Only accept Python roles" not in system_prompt
    assert system_prompt.startswith("\nОпредели, подходит ли вакансия кандидату.")


def test_heavy_check_sends_vacancy_description() -> None:
    """Scenario: the heavy check sends the full vacancy to the filter AI.

    Given a vacancy whose full card has a description
    When the heavy suitability check runs
    Then the filter AI receives the vacancy name and description
    """
    operation = _make_operation()
    operation.tool.api_client.get.return_value = {
        "description": "<p>React и TypeScript</p>"
    }
    operation.vacancy_filter_ai = MagicMock()
    operation.vacancy_filter_ai.complete.return_value = "true"

    assert operation._is_vacancy_suitable_heavy({"id": "1", "name": "Frontend"})

    prompt = operation.vacancy_filter_ai.complete.call_args.args[0]
    assert "Вакансия: Frontend" in prompt
    assert "Описание: React и TypeScript" in prompt


def test_light_check_sends_key_skills() -> None:
    """Scenario: the light check sends only key skills to the filter AI.

    Given a vacancy with key skills
    When the light suitability check runs
    Then the filter AI receives the vacancy name and key skills
    """
    operation = _make_operation()
    operation.tool.api_client.get.return_value = {
        "key_skills": [{"name": "React"}, {"name": "TypeScript"}]
    }
    operation.vacancy_filter_ai = MagicMock()
    operation.vacancy_filter_ai.complete.return_value = "false"

    assert not operation._is_vacancy_suitable_light({"id": "1", "name": "Frontend"})

    prompt = operation.vacancy_filter_ai.complete.call_args.args[0]
    assert "Ключевые навыки: React, TypeScript" in prompt


def test_filter_client_sends_system_prompt_in_openai_payload() -> None:
    """Scenario: the filter prompt is present in the outbound AI request.

    Given a ChatOpenAI client configured with a filter system prompt
    When it completes a vacancy suitability request
    Then the outbound messages contain that prompt as the system message
    """
    session = MagicMock()
    session.post.return_value = _Response()
    client = ChatOpenAI(
        api_key="test-key",
        base_url="https://example.test/v1/chat/completions",
        model="test-model",
        system_prompt="Only accept Python roles",
        session=session,
    )

    assert client.complete("Вакансия: Python developer") == "true"

    payload = session.post.call_args.kwargs["json"]
    assert payload["messages"] == [
        {"role": "system", "content": "Only accept Python roles"},
        {"role": "user", "content": "Вакансия: Python developer"},
    ]
