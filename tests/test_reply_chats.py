"""Автоответчик reply-chats в форке.

В 2.2 апстрим заменил autoresponder на reply-chats. Форк возвращает то, без
чего автоответчик не живёт: ошибка в одном чате не обрывает проход, чаты,
закрытые для сообщений, пропускаются, а из чатов с отказом бот выходит
только по флагу. Цикл с 2.3 внешний, его задаёт crontab.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

from hh_applicant_tool.operations.reply_chats import Operation

NOW = datetime.now(timezone.utc).isoformat()


def _item(chat_id: int, **extra) -> dict:
    item = {
        "id": chat_id,
        "currentParticipantId": "me",
        "lastMessage": {
            "participantId": "hr",
            "text": "Когда сможете созвониться?",
            "creationTime": NOW,
        },
        "resources": {"RESUME": ["r1"], "VACANCY": ["v1"]},
    }
    item.update(extra)
    return item


def _discarded(chat_id: int) -> dict:
    item = _item(chat_id)
    item["lastMessage"]["workflowTransition"] = {"applicantState": "DISCARD"}
    return item


def _collect(items: list[dict], *, leave_discarded: bool = False) -> list[int]:
    op = Operation()
    op.tool = MagicMock()
    op.tool.get_resumes.return_value = [
        {"id": "rid", "hash": "h1", "status": {"id": "published"}}
    ]
    op.resume_id = None
    op.max_age = None
    op.ignored_chats = set()
    op.user = {"id": 7}
    op.leave_discarded = leave_discarded
    op.__dict__["chat_page_url"] = "https://chatik.hh.ru/"
    op.get_chats = MagicMock(
        return_value={
            "chats": {"items": items},
            "resources": {
                "resumeHashById": {"r1": "h1"},
                "resumes": {"r1": {"userId": 7}},
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
    return [c.chat_id for c in op.get_chats_awaiting_reply(max_pages=3)]


class TestCollectChats:
    def test_blocked_chat_skipped(self):
        assert _collect([_item(1, blockInfo={"reason": "x"}), _item(2)]) == [2]

    def test_discarded_chat_stays_without_flag(self):
        assert _collect([_discarded(1), _item(2)]) == [2]

    def test_discarded_chat_left_with_flag(self):
        items = [_discarded(1), _item(2)]

        assert _collect(items, leave_discarded=True) == [1, 2]


def test_chat_error_does_not_stop_other_chats(caplog):
    op = Operation()
    op.tool = MagicMock()
    op.tool.get_blacklisted.return_value = []
    op.max_pages = 1
    op.get_unread_count = MagicMock(return_value={"unreadCount": 2})
    op.get_chats_awaiting_reply = MagicMock(
        return_value=[SimpleNamespace(chat_id=1), SimpleNamespace(chat_id=2)]
    )
    op.process_chat = MagicMock(
        side_effect=[requests.HTTPError("409 Conflict"), None]
    )

    op.reply_chats()

    assert op.process_chat.call_count == 2
    assert "Ошибка ответа в чате 1: 409 Conflict" in caplog.text
