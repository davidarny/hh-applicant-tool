"""Вакансия с тестом: отклик уходит один раз, через форму теста.

После отправки теста код проваливался дальше и слал ещё и обычный
отклик через API. hh отвечал 403 «Must process test first», и в логе
появлялась ложная ошибка отправки.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from .test_apply_clone_vacancies import RESUME, USER, _vacancy
from .test_apply_limit_shutdown import _make_operation


def _apply_with_test(result: dict) -> MagicMock:
    op = _make_operation(max_responses=0)
    op._get_vacancies = lambda resume_id=None, resume_title="": iter(
        [_vacancy(1, has_test=True)]
    )
    op._solve_vacancy_test = MagicMock(return_value=result)
    op._apply_resume(resume=RESUME, user=USER, seen_employers=set())
    op._solve_vacancy_test.assert_called_once()
    return op.tool.api_client.post


class TestVacancyWithTest:
    def test_solved_test_is_not_posted_again(self):
        post = _apply_with_test({"success": "true"})

        post.assert_not_called()

    def test_failed_test_is_not_posted_again(self):
        """Без пройденного теста hh всё равно не примет отклик через API."""
        post = _apply_with_test({"success": "false", "error": "unknown"})

        post.assert_not_called()
