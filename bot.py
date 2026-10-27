import os
import asyncio
import logging
import secrets
from html import escape
from urllib.parse import urlparse

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    BusinessConnection,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("nft_offer_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Set it in Render Environment.")
if not ADMIN_ID_RAW.isdigit():
    raise RuntimeError("ADMIN_ID must be your numeric Telegram user ID.")
ADMIN_ID = int(ADMIN_ID_RAW)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# In-memory demo state. It resets when the Render worker restarts.
connections: dict[str, BusinessConnection] = {}
known_chats: dict[str, dict] = {}
offers: dict[str, dict] = {}


def valid_telegram_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.netloc in {
            "t.me", "www.t.me", "telegram.me", "www.telegram.me"
        }
    except ValueError:
        return False


def format_stars(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def offer_keyboard(offer_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✓  Принять предложение",
                callback_data=f"accept:{offer_id}",
            )],
            [InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"decline:{offer_id}",
            )],
        ]
    )


def is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


@dp.business_connection()
async def on_business_connection(connection: BusinessConnection):
    if connection.is_enabled:
        connections[connection.id] = connection
        log.info("Business connection enabled: %s", connection.id)
    else:
        connections.pop(connection.id, None)
        log.info("Business connection disabled: %s", connection.id)


@dp.business_message()
async def on_business_message(message: Message):
    connection_id = message.business_connection_id
    user = message.from_user
    if not connection_id or not user or not user.username:
        return

    connection = connections.get(connection_id)
    if not connection or not connection.is_enabled:
        return

    # A username is only mapped after the business account receives
    # a message from that user in an accessible chat.
    known_chats[user.username.casefold()] = {
        "chat_id": message.chat.id,
        "connection_id": connection_id,
        "user_id": user.id,
    }


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message):
        await message.answer("Бот для отправки NFT-предложений.")
        return
    await message.answer(
        "NFT Offer Bot запущен.\n\n"
        "Команда:\n"
        "/offer @username 1000 https://t.me/nft/...\n\n"
        "После реальной проверки получения подарка:\n"
        "/received ID_предложения\n\n"
        "Важно: это собственное сообщение бота, не системный оффер Telegram."
    )


@dp.message(Command("offer"))
async def cmd_offer(message: Message):
    if not is_admin(message):
        return

    parts = (message.text or "").split(maxsplit=3)
    if len(parts) != 4:
        await message.answer(
            "Формат команды:\n"
            "/offer @username 1000 https://t.me/nft/...\n\n"
            "Цена задаётся целым числом Stars, ссылка — индивидуальная."
        )
        return

    username = parts[1].lstrip("@").casefold()
    if not username or any(ch.isspace() for ch in username):
        await message.answer("Укажи корректный @username.")
        return

    try:
        price = int(parts[2])
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Цена должна быть целым числом больше нуля.")
        return

    gift_url = parts[3].strip()
    if not valid_telegram_url(gift_url):
        await message.answer(
            "Ссылка должна быть HTTPS-ссылкой Telegram, например "
            "https://t.me/nft/..."
        )
        return

    target = known_chats.get(username)
    if not target:
        await message.answer(
            f"Не найден доступный чат @{username}.\n\n"
            "Один @username не позволяет боту произвольно начать чат. "
            "Пользователь должен написать в доступный бизнес-чат, "
            "и подключение должно разрешать отправку сообщений."
        )
        return

    connection_id = target["connection_id"]
    connection = connections.get(connection_id)
    if not connection or not connection.is_enabled:
        await message.answer("Business-подключение отключено или недоступно.")
        return

    offer_id = secrets.token_hex(4).upper()
    offers[offer_id] = {
        "username": username,
        "user_id": target["user_id"],
        "chat_id": target["chat_id"],
        "connection_id": connection_id,
        "price": price,
        "gift_url": gift_url,
        "status": "pending",
    }

    text = (
        "💎 <b>Предложение о покупке</b>\n\n"
        "Коллекционный подарок Telegram\n\n"
        f"💰 <b>Цена предложения: {format_stars(price)} ⭐</b>\n\n"
        "Если вы согласны продать подарок по указанной цене, "
        "нажмите «Принять предложение».\n\n"
        f'<a href="{escape(gift_url, quote=True)}">Посмотреть подарок</a>\n\n'
        "<i>Выплата производится покупателем вручную после проверки "
        "получения подарка. Это сообщение не является системным "
        "оффером Telegram.</i>"
    )

    try:
        await bot.send_message(
            chat_id=target["chat_id"],
            business_connection_id=connection_id,
            text=text,
            parse_mode="HTML",
            reply_markup=offer_keyboard(offer_id),
            disable_web_page_preview=False,
        )
    except Exception:
        offers.pop(offer_id, None)
        log.exception("Failed to send offer")
        await message.answer(
            "Не удалось отправить предложение. Проверь Business-права "
            "и доступность чата; подробности смотри в Render Logs."
        )
        return

    await message.answer(
        f"Предложение отправлено @{username}.\n"
        f"Цена: {format_stars(price)} ⭐\n"
        f"ID: {offer_id}"
    )


@dp.callback_query(F.data.startswith(("accept:", "decline:")))
async def on_offer_action(callback: CallbackQuery):
    if not callback.data or not callback.message:
        await callback.answer()
        return

    action, offer_id = callback.data.split(":", 1)
    offer = offers.get(offer_id)
    if not offer:
        await callback.answer(
            "Предложение недоступно. Возможно, бот перезапускался.",
            show_alert=True,
        )
        return

    if callback.from_user.id != offer["user_id"]:
        await callback.answer(
            "Это предложение предназначено другому пользователю.",
            show_alert=True,
        )
        return

    if offer["status"] != "pending":
        await callback.answer("Предложение уже обработано.", show_alert=True)
        return

    if action == "decline":
        offer["status"] = "declined"
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer("Предложение отклонено.")
        await bot.send_message(
            ADMIN_ID,
            f"Предложение <code>{offer_id}</code> отклонено "
            f"пользователем @{escape(offer['username'])}.",
            parse_mode="HTML",
        )
        await callback.answer("Предложение отклонено.")
        return

    offer["status"] = "accepted"
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        "✓ <b>Предложение принято</b>\n\n"
        "Свяжитесь с покупателем и передайте указанный подарок. "
        "Покупатель проверит получение и произведёт оплату вручную.",
        parse_mode="HTML",
    )
    await bot.send_message(
        ADMIN_ID,
        "🤝 <b>Предложение принято</b>\n\n"
        f"Продавец: @{escape(offer['username'])}\n"
        f"Сумма к выплате: <b>{format_stars(offer['price'])} ⭐</b>\n"
        f'<a href="{escape(offer["gift_url"], quote=True)}">Ссылка на подарок</a>\n'
        f"ID: <code>{offer_id}</code>\n\n"
        "После самостоятельной проверки получения отправь:\n"
        f"<code>/received {offer_id}</code>",
        parse_mode="HTML",
    )
    await callback.answer("Предложение принято.")


@dp.message(Command("received"))
async def cmd_received(message: Message):
    if not is_admin(message):
        return

    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /received ID_предложения")
        return

    offer_id = parts[1].upper()
    offer = offers.get(offer_id)
    if not offer or offer["status"] != "accepted":
        await message.answer(
            "Предложение не найдено или не находится в статусе «принято»."
        )
        return

    # This is an admin confirmation, not automatic NFT ownership verification.
    offer["status"] = "received"
    await message.answer(
        "✓ <b>Получение отмечено</b>\n\n"
        f"Продавец: @{escape(offer['username'])}\n"
        f"Сумма к ручной выплате: <b>{format_stars(offer['price'])} ⭐</b>\n\n"
        "Это только твоя отметка. Перед выплатой самостоятельно "
        "убедись, что подарок действительно поступил.",
        parse_mode="HTML",
    )


async def main():
    log.info("Starting NFT Offer Bot")
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "business_connection",
            "business_message",
        ],
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # Best-effort cleanup on process exit.
        pass
