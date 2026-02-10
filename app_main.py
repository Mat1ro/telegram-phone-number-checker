import logging
import re
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from telegram_phone_number_checker.main import (
    login,
    get_user_info_by_phone,
    TelegramClient,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Telegram Phone Checker")

_client: Optional[TelegramClient] = None


class PhoneRequest(BaseModel):
    phone: str


def _normalize_phone(phone: str) -> str:
    """
    Приводим номер к единому виду: убираем пробелы, добавляем '+' если надо
    и проверяем, что остались только цифры.
    """
    if not phone:
        raise ValueError("Пустой номер телефона")

    normalized = re.sub(r"\s+", "", phone)
    if not normalized.startswith("+"):
        normalized = f"+{normalized}"

    if not re.fullmatch(r"\+\d{5,20}", normalized):
        raise ValueError("Неверный формат номера телефона")

    return normalized


async def _get_or_create_client() -> TelegramClient:
    global _client
    if _client is None:
        # login() сам читает API_ID, API_HASH, PHONE_NUMBER из окружения/.env при необходимости
        _client = await login(api_id=None, api_hash=None, phone_number=None)
    return _client


async def _build_result_string(phone: str) -> str:
    """
    Обёртка, которая:
    - нормализует номер
    - ходит в Telegram
    - приводит ответ к одной строке (username или человекочитаемая ошибка)
    """
    normalized = _normalize_phone(phone)
    client = await _get_or_create_client()

    info = await get_user_info_by_phone(client, normalized)

    # Условно нормализуем основные варианты
    if not info:
        return "Неизвестная ошибка"

    # Явная ошибка от нижележащей функции
    if "error" in info and info["error"]:
        error_text = str(info["error"])

        # Простейшее приближение: маппим типовые сообщения в более понятные русские тексты
        if "not on Telegram" in error_text:
            return "Нет такого пользователя в Telegram или заблокировано добавление в контакты"
        if "multiple Telegram accounts" in error_text:
            return "Номер привязан к нескольким аккаунтам (неожиданная ситуация)"

        return error_text

    username = info.get("username")
    if username:
        # Возвращаем с '@' для удобства визуально отличать username
        return f"@{username}"

    # Пользователь есть, но username отсутствует
    if info.get("id"):
        return "У пользователя нет username"

    return "Не удалось определить информацию по номеру"


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _client
    if _client is not None:
        await _client.disconnect()
        _client = None


@app.get("/check_phone")
async def check_phone(phone: str) -> dict:
    """
    Простой GET-эндпоинт для Google Sheets:
    - принимает номер как query-параметр ?phone=+7999...
    - возвращает JSON вида {\"result\": \"@username\" или \"текст ошибки\"}
    """
    try:
        result = await _build_result_string(phone)
    except ValueError as e:
        # Ошибка формата номера
        return {"result": str(e)}
    except Exception as e:
        logger.exception("Unexpected error while checking phone %s: %s", phone, e)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервиса")

    return {"result": result}


@app.post("/check_phone")
async def check_phone_post(body: PhoneRequest) -> dict:
    """
    Альтернативный POST-эндпоинт на тот же функционал.
    """
    return await check_phone(phone=body.phone)

