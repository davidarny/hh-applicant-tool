"""Копии одной вакансии: отклик только на первую.

Работодатель может опубликовать одну вакансию десятком копий с разными
id. Раньше бот откликался на каждую, и все отклики приходили отказом.
Копию узнаём по работодателю и названию вакансии.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hh_applicant_tool.api.errors import ApiError

from .test_apply_limit_shutdown import _make_operation

RESUME = {"id": "r1", "title": "Dev", "alternate_url": "u"}
USER = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": ""}


def _vacancy(i: int, name: str = "Full Stack Developer", **extra) -> dict:
    return {
        "id": str(i),
        "name": name,
        "alternate_url": f"https://hh.ru/vacancy/{i}",
        # Без id работодателя: профиль не грузится, ключ строится по имени
        "employer": {"name": "Nitka"},
        "snippet": {},
        **extra,
    }


def _apply(vacancies: list[dict], seen_vacancies=None) -> MagicMock:
    op = _make_operation(max_responses=0)
    op._get_vacancies = lambda resume_id=None, resume_title="": iter(vacancies)
    op._apply_resume(
        resume=RESUME,
        user=USER,
        seen_employers=set(),
        seen_vacancies=seen_vacancies,
    )
    return op.tool.api_client.post


class TestCloneVacancies:
    def test_only_first_clone_is_applied(self):
        post = _apply([_vacancy(1), _vacancy(2), _vacancy(3, "full  stack developer")])

        assert post.call_count == 1

    def test_other_vacancies_of_same_employer_are_applied(self):
        post = _apply([_vacancy(1), _vacancy(2, "Frontend Developer")])

        assert post.call_count == 2

    def test_clone_of_earlier_application_is_skipped(self):
        """Ключи прошлых откликов приходят из _load_applied_vacancy_keys."""
        post = _apply([_vacancy(1)], seen_vacancies={("Nitka", "full stack developer")})

        assert post.call_count == 0

    def test_clone_with_response_blocks_later_clones(self):
        """Копия с откликом в выдаче тоже отмечает вакансию."""
        post = _apply([_vacancy(1, relations=["got_response"]), _vacancy(2)])

        assert post.call_count == 0


class TestLoadAppliedVacancyKeys:
    def test_keys_from_negotiations(self):
        op = _make_operation()
        op.tool.api_client.get.return_value = {
            "items": [
                {"vacancy": {"name": "Full Stack  Developer", "employer": {"id": 5}}},
                {"vacancy": {"name": "", "employer": {"id": 6}}},
            ],
            "pages": 1,
        }

        assert op._load_applied_vacancy_keys() == {("5", "full stack developer")}
        op.tool.api_client.get.assert_called_once()

    def test_api_error_gives_empty_set(self):
        op = _make_operation()
        op.tool.api_client.get.side_effect = ApiError(MagicMock(), {})

        assert op._load_applied_vacancy_keys() == set()
