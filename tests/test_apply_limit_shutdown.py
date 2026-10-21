"""Deterministic tests for --max-responses being enforced in the apply loop.

The graceful-shutdown test went away with the cancel check, which upstream
removed from the loop in v2.0.

These tests avoid live hh.ru credentials — they mock the network/API layer,
so they run in any environment (the real /me and /resumes/mine calls return
403 here because the HH token is server-rejected, unrelated to the code).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hh_applicant_tool.operations.apply_vacancies import Operation


def _make_vacancy(i: int) -> dict:
    return {
        "id": str(i),
        "name": f"Vacancy {i}",
        "alternate_url": f"https://hh.ru/vacancy/{i}",
        "employer": {},  # no employer id -> no profile fetch
        "snippet": {},
    }


def _make_operation(max_responses: int = 5) -> Operation:
    op = Operation()
    # Attributes that run() sets from args before _apply_resume
    op.max_responses = max_responses
    op.dry_run = False
    op.ai_filter = False
    op.vacancy_filter_ai = None
    op.cover_letter_ai = None
    op.excluded_pat = None
    op.cover_letter = "hello"
    op.force_cover_letter = False
    op.send_email = False
    op.skip_tests = False

    tool = MagicMock()
    tool.general_config = {}
    tool.get_resume_placeholders.return_value = {}
    op.tool = tool

    # Each post returns empty dict -> assert res == {} passes, applied_count++.
    # `api_client` is a read-only property returning `tool.api_client`.
    op.tool.api_client = MagicMock()
    op.tool.api_client.post.return_value = {}
    return op


class TestMaxResponses:
    def test_loop_stops_after_max_responses(self):
        """With --max-responses 5 and 20 vacancies, only 5 are applied."""
        op = _make_operation(max_responses=5)
        total = 20
        op._get_vacancies = lambda resume_id=None, resume_title="": iter(
            _make_vacancy(i) for i in range(total)
        )

        resume = {"id": "r1", "title": "Dev", "alternate_url": "u"}
        user = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": ""}
        op._apply_resume(resume=resume, user=user, seen_employers=set())

        assert op.tool.api_client.post.call_count == 5

    def test_no_limit_means_no_early_stop(self):
        """Without max-responses, all vacancies are attempted."""
        op = _make_operation(max_responses=0)
        total = 8
        op._get_vacancies = lambda resume_id=None, resume_title="": iter(
            _make_vacancy(i) for i in range(total)
        )

        resume = {"id": "r1", "title": "Dev", "alternate_url": "u"}
        user = {"first_name": "A", "last_name": "B", "email": "a@b.c", "phone": ""}
        op._apply_resume(resume=resume, user=user, seen_employers=set())

        assert op.tool.api_client.post.call_count == total
