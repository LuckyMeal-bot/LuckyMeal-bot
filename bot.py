import logging
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from database import (
    add_offer,
    confirm_booking,
    create_or_update_venue,
    get_offer,
    get_venue_by_telegram_id,
    init_db,
    list_available_offers,
    list_buyer_bookings,
    list_venue_offers,
)


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

(
    REGISTER_NAME,
    REGISTER_ADDRESS,
    REGISTER_PHONE,
    REGISTER_INSTAGRAM,
    REGISTER_CONTACT_PERSON,
    OFFER_TITLE,
    OFFER_ORIGINAL_PRICE,
    OFFER_PRICE,
    OFFER_QUANTITY,
    OFFER_PICKUP_TIME,
    OFFER_PHOTO,
) = range(11)

WELCOME_TEXT = (
    "🍽️ Ласкаво просимо до LuckyMeal\n\n"
    "Допомагаємо рятувати якісну їжу від списання та знаходити вигідні пропозиції поруч.\n\n"
    "Оберіть роль:"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_price(value):
    return f"{value:.0f} грн"


def discount_percent(original_price, price):
    if original_price <= 0:
        return 0
    return max(round((original_price - price) / original_price * 100), 0)


def offer_card_text(offer, include_id=False):
    original_price = offer["original_price"]
    price = offer["price"]
    discount = discount_percent(original_price, price)
    id_prefix = f"#{offer['id']} " if include_id else ""

    lines = [
        f"🏪 {offer['venue_name']}",
        f"🍽️ {id_prefix}{offer['title']}",
        "",
        f"💰 Ціна зі знижкою: {format_price(price)}",
        f"💸 Звичайна ціна: {format_price(original_price)}",
        f"📉 Знижка: {discount}%",
        "",
    ]
    if offer["venue_address"]:
        lines.append(f"📍 {offer['venue_address']}")
    if offer["venue_phone"]:
        lines.append(f"📞 {offer['venue_phone']}")
    if offer["venue_instagram"]:
        lines.append(f"📷 {offer['venue_instagram']}")
    lines.append(f"🕒 Час видачі: {offer['pickup_time']}")
    lines.append(f"📦 Наборів залишилось: {offer['quantity']}")
    lines.append("🚶 Самовивіз")

    return "\n".join(lines)


def booking_confirmation_text(booking_id, offer):
    lines = [
        "✅ Бронювання підтверджено!",
        "",
        f"Номер бронювання: #{booking_id}",
        f"🏪 Заклад: {offer['venue_name']}",
        f"🍽️ Набір: {offer['title']}",
        f"💰 Ціна: {format_price(offer['price'])}",
        f"🕒 Час видачі: {offer['pickup_time']}",
    ]
    if offer["venue_address"]:
        lines.append(f"📍 Адреса: {offer['venue_address']}")
    lines += [
        "",
        "Будь ласка, прийдіть до закладу у вказаний час та покажіть це повідомлення для отримання замовлення.",
        "🚶 Самовивіз",
    ]
    return "\n".join(lines)


def venue_notification_text(booking_id, offer, buyer_name, buyer_username=None):
    now = datetime.now().strftime("%d.%m.%Y о %H:%M")
    buyer_display = f"@{buyer_username}" if buyer_username else buyer_name
    remaining = max(offer["quantity"] - 1, 0)
    return (
        f"🔔 Нове бронювання\n\n"
        f"Заклад: {offer['venue_name']}\n"
        f"Покупець: {buyer_display}\n"
        f"Набір: {offer['title']}\n"
        f"Кількість: 1\n"
        f"Час бронювання: {now}\n\n"
        f"⏰ Час видачі: {offer['pickup_time']}\n"
        f"📦 Залишилось наборів: {remaining}"
    )


def admin_notification_text(booking_id, offer, buyer):
    buyer_username = f"@{buyer.username}" if buyer.username else "не вказано"
    return (
        f"📋 Службове повідомлення — бронювання #{booking_id}\n\n"
        f"Заклад: {offer['venue_name']}\n"
        f"Адреса: {offer['venue_address'] or 'не вказано'}\n"
        f"Контакт: {offer['venue_contact_person'] or 'не вказано'}\n"
        f"Телефон: {offer['venue_phone'] or 'не вказано'}\n"
        f"Instagram: {offer['venue_instagram'] or 'не вказано'}\n\n"
        f"Набір: {offer['title']}\n"
        f"Ціна: {format_price(offer['price'])}\n"
        f"Час видачі: {offer['pickup_time']}\n\n"
        f"Покупець: {buyer.full_name}\n"
        f"Telegram ID: {buyer.id}\n"
        f"Username: {buyer_username}"
    )


async def send_notification(bot, chat_id, text, notification_name):
    if not chat_id:
        logging.info("%s notification skipped: no chat_id", notification_name)
        return False
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        logging.info("%s notification sent", notification_name)
        return True
    except Exception as error:
        logging.warning("Could not send %s notification: %s", notification_name, error)
        return False


def get_admin_chat_id():
    return os.getenv("ADMIN_CHAT_ID")


def venue_profile_is_complete(venue):
    return all(
        venue[field]
        for field in ("name", "address", "phone", "contact_person")
    )


# ── Keyboards ─────────────────────────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Я покупець", callback_data="role_buyer"),
                InlineKeyboardButton("Я заклад", callback_data="role_venue"),
            ],
        ]
    )


def venue_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Додати пропозицію", callback_data="venue_add_offer")],
            [InlineKeyboardButton("📋 Мої пропозиції", callback_data="venue_my_offers")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")],
        ]
    )


def buyer_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Переглянути пропозиції", callback_data="buyer_list_offers")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")],
        ]
    )


def offer_keyboard(offers):
    buttons = []
    for offer in offers:
        discount = discount_percent(offer["original_price"], offer["price"])
        text = f"{offer['venue_name']} — {format_price(offer['price'])} (−{discount}%)"
        buttons.append([InlineKeyboardButton(text, callback_data=f"offer_{offer['id']}")])
    buttons.append([InlineKeyboardButton("← Назад", callback_data="role_buyer")])
    return InlineKeyboardMarkup(buttons)


def booking_confirm_keyboard(offer_id):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Підтвердити бронювання", callback_data=f"confirm_{offer_id}")],
            [InlineKeyboardButton("← Назад до списку", callback_data="buyer_list_offers")],
        ]
    )


def photo_skip_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Пропустити →", callback_data="skip_photo")]]
    )


# ── Commands ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(WELCOME_TEXT, reply_markup=main_menu_keyboard())
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(WELCOME_TEXT, reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Довідка LuckyMeal\n\n"
        "Як покупець:\n"
        "• /offers — переглянути доступні пропозиції\n"
        "• /mybookings — ваші бронювання\n\n"
        "Як заклад:\n"
        "• /myvenue — профіль закладу та пропозиції\n\n"
        "Загальне:\n"
        "• /start — повернутись до головного меню\n"
        "• /myid — ваш Telegram ID\n"
        "• /cancel — скасувати поточну дію\n\n"
        "Є питання? Напишіть нам — ми завжди на зв'язку."
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш Telegram ID: {update.effective_user.id}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Дію скасовано.\n\nЩоб повернутися до головного меню, натисніть /start"
    )
    return ConversationHandler.END


async def offers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    offers = list_available_offers()
    if not offers:
        await update.message.reply_text(
            "Поки немає доступних пропозицій. Завітайте трохи пізніше.",
            reply_markup=buyer_keyboard(),
        )
        return
    await update.message.reply_text(
        "🔍 Доступні пропозиції:\n\nОберіть набір, щоб побачити деталі та забронювати.",
        reply_markup=offer_keyboard(offers),
    )


async def mybookings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bookings = list_buyer_bookings(update.effective_user.id)
    if not bookings:
        await update.message.reply_text(
            "❤️ У вас ще немає бронювань.\n\n"
            "Скористайтеся командою /offers, щоб знайти доступні пропозиції."
        )
        return
    lines = ["❤️ Ваші останні бронювання:\n"]
    for b in bookings:
        address = b["venue_address"] or "адреса не вказана"
        lines.append(
            f"#{b['booking_id']} {b['venue_name']}\n"
            f"🍽️ {b['offer_title']}\n"
            f"💰 {format_price(b['price'])}\n"
            f"🕒 {b['pickup_time']}\n"
            f"📍 {address}\n"
        )
    await update.message.reply_text("\n".join(lines))


async def myvenue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    venue = get_venue_by_telegram_id(update.effective_user.id)
    if venue is None or not venue_profile_is_complete(venue):
        await update.message.reply_text(
            "🏪 Профіль закладу не знайдено.\n\n"
            "Натисніть /start, оберіть «Я заклад» і зареєструйте профіль."
        )
        return
    instagram_line = f"📷 {venue['instagram']}\n" if venue["instagram"] else ""
    await update.message.reply_text(
        f"🏪 {venue['name']}\n"
        f"📍 {venue['address']}\n"
        f"📞 {venue['phone']}\n"
        f"{instagram_line}"
        f"👤 {venue['contact_person']}",
        reply_markup=venue_keyboard(),
    )


# ── Role selection ────────────────────────────────────────────────────────────

async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        await start(update, context)
        return ConversationHandler.END

    if query.data == "role_venue":
        venue = get_venue_by_telegram_id(query.from_user.id)
        if venue is None or not venue_profile_is_complete(venue):
            context.user_data["new_venue"] = {}
            await query.edit_message_text(
                "📝 Реєстрація закладу\n\n"
                "Крок 1 з 5 — Введіть назву закладу.\n"
                "Наприклад: Пекарня на Подолі"
            )
            return REGISTER_NAME

        await query.edit_message_text(
            f"🏪 Ви увійшли як заклад: {venue['name']}",
            reply_markup=venue_keyboard(),
        )
        return ConversationHandler.END

    if query.data == "role_buyer":
        await query.edit_message_text(
            "🛍️ Ви увійшли як покупець.\n\nОберіть дію:",
            reply_markup=buyer_keyboard(),
        )
        return ConversationHandler.END

    return ConversationHandler.END


# ── Venue registration ─────────────────────────────────────────────────────────

async def register_venue_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Назва занадто коротка. Введіть назву ще раз.")
        return REGISTER_NAME
    context.user_data["new_venue"]["name"] = name
    await update.message.reply_text(
        "📝 Крок 2 з 5 — Введіть адресу закладу.\n"
        "Наприклад: Київ, вул. Ярославська, 12"
    )
    return REGISTER_ADDRESS


async def register_venue_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if len(address) < 5:
        await update.message.reply_text("Адреса занадто коротка. Введіть повну адресу.")
        return REGISTER_ADDRESS
    context.user_data["new_venue"]["address"] = address
    await update.message.reply_text(
        "📝 Крок 3 з 5 — Введіть телефон закладу.\n"
        "Наприклад: +380671234567"
    )
    return REGISTER_PHONE


async def register_venue_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if sum(c.isdigit() for c in phone) < 10:
        await update.message.reply_text(
            "Схоже, номер неповний. Введіть ще раз, наприклад: +380671234567"
        )
        return REGISTER_PHONE
    context.user_data["new_venue"]["phone"] = phone
    await update.message.reply_text(
        "📝 Крок 4 з 5 — Введіть Instagram закладу (необов'язково).\n"
        "Наприклад: @bakery_kyiv\n\n"
        "Якщо Instagram немає — натисніть «Пропустити».",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Пропустити →", callback_data="skip_instagram")]]
        ),
    )
    return REGISTER_INSTAGRAM


async def register_venue_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instagram = update.message.text.strip()
    if len(instagram) < 2:
        await update.message.reply_text("Введіть Instagram ще раз або натисніть «Пропустити».")
        return REGISTER_INSTAGRAM
    context.user_data["new_venue"]["instagram"] = instagram
    await update.message.reply_text(
        "📝 Крок 5 з 5 — Введіть ім'я контактної особи.\n"
        "Наприклад: Олена"
    )
    return REGISTER_CONTACT_PERSON


async def register_venue_instagram_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_venue"]["instagram"] = None
    await query.edit_message_text(
        "📝 Крок 5 з 5 — Введіть ім'я контактної особи.\n"
        "Наприклад: Олена"
    )
    return REGISTER_CONTACT_PERSON


async def register_venue_contact_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_person = update.message.text.strip()
    if len(contact_person) < 2:
        await update.message.reply_text("Ім'я занадто коротке. Введіть ім'я ще раз.")
        return REGISTER_CONTACT_PERSON

    new_venue = context.user_data["new_venue"]
    create_or_update_venue(
        owner_telegram_id=update.effective_user.id,
        name=new_venue["name"],
        address=new_venue["address"],
        phone=new_venue["phone"],
        instagram=new_venue["instagram"],
        contact_person=contact_person,
    )
    context.user_data.pop("new_venue", None)

    instagram_line = f"📷 {new_venue['instagram']}\n" if new_venue.get("instagram") else ""
    await update.message.reply_text(
        "✅ Профіль закладу створено!\n\n"
        f"🏪 {new_venue['name']}\n"
        f"📍 {new_venue['address']}\n"
        f"📞 {new_venue['phone']}\n"
        f"{instagram_line}"
        f"👤 {contact_person}",
        reply_markup=venue_keyboard(),
    )
    return ConversationHandler.END


# ── Venue actions ─────────────────────────────────────────────────────────────

async def venue_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "venue_add_offer":
        venue = get_venue_by_telegram_id(query.from_user.id)
        if venue is None:
            await query.edit_message_text("Спочатку зареєструйте заклад через /start.")
            return ConversationHandler.END
        context.user_data["new_offer"] = {}
        await query.edit_message_text(
            "➕ Нова пропозиція\n\n"
            "Крок 1 з 5 — Введіть назву набору.\n"
            "Наприклад: Вечірній мікс випічки"
        )
        return OFFER_TITLE

    if query.data == "venue_my_offers":
        offers = list_venue_offers(query.from_user.id)
        if not offers:
            await query.edit_message_text(
                "📋 У вас поки немає активних пропозицій.",
                reply_markup=venue_keyboard(),
            )
            return ConversationHandler.END

        lines = ["📋 Ваші пропозиції:\n"]
        for offer in offers:
            photo_note = " 📷" if offer["photo_file_id"] else ""
            lines.append(
                f"#{offer['id']} {offer['title']}{photo_note}\n"
                f"💰 {format_price(offer['price'])} (звичайна: {format_price(offer['original_price'])})\n"
                f"📉 Знижка: {discount_percent(offer['original_price'], offer['price'])}%\n"
                f"📦 Залишилось: {offer['quantity']}\n"
                f"🕒 {offer['pickup_time']}\n"
            )

        await query.edit_message_text("\n".join(lines), reply_markup=venue_keyboard())
        return ConversationHandler.END

    return ConversationHandler.END


# ── Offer creation flow ───────────────────────────────────────────────────────

async def offer_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if len(title) < 3:
        await update.message.reply_text("Назва занадто коротка. Введіть назву ще раз.")
        return OFFER_TITLE
    context.user_data["new_offer"]["title"] = title
    await update.message.reply_text(
        "Крок 2 з 5 — Введіть звичайну ціну набору в гривнях.\n"
        "Наприклад: 500"
    )
    return OFFER_ORIGINAL_PRICE


async def offer_original_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        original_price = float(update.message.text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Ціна має бути числом. Наприклад: 500")
        return OFFER_ORIGINAL_PRICE
    if original_price <= 0:
        await update.message.reply_text("Ціна має бути більшою за нуль.")
        return OFFER_ORIGINAL_PRICE
    context.user_data["new_offer"]["original_price"] = original_price
    await update.message.reply_text(
        "Крок 3 з 5 — Введіть ціну зі знижкою в гривнях.\n"
        "Наприклад: 250"
    )
    return OFFER_PRICE


async def offer_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Ціна має бути числом. Наприклад: 250")
        return OFFER_PRICE
    if price <= 0:
        await update.message.reply_text("Ціна має бути більшою за нуль.")
        return OFFER_PRICE
    original_price = context.user_data["new_offer"]["original_price"]
    if price > original_price:
        await update.message.reply_text(
            "Ціна зі знижкою не може бути вищою за звичайну.\n"
            "Введіть ціну зі знижкою ще раз."
        )
        return OFFER_PRICE
    context.user_data["new_offer"]["price"] = price
    await update.message.reply_text(
        "Крок 4 з 5 — Введіть кількість наборів.\n"
        "Наприклад: 5"
    )
    return OFFER_QUANTITY


async def offer_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        quantity = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Кількість має бути цілим числом. Наприклад: 5")
        return OFFER_QUANTITY
    if quantity <= 0:
        await update.message.reply_text("Кількість має бути більшою за нуль.")
        return OFFER_QUANTITY
    context.user_data["new_offer"]["quantity"] = quantity
    await update.message.reply_text(
        "Крок 5 з 5 — Введіть час видачі.\n"
        "Наприклад: сьогодні 19:00–20:00"
    )
    return OFFER_PICKUP_TIME


async def offer_pickup_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pickup_time = update.message.text.strip()
    if len(pickup_time) < 3:
        await update.message.reply_text("Введіть час видачі трохи детальніше.")
        return OFFER_PICKUP_TIME
    context.user_data["new_offer"]["pickup_time"] = pickup_time
    await update.message.reply_text(
        "📷 Додайте фото набору — це допоможе покупцям зробити вибір.\n\n"
        "Надішліть фото або натисніть «Пропустити».",
        reply_markup=photo_skip_keyboard(),
    )
    return OFFER_PHOTO


async def _save_new_offer(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_file_id=None):
    new_offer = context.user_data.pop("new_offer", {})
    add_offer(
        owner_telegram_id=update.effective_user.id,
        title=new_offer["title"],
        original_price=new_offer["original_price"],
        price=new_offer["price"],
        quantity=new_offer["quantity"],
        pickup_time=new_offer["pickup_time"],
        photo_file_id=photo_file_id,
    )


async def offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    await _save_new_offer(update, context, photo_file_id=photo_file_id)
    await update.message.reply_text(
        "✅ Пропозицію додано з фото!\n\nПокупці вже можуть її бачити та бронювати.",
        reply_markup=venue_keyboard(),
    )
    return ConversationHandler.END


async def offer_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _save_new_offer(update, context)
    await query.edit_message_text(
        "✅ Пропозицію додано!\n\nПокупці вже можуть її бачити та бронювати.",
        reply_markup=venue_keyboard(),
    )
    return ConversationHandler.END


# ── Buyer flow ────────────────────────────────────────────────────────────────

async def buyer_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "buyer_list_offers":
        offers = list_available_offers()
        if not offers:
            await query.edit_message_text(
                "Поки немає доступних пропозицій. Завітайте трохи пізніше.",
                reply_markup=buyer_keyboard(),
            )
            return
        await query.edit_message_text(
            "🔍 Доступні пропозиції:\n\nОберіть набір, щоб побачити деталі та забронювати.",
            reply_markup=offer_keyboard(offers),
        )


async def show_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    offer_id = int(query.data.split("_")[1])
    offer = get_offer(offer_id)

    if offer is None or offer["quantity"] <= 0:
        await query.edit_message_text(
            "Ця пропозиція вже недоступна.",
            reply_markup=buyer_keyboard(),
        )
        return

    card_text = f"{offer_card_text(offer)}\n\nПідтвердити бронювання?"
    keyboard = booking_confirm_keyboard(offer_id)

    if offer["photo_file_id"]:
        # Відправляємо нове повідомлення з фото, видаляємо попереднє
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.chat.send_photo(
            photo=offer["photo_file_id"],
            caption=card_text,
            reply_markup=keyboard,
        )
    else:
        await query.edit_message_text(card_text, reply_markup=keyboard)


async def confirm_booking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    offer_id = int(query.data.split("_")[1])
    offer = get_offer(offer_id)
    buyer = query.from_user
    buyer_name = buyer.full_name or buyer.username or str(buyer.id)
    booking_id, status = confirm_booking(offer_id, buyer.id, buyer_name)

    if status == "not_found":
        await query.edit_message_text("Пропозицію не знайдено.", reply_markup=buyer_keyboard())
        return

    if status == "sold_out":
        await query.edit_message_text(
            "На жаль, ці набори вже закінчилися.",
            reply_markup=buyer_keyboard(),
        )
        return

    confirmation = booking_confirmation_text(booking_id, offer)

    # Якщо поточне повідомлення з фото — редагуємо підпис; інакше — текст
    if query.message.caption is not None:
        try:
            await query.edit_message_caption(caption=confirmation, reply_markup=buyer_keyboard())
        except Exception:
            await query.message.chat.send_message(confirmation, reply_markup=buyer_keyboard())
    else:
        await query.edit_message_text(confirmation, reply_markup=buyer_keyboard())

    await send_notification(
        bot=context.bot,
        chat_id=offer["venue_owner_telegram_id"],
        text=venue_notification_text(booking_id, offer, buyer_name, buyer.username),
        notification_name="venue",
    )
    await send_notification(
        bot=context.bot,
        chat_id=get_admin_chat_id(),
        text=admin_notification_text(booking_id, offer, buyer),
        notification_name="admin",
    )


# ── Bot setup ─────────────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "🏠 Головна"),
            BotCommand("offers", "🔍 Пропозиції"),
            BotCommand("mybookings", "❤️ Мої бронювання"),
            BotCommand("myvenue", "🏪 Мій заклад"),
            BotCommand("help", "ℹ️ Допомога"),
            BotCommand("myid", "Мій Telegram ID"),
            BotCommand("cancel", "Скасувати поточну дію"),
        ]
    )


def build_application(token):
    application = Application.builder().token(token).post_init(post_init).build()

    conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(choose_role, pattern="^(role_venue|role_buyer|main_menu)$"),
            CallbackQueryHandler(venue_actions, pattern="^venue_"),
        ],
        states={
            REGISTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_name)
            ],
            REGISTER_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_address)
            ],
            REGISTER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_phone)
            ],
            REGISTER_INSTAGRAM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_instagram),
                CallbackQueryHandler(register_venue_instagram_skip, pattern="^skip_instagram$"),
            ],
            REGISTER_CONTACT_PERSON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_contact_person)
            ],
            OFFER_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, offer_title)
            ],
            OFFER_ORIGINAL_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, offer_original_price)
            ],
            OFFER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, offer_price)
            ],
            OFFER_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, offer_quantity)
            ],
            OFFER_PICKUP_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, offer_pickup_time)
            ],
            OFFER_PHOTO: [
                MessageHandler(filters.PHOTO & ~filters.COMMAND, offer_photo),
                CallbackQueryHandler(offer_photo_skip, pattern="^skip_photo$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("offers", offers_command))
    application.add_handler(CommandHandler("mybookings", mybookings_command))
    application.add_handler(CommandHandler("myvenue", myvenue_command))
    application.add_handler(conversation)
    application.add_handler(CallbackQueryHandler(buyer_actions, pattern="^buyer_list_offers$"))
    application.add_handler(CallbackQueryHandler(show_offer, pattern="^offer_[0-9]+$"))
    application.add_handler(
        CallbackQueryHandler(confirm_booking_callback, pattern="^confirm_[0-9]+$")
    )

    return application


def run():
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN не задано у файлі .env")
    init_db()
    application = build_application(token)
    application.run_polling()


if __name__ == "__main__":
    run()
