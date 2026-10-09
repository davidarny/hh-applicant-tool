"""Разбор элемента чата в автоответчике.

При переписке autoresponder в main потерялся хелпер get_resource, и
parse_chat_item остался с обращением к несуществующим переменным
vacancy/resume — NameError на первом же чате. Тесты ловят именно разбор
ответа hh, без обращения к сети.

Формат resources у hh меняется: в одном ответе объекты лежат картой
прямо в элементе чата, в другом — списком id в item["resources"]
["VACANCY"], а объекты в resources верхнего уровня. Проверяем оба.
"""

from __future__ import annotations

import logging
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import MagicMock

import pytest
import requests

from hh_applicant_tool.api.errors import BadResponse
from hh_applicant_tool.operations.autoresponder import Operation


def _message(text: str = "Здравствуйте!") -> dict:
    return {
        "id": 9,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "text": text,
        "participantDisplay": {"name": "Иван Иванов", "isBot": False},
        "actions": {"text_buttons": [{"text": "Да, интересно"}]},
    }


def _vacancy(vacancy_id: int = 555) -> dict:
    return {
        "vacancyId": vacancy_id,
        "name": "Python разработчик",
        "company": {"id": 1, "name": "ООО Рога"},
        "links": {"desktop": "https://hh.ru/vacancy/555"},
        "compensation": {"from": 200000, "to": None, "currencyCode": "RUR"},
    }


def _resume(resume_id: int = 777) -> dict:
    return {
        "id": resume_id,
        "hash": "abc123",
        "title": "Python разработчик",
        "userId": 4242,
        "firstName": "Пётр",
        "lastName": "Петров",
    }


def _parse(operation: Operation, item: dict, **kwargs) -> object:
    params = {
        "resume_id": 777,
        "resume_hash": "abc123",
        "resume_title": "Python разработчик",
        "resume_experience": "5 лет",
        "salary": "200000",
        "skills": "Python",
    }
    params.update(kwargs)
    return operation.parse_chat_item(item, **params)


class TestResources:
    def test_resources_as_map_inside_item(self):
        """Объекты лежат картой прямо в элементе чата."""
        op = Operation()
        item = {
            "id": 1,
            "messages": {"items": [_message()]},
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        chat = _parse(op, item)

        assert chat is not None
        assert chat.vacancy_name == "Python разработчик"
        assert chat.company_name == "ООО Рога"
        assert chat.first_name == "Пётр"
        assert chat.applicant_id == 4242

    def test_ids_in_item_and_objects_in_common_resources(self):
        """Второй формат: id в элементе, объекты на верхнем уровне."""
        op = Operation()
        item = {
            "id": 1,
            "lastMessage": _message(),
            "resources": {"VACANCY": ["555"], "RESUME": ["777"]},
        }
        resources = {
            "vacancies": {"555": _vacancy()},
            "resumes": {"777": _resume()},
        }

        chat = _parse(op, item, resources=resources)

        assert chat is not None
        assert chat.vacancy_url == "https://hh.ru/vacancy/555"
        assert chat.vacancy_compensation

    def test_common_resources_used_without_item_ids(self):
        """Даже без id в элементе берём единственный объект."""
        op = Operation()
        item = {"id": 1, "messages": {"items": [_message()]}}
        resources = {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}}

        chat = _parse(op, item, resources=resources)

        assert chat is not None
        assert chat.vacancy_name == "Python разработчик"

    def test_resources_as_list(self):
        """Список объектов вместо карты."""
        op = Operation()
        item = {
            "id": 1,
            "messages": {"items": [_message()]},
            "resources": {
                "vacancies": [_vacancy()],
                "resumes": [_resume()],
            },
        }

        chat = _parse(op, item)

        assert chat is not None
        assert chat.last_name == "Петров"

    def test_missing_resources_skips_chat(self):
        """Нет вакансии — чат пропускаем, а не падаем."""
        op = Operation()
        item = {"id": 1, "messages": {"items": [_message()]}}

        assert _parse(op, item) is None

    def test_prefers_the_iterated_resume(self):
        """Резюме выбирается по resume_id, а не первое попавшееся."""
        op = Operation()
        other = _resume(888)
        other["firstName"] = "Чужое"
        item = {
            "id": 1,
            "messages": {"items": [_message()]},
            "resources": {
                "vacancies": {"555": _vacancy()},
                "resumes": {"888": other, "777": _resume()},
            },
        }

        chat = _parse(op, item, resume_id=777)

        assert chat is not None
        assert chat.first_name == "Пётр"


class TestLastMessage:
    def test_last_message_field_is_used(self):
        """Список чатов кладёт последнее сообщение в lastMessage."""
        op = Operation()
        item = {
            "id": 1,
            "lastMessage": _message("Сколько у вас зп?"),
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        chat = _parse(op, item)

        assert chat is not None
        assert chat.reply_to_message == "Сколько у вас зп?"

    def test_chat_without_messages_skipped(self):
        """Нет ни одного сообщения — отвечать не на что."""
        op = Operation()
        item = {"id": 1, "resources": {"vacancies": {}, "resumes": {}}}

        assert _parse(op, item) is None

    def test_old_chat_skipped(self):
        """Чаты старше 72 часов не трогаем."""
        op = Operation()
        old = _message()
        old["createdAt"] = (
            datetime.now(timezone.utc) - timedelta(hours=100)
        ).isoformat()
        item = {
            "id": 1,
            "lastMessage": old,
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        assert _parse(op, item) is None

    def test_creation_time_field_is_used(self):
        """Список чатов отдаёт время сообщения в creationTime."""
        op = Operation()
        message = _message()
        message["creationTime"] = message.pop("createdAt")
        item = {
            "id": 1,
            "lastMessage": message,
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        assert _parse(op, item) is not None

    def test_own_last_message_skipped(self):
        """Последним написал соискатель — ждём работодателя, не отвечаем."""
        op = Operation()
        message = _message("Здравствуйте! Меня зовут Пётр")
        message["participantId"] = 4242
        item = {
            "id": 1,
            "currentParticipantId": 4242,
            "lastMessage": message,
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        assert _parse(op, item) is None

    def test_blocked_chat_skipped(self):
        """В заблокированный чат hh не даст написать, пропускаем его."""
        op = Operation()
        item = {
            "id": 1,
            "blockInfo": {"reason": "EMPLOYER_ADDITIONAL_CHECK"},
            "lastMessage": _message(),
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        assert _parse(op, item) is None


class TestFormatSalary:
    def test_resume_amount(self):
        """Резюме отдаёт ожидания одной суммой в amount."""
        op = Operation()

        assert op.format_salary({"amount": 320000, "currency": "RUR"}) == "320000 RUR"

    def test_range(self):
        op = Operation()

        assert op.format_salary({"from": 200000, "to": 300000, "currency": "RUR"}) == "200000-300000 RUR"


class TestReplyToChat:
    def test_write_disabled_skips_ai_and_send(self):
        """Пока ИИ-помощник работодателя печатает, hh ответит 409.

        Не тратим запрос к AI и не отправляем сообщение.
        """
        op = Operation()
        op.tool = MagicMock()
        op.get_chat_data = MagicMock(  # type: ignore[method-assign]
            return_value={
                "chat": {
                    "writePossibility": {
                        "name": "DISABLED_FOR_APPLICANT_BY_AI_ASSISTANT",
                        "writeDisabledReasons": ["AI_ASSISTANT_TYPING"],
                    },
                    "messages": {"items": [_message()]},
                }
            }
        )
        op.send_chat_message = MagicMock()  # type: ignore[method-assign]
        item = {
            "id": 1,
            "lastMessage": _message(),
            "resources": {"vacancies": {"555": _vacancy()}, "resumes": {"777": _resume()}},
        }

        op.reply_to_chat(_parse(op, item))

        op.tool.get_chat_ai.assert_not_called()
        op.send_chat_message.assert_not_called()


class TestGetChatsAwaitingReply:
    def test_skipped_chats_do_not_break_the_loop(self):
        """parse_chat_item возвращает None — цикл это переживает.

        Раньше тут был chat.is_discard без проверки на None, то есть
        первый же отброшенный чат ронял весь проход.
        """
        op = Operation()
        tool = MagicMock()
        tool.get_resumes.return_value = [
            {
                "id": "777",
                "hash": "abc123",
                "title": "Python разработчик",
                "status": {"id": "published"},
                "experience": None,
                "salary": None,
                "skills": None,
            }
        ]
        op.tool = tool

        op.get_chats = MagicMock(  # type: ignore[method-assign]
            return_value={
                "chats": {
                    "pages": 1,
                    "items": [
                        {"id": 1},
                        {
                            "id": 2,
                            "lastMessage": _message(),
                            "resources": {
                                "vacancies": {"555": _vacancy()},
                                "resumes": {"777": _resume()},
                            },
                        },
                    ],
                }
            }
        )

        chats = op.get_chats_awaiting_reply(1)

        assert [c.chat_id for c in chats] == [2]

    def test_repeated_page_does_not_duplicate_chats(self):
        """hh игнорирует page и отдаёт одну и ту же страницу.

        Чат должен попасть в ответ один раз, иначе бот напишет в него
        столько раз, сколько страниц разрешено листать.
        """
        op = Operation()
        tool = MagicMock()
        tool.get_resumes.return_value = [
            {
                "id": "777",
                "hash": "abc123",
                "title": "Python разработчик",
                "status": {"id": "published"},
                "experience": None,
                "salary": None,
                "skills": None,
            }
        ]
        op.tool = tool

        op.get_chats = MagicMock(  # type: ignore[method-assign]
            return_value={
                "chats": {
                    "items": [
                        {
                            "id": 2,
                            "lastMessage": _message(),
                            "resources": {
                                "vacancies": {"555": _vacancy()},
                                "resumes": {"777": _resume()},
                            },
                        },
                    ],
                }
            }
        )

        chats = op.get_chats_awaiting_reply(5)

        assert [c.chat_id for c in chats] == [2]
        assert op.get_chats.call_count == 2


class TestChatUrl:
    def test_chatik_host_from_initial_state(self):
        """В v2.0 chat_url распаковывал словарь как пару и падал на старте."""
        op = Operation()
        op.tool = MagicMock()
        op.tool.get_initial_state.return_value = {
            "config": {"externalMicroFrontendHosts": {"chatik": "https://chatik.hh.ru"}},
            "account": {},
        }

        assert op.chat_url == "https://chatik.hh.ru"


class TestRun:
    @pytest.mark.parametrize(
        "error",
        [
            requests.ConnectionError("Remote end closed connection"),
            # api.hh.ru отдаёт 502 с HTML, клиент не может разобрать JSON
            BadResponse("Can't decode JSON: GET https://api.hh.ru/resumes/mine (502)"),
        ],
    )
    def test_network_error_logged_without_traceback(self, caplog, error):
        """hh.ru рвёт соединение — в логе одна строка, цикл живёт дальше."""
        cancel = Event()
        op = Operation()

        def fail(_max_pages):
            cancel.set()
            raise error

        op.get_chats_awaiting_reply = fail  # type: ignore[method-assign]
        args = Namespace(max_pages=1, interval=0, delete=False, _cancel_event=cancel)

        with caplog.at_level(logging.ERROR):
            op.run(MagicMock(), args)

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert [r.getMessage() for r in errors] == [f"Ошибка получения чатов: {error}"]
        assert errors[0].exc_info is None