"""Автоответчик reply-chats в форке.

Форк добавляет к апстриму то, без чего автоответчик не живёт: ошибка в
одном чате не обрывает проход, чаты, закрытые для сообщений,
пропускаются, из чатов с отказом бот выходит только по флагу, а
напоминает о себе молчащему работодателю только по флагу --bump.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

from hh_applicant_tool.operations.reply_chats import Operation

NOW = datetime.now(timezone.utc)


def _item(chat_id: int, *, mine: bool = False, age_days: float = 0, **extra) -> dict:
    item = {
        "id": chat_id,
        "currentParticipantId": "me",
        "lastMessage": {
            "id": chat_id * 10,
            "participantId": "me" if mine else "hr",
            "text": "Когда сможете созвониться?",
            "creationTime": (NOW - timedelta(days=age_days)).isoformat(),
        },
        "resources": {
            "RESUME": ["r1"],
            "VACANCY": ["v1"],
            "NEGOTIATION_TOPIC": [f"t{chat_id}"],
        },
    }
    item.update(extra)
    return item


def _collect(
    items: list[dict],
    *,
    leave_discarded: bool = False,
    bump: bool = False,
    discarded: set[int] = frozenset(),
) -> tuple[list[int], MagicMock]:
    op = Operation()
    op.tool = MagicMock()
    op.resume_id = None
    op.dry_run = False
    op.leave_discarded = leave_discarded
    op.bump = bump
    op.leave_chat = MagicMock()
    op.__dict__["chat_page_url"] = "https://chatik.hh.ru/"
    op.get_chats = MagicMock(
        return_value={
            "chats": {"items": items, "found": len(items), "nextFrom": None},
            "resources": {
                "resumeHashById": {"r1": "h1"},
                "negotiation_topics": {
                    f"t{i}": {"currentApplicantState": "DISCARD"}
                    for i in discarded
                },
                "vacancies": {
                    "v1": {
                        "name": "Go",
                        "company": {"id": 9, "name": "Co"},
                        "links": {"desktop": "https://hh.ru/vacancy/1"},
                    }
                },
            },
        }
    )
    ids = [c.chat_id for c in op.get_processing_chats(max_pages=3)]
    return ids, op.leave_chat


class TestCollectChats:
    def test_blocked_chat_skipped(self):
        ids, _ = _collect([_item(1, blockInfo={"reason": "x"}), _item(2)])

        assert ids == [2]

    def test_discarded_chat_stays_without_flag(self):
        ids, leave = _collect([_item(1), _item(2)], discarded={1})

        assert ids == [2]
        leave.assert_not_called()

    def test_discarded_chat_left_with_flag(self):
        ids, leave = _collect(
            [_item(1), _item(2)], discarded={1}, leave_discarded=True
        )

        assert ids == [2]
        leave.assert_called_once_with(1)

    def test_silent_employer_not_bumped_without_flag(self):
        ids, _ = _collect([_item(1, mine=True, age_days=5), _item(2)])

        assert ids == [2]

    def test_silent_employer_bumped_with_flag(self):
        ids, _ = _collect([_item(1, mine=True, age_days=5), _item(2)], bump=True)

        assert ids == [1, 2]


def test_chat_error_does_not_stop_other_chats(caplog):
    op = Operation()
    op.tool = MagicMock()
    op.max_pages = 1
    op.loop = False
    op.get_unread_count = MagicMock(return_value={"unreadCount": 2})
    op.get_processing_chats = MagicMock(
        return_value=iter([SimpleNamespace(chat_id=1), SimpleNamespace(chat_id=2)])
    )
    op.process_chat = MagicMock(
        side_effect=[requests.HTTPError("409 Conflict"), None]
    )

    op.reply_chats()

    assert op.process_chat.call_count == 2
    assert "Ошибка ответа в чате 1: 409 Conflict" in caplog.text
