import logging
import os
from datetime import datetime, time as dt_time, timezone, timedelta

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
    VENUE_CATEGORIES,
    activate_template_today,
    add_offer,
    add_offer_by_venue_id,
    admin_add_venue,
    admin_delete_venue,
    admin_update_venue,
    confirm_booking,
    create_or_update_venue,
    create_template,
    delete_template,
    deactivate_template_today,
    get_all_venue_owner_ids,
    get_all_venues,
    get_offer,
    get_stats,
    get_template,
    get_templates_for_venue,
    get_venue_by_id,
    get_venue_by_telegram_id,
    init_db,
    is_template_active_today,
    link_venue_to_owner,
    list_available_offers,
    list_buyer_bookings,
    list_venue_offers,
    reset_expired_template_offers,
    update_template,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ── Conversation state constants ───────────────────────────────────────────────

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

(
    ADMIN_ADD_NAME,
    ADMIN_ADD_CATEGORY,
    ADMIN_ADD_ADDRESS,
    ADMIN_ADD_PHONE,
    ADMIN_ADD_INSTAGRAM,
    ADMIN_ADD_DESCRIPTION,
    ADMIN_ADD_PICKUP,
    ADMIN_EDIT_FIELD,
    ADMIN_EDIT_VALUE,
    ADMIN_LINK_TELEGRAM,
    ADMIN_OFFER_TITLE,
    ADMIN_OFFER_ORIG,
    ADMIN_OFFER_PRICE,
    ADMIN_OFFER_QTY,
    ADMIN_OFFER_TIME,
    ADMIN_OFFER_PHOTO,
) = range(20, 36)

# Template conversation states
(
    TEMPLATE_TITLE,
    TEMPLATE_ORIG_PRICE,
    TEMPLATE_PRICE,
    TEMPLATE_PICKUP_TIME,
    TEMPLATE_DESCRIPTION,
    TEMPLATE_PHOTO,
    TEMPLATE_ACTIVATE_QTY,
    TEMPLATE_EDIT_FIELD,
    TEMPLATE_EDIT_VALUE,
) = range(40, 49)

# ── Seed data — всі 23 заклади ────────────────────────────────────────────────
SEED_VENUES = [
    # ФОП Софія
    {"name": "Very Tasty Cafe",        "category": "☕ Кафе"},
    {"name": "Salad Bar & Kitchen",    "category": "🥗 Салат-бар"},
    {"name": "Pasta Milano",           "category": "🍝 Паста / Ризото"},
    {"name": "Delux Burger",           "category": "🍔 Бургери"},
    {"name": "Trattoria Napole",       "category": "🍕 Піца"},
    # ФОП Плясунова
    {"name": "Steak & Grill",          "category": "🥩 М'ясо / Гриль"},
    {"name": "Frutti del Mare",        "category": "🦞 Морепродукти"},
    {"name": "Salateria Verde",        "category": "🥗 Салат-бар"},
    {"name": "Brooklyn Pizza",         "category": "🍕 Піца"},
    {"name": "The Burger Launch",      "category": "🍔 Бургери"},
    # ФОП Матвій
    {"name": "Pizza della Mozzarella", "category": "🍕 Піца"},
    {"name": "Pizza54",                "category": "🍕 Піца"},
    {"name": "Salad & Fresh",          "category": "🥗 Салат-бар"},
    {"name": "La Pasta Italiano",      "category": "🍝 Паста / Ризото"},
    {"name": "BIG Burger",             "category": "🍔 Бургери"},
    {"name": "Fish & Grill",           "category": "🦞 Морепродукти"},
    # ФОП Андрей
    {"name": "Паста По-Київськи",      "category": "🍝 Паста / Ризото"},
    {"name": "Pasta La Pepito",        "category": "🍝 Паста / Ризото"},
    {"name": "Beef & Grill",           "category": "🥩 М'ясо / Гриль"},
    {"name": "Шніцель Хауз",           "category": "🥩 М'ясо / Гриль"},
    {"name": "Pizza De Monte",         "category": "🍕 Піца"},
    {"name": "Pasta De Monte",         "category": "🍝 Паста / Ризото"},
    {"name": "Sea Food Bar & Kitchen", "category": "🦞 Морепродукти"},
]

WELCOME_TEXT = (
    "🍽️ Ласкаво просимо до LuckyMeal\n\n"
    "Допомагаємо рятувати якісну їжу від списання та знаходити вигідні пропозиції поруч.\n\n"
    "Оберіть роль:"
)

# Ukraine is permanently UTC+3 (no DST since 2022)
_KYIV_TZ = timezone(timedelta(hours=3))


# ── Helpers ────────────────────────────────────────────────────────────────────

def format_price(value):
    return f"{value:.0f} грн"


def discount_percent(original_price, price):
    if original_price <= 0:
        return 0
    return max(round((original_price - price) / original_price * 100), 0)


def get_admin_chat_id():
    return os.getenv("ADMIN_CHAT_ID")


def is_admin(user_id):
    admin_id = get_admin_chat_id()
    return bool(admin_id and str(user_id) == str(admin_id))


def venue_profile_is_complete(venue):
    return all(venue[f] for f in ("name", "address", "phone", "contact_person"))


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
        "Будь ласка, прийдіть до закладу у вказаний час та покажіть це повідомлення.",
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
        f"Телефон: {offer['venue_phone'] or 'не вказано'}\n\n"
        f"Набір: {offer['title']}\n"
        f"Ціна: {format_price(offer['price'])}\n"
        f"Час видачі: {offer['pickup_time']}\n\n"
        f"Покупець: {buyer.full_name}\n"
        f"Telegram ID: {buyer.id}\n"
        f"Username: {buyer_username}"
    )


async def send_notification(bot, chat_id, text, notification_name):
    if not chat_id:
        return False
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as error:
        logging.warning("Could not send %s notification: %s", notification_name, error)
        return False


def venue_info_text(venue):
    status_label = "✅ Активний" if venue["status"] == "active" else "⏸ Неактивний"
    pickup_label = "Так" if venue["pickup"] else "Ні"
    managed_label = " (адмін управляє)" if venue["admin_managed"] else ""
    lines = [
        f"🏪 {venue['name']}{managed_label}",
        f"📂 {venue['category'] or '—'}",
        f"📍 {venue['address'] or '—'}",
        f"📞 {venue['phone'] or '—'}",
        f"📷 {venue['instagram'] or '—'}",
        f"👤 {venue['contact_person'] or '—'}",
        f"📝 {venue['description'] or '—'}",
        f"🚶 Самовивіз: {pickup_label}",
        f"📊 Статус: {status_label}",
    ]
    return "\n".join(lines)


def template_card_text(t):
    is_active = is_template_active_today(t["id"])
    status = "🟢 Активний сьогодні" if is_active else "⚫ Неактивний"
    discount = discount_percent(t["original_price"], t["price"])
    lines = [
        f"📦 {t['title']}",
        "",
        f"💰 LuckyMeal: {format_price(t['price'])}",
        f"💸 Звичайна: {format_price(t['original_price'])}",
        f"📉 Знижка: {discount}%",
        f"🕒 Час видачі: {t['pickup_time']}",
    ]
    if t["description"]:
        lines.append(f"📝 {t['description']}")
    lines.append(f"\nСтатус: {status}")
    return "\n".join(lines)


# ── Keyboards ──────────────────────────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Я покупець", callback_data="role_buyer"),
            InlineKeyboardButton("Я заклад",   callback_data="role_venue"),
        ],
    ])


def venue_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати пропозицію",  callback_data="venue_add_offer")],
        [
            InlineKeyboardButton("📦 Мої шаблони",     callback_data="tmpl_list"),
            InlineKeyboardButton("📋 Мої пропозиції",  callback_data="venue_my_offers"),
        ],
        [InlineKeyboardButton("🏠 Головне меню",       callback_data="main_menu")],
    ])


def buyer_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Переглянути пропозиції", callback_data="buyer_list_offers")],
        [InlineKeyboardButton("🏠 Головне меню",           callback_data="main_menu")],
    ])


def offer_keyboard(offers):
    buttons = []
    for offer in offers:
        discount = discount_percent(offer["original_price"], offer["price"])
        text = f"{offer['venue_name']} — {format_price(offer['price'])} (−{discount}%)"
        buttons.append([InlineKeyboardButton(text, callback_data=f"offer_{offer['id']}")])
    buttons.append([InlineKeyboardButton("← Назад", callback_data="role_buyer")])
    return InlineKeyboardMarkup(buttons)


def booking_confirm_keyboard(offer_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити бронювання", callback_data=f"confirm_{offer_id}")],
        [InlineKeyboardButton("← Назад до списку",         callback_data="buyer_list_offers")],
    ])


def photo_skip_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Пропустити →", callback_data="skip_photo")]
    ])


def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати заклад",  callback_data="adm_add")],
        [InlineKeyboardButton("📋 Всі заклади",    callback_data="adm_list")],
        [InlineKeyboardButton("📊 Статистика",     callback_data="adm_stats")],
    ])


def admin_venues_keyboard(venues):
    buttons = []
    for v in venues:
        status_icon  = "✅" if v["status"] == "active" else "⏸"
        managed_icon = "🔧" if v["admin_managed"] else ""
        label = f"{status_icon}{managed_icon} {v['name']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"adm_venue_{v['id']}")])
    buttons.append([InlineKeyboardButton("← Меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(buttons)


def admin_venue_detail_keyboard(venue_id, status):
    toggle_label = "⏸ Деактивувати" if status == "active" else "✅ Активувати"
    toggle_cb    = f"adm_deactivate_{venue_id}" if status == "active" else f"adm_activate_{venue_id}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Редагувати",          callback_data=f"adm_edit_{venue_id}")],
        [InlineKeyboardButton("➕ Додати пропозицію",   callback_data=f"adm_offer_{venue_id}")],
        [InlineKeyboardButton("🔗 Прив'язати власника", callback_data=f"adm_link_{venue_id}")],
        [InlineKeyboardButton(toggle_label,             callback_data=toggle_cb)],
        [InlineKeyboardButton("🗑️ Видалити",            callback_data=f"adm_del_{venue_id}")],
        [InlineKeyboardButton("← Список закладів",     callback_data="adm_list")],
    ])


def admin_edit_fields_keyboard(venue_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Назва",    callback_data=f"adm_ef_name_{venue_id}"),
         InlineKeyboardButton("Категорія", callback_data=f"adm_ef_category_{venue_id}")],
        [InlineKeyboardButton("Адреса",   callback_data=f"adm_ef_address_{venue_id}"),
         InlineKeyboardButton("Телефон",  callback_data=f"adm_ef_phone_{venue_id}")],
        [InlineKeyboardButton("Instagram", callback_data=f"adm_ef_instagram_{venue_id}"),
         InlineKeyboardButton("Контакт",  callback_data=f"adm_ef_contact_person_{venue_id}")],
        [InlineKeyboardButton("Опис",     callback_data=f"adm_ef_description_{venue_id}")],
        [InlineKeyboardButton("← Назад",  callback_data=f"adm_venue_{venue_id}")],
    ])


def category_keyboard(prefix="adm_cat"):
    buttons = []
    for i in range(0, len(VENUE_CATEGORIES), 2):
        row = [InlineKeyboardButton(VENUE_CATEGORIES[i], callback_data=f"{prefix}_{i}")]
        if i + 1 < len(VENUE_CATEGORIES):
            row.append(InlineKeyboardButton(VENUE_CATEGORIES[i + 1], callback_data=f"{prefix}_{i + 1}"))
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def pickup_keyboard(prefix="adm_pickup"):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Так", callback_data=f"{prefix}_yes"),
            InlineKeyboardButton("❌ Ні",  callback_data=f"{prefix}_no"),
        ]
    ])


def skip_keyboard(callback_data):
    return InlineKeyboardMarkup([[InlineKeyboardButton("Пропустити →", callback_data=callback_data)]])


# ── Template keyboards ─────────────────────────────────────────────────────────

def templates_list_keyboard(templates):
    buttons = []
    for t in templates:
        active = is_template_active_today(t["id"])
        status = "🟢" if active else "⚫"
        label  = f"{status} {t['title']} — {format_price(t['price'])}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"tmpl_view_{t['id']}")])
    buttons.append([InlineKeyboardButton("➕ Новий шаблон",  callback_data="tmpl_create")])
    buttons.append([InlineKeyboardButton("← Назад",          callback_data="tmpl_back_venue")])
    return InlineKeyboardMarkup(buttons)


def template_detail_keyboard(template_id, is_active):
    if is_active:
        toggle = InlineKeyboardButton(
            "⏸️ Деактивувати", callback_data=f"tmpl_deactivate_{template_id}"
        )
    else:
        toggle = InlineKeyboardButton(
            "▶️ Активувати сьогодні", callback_data=f"tmpl_activate_{template_id}"
        )
    return InlineKeyboardMarkup([
        [toggle],
        [InlineKeyboardButton("✏️ Редагувати", callback_data=f"tmpl_edit_{template_id}")],
        [InlineKeyboardButton("🗑️ Видалити",   callback_data=f"tmpl_del_{template_id}")],
        [InlineKeyboardButton("← Шаблони",    callback_data="tmpl_list")],
    ])


def template_edit_fields_keyboard(template_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Назва",         callback_data=f"tmpl_ef_title_{template_id}"),
         InlineKeyboardButton("Час видачі",    callback_data=f"tmpl_ef_pickup_time_{template_id}")],
        [InlineKeyboardButton("Звичайна ціна", callback_data=f"tmpl_ef_original_price_{template_id}"),
         InlineKeyboardButton("LuckyMeal ціна", callback_data=f"tmpl_ef_price_{template_id}")],
        [InlineKeyboardButton("Опис",          callback_data=f"tmpl_ef_description_{template_id}")],
        [InlineKeyboardButton("← Назад",       callback_data=f"tmpl_view_{template_id}")],
    ])


# ── Standard commands ──────────────────────────────────────────────────────────

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
        "• /start — головне меню\n"
        "• /myid — ваш Telegram ID\n"
        "• /cancel — скасувати поточну дію"
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш Telegram ID: {update.effective_user.id}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Дію скасовано.\n\nЩоб повернутися — натисніть /start")
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
        lines.append(
            f"#{b['booking_id']} {b['venue_name']}\n"
            f"🍽️ {b['offer_title']}\n"
            f"💰 {format_price(b['price'])}\n"
            f"🕒 {b['pickup_time']}\n"
            f"📍 {b['venue_address'] or 'адреса не вказана'}\n"
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


# ── Role selection ─────────────────────────────────────────────────────────────

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
                "📝 Реєстрація закладу\n\nКрок 1 з 5 — Введіть назву закладу."
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
        await update.message.reply_text("Назва занадто коротка. Введіть ще раз.")
        return REGISTER_NAME
    context.user_data["new_venue"]["name"] = name
    await update.message.reply_text(
        "📝 Крок 2 з 5 — Введіть адресу закладу.\nНаприклад: Київ, вул. Ярославська, 12"
    )
    return REGISTER_ADDRESS


async def register_venue_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    address = update.message.text.strip()
    if len(address) < 5:
        await update.message.reply_text("Адреса занадто коротка. Введіть повну адресу.")
        return REGISTER_ADDRESS
    context.user_data["new_venue"]["address"] = address
    await update.message.reply_text(
        "📝 Крок 3 з 5 — Введіть телефон закладу.\nНаприклад: +380671234567"
    )
    return REGISTER_PHONE


async def register_venue_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    if sum(c.isdigit() for c in phone) < 10:
        await update.message.reply_text("Схоже, номер неповний. Введіть ще раз.")
        return REGISTER_PHONE
    context.user_data["new_venue"]["phone"] = phone
    await update.message.reply_text(
        "📝 Крок 4 з 5 — Введіть Instagram (необов'язково).",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Пропустити →", callback_data="skip_instagram")]]
        ),
    )
    return REGISTER_INSTAGRAM


async def register_venue_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_venue"]["instagram"] = update.message.text.strip()
    await update.message.reply_text("📝 Крок 5 з 5 — Введіть ім'я контактної особи.")
    return REGISTER_CONTACT_PERSON


async def register_venue_instagram_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_venue"]["instagram"] = None
    await query.edit_message_text("📝 Крок 5 з 5 — Введіть ім'я контактної особи.")
    return REGISTER_CONTACT_PERSON


async def register_venue_contact_person(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_person = update.message.text.strip()
    if len(contact_person) < 2:
        await update.message.reply_text("Ім'я занадто коротке. Введіть ще раз.")
        return REGISTER_CONTACT_PERSON

    nv = context.user_data["new_venue"]
    create_or_update_venue(
        owner_telegram_id=update.effective_user.id,
        name=nv["name"],
        address=nv["address"],
        phone=nv["phone"],
        instagram=nv.get("instagram"),
        contact_person=contact_person,
    )
    context.user_data.pop("new_venue", None)
    instagram_line = f"📷 {nv['instagram']}\n" if nv.get("instagram") else ""
    await update.message.reply_text(
        f"✅ Профіль закладу створено!\n\n"
        f"🏪 {nv['name']}\n📍 {nv['address']}\n📞 {nv['phone']}\n{instagram_line}👤 {contact_person}",
        reply_markup=venue_keyboard(),
    )
    return ConversationHandler.END


# ── Venue actions (offer add / my offers) ─────────────────────────────────────

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
            "➕ Нова пропозиція\n\nКрок 1 з 5 — Введіть назву набору.\nНаприклад: Вечірній мікс випічки"
        )
        return OFFER_TITLE

    if query.data == "venue_my_offers":
        offers = list_venue_offers(query.from_user.id)
        if not offers:
            await query.edit_message_text("📋 У вас поки немає активних пропозицій.", reply_markup=venue_keyboard())
            return ConversationHandler.END
        lines = ["📋 Ваші пропозиції:\n"]
        for o in offers:
            photo_note = " 📷" if o["photo_file_id"] else ""
            lines.append(
                f"#{o['id']} {o['title']}{photo_note}\n"
                f"💰 {format_price(o['price'])} (звичайна: {format_price(o['original_price'])})\n"
                f"📉 {discount_percent(o['original_price'], o['price'])}%\n"
                f"📦 Залишилось: {o['quantity']}\n"
                f"🕒 {o['pickup_time']}\n"
            )
        await query.edit_message_text("\n".join(lines), reply_markup=venue_keyboard())
        return ConversationHandler.END

    return ConversationHandler.END


# ── Offer creation (venue owner) ───────────────────────────────────────────────

async def offer_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if len(title) < 3:
        await update.message.reply_text("Назва занадто коротка. Введіть ще раз.")
        return OFFER_TITLE
    context.user_data["new_offer"]["title"] = title
    await update.message.reply_text(
        "Крок 2 з 5 — Введіть звичайну ціну набору в гривнях.\nНаприклад: 600"
    )
    return OFFER_ORIGINAL_PRICE


async def offer_original_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        original_price = float(update.message.text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Ціна має бути числом. Наприклад: 600")
        return OFFER_ORIGINAL_PRICE
    if original_price <= 0:
        await update.message.reply_text("Ціна має бути більшою за нуль.")
        return OFFER_ORIGINAL_PRICE
    context.user_data["new_offer"]["original_price"] = original_price
    await update.message.reply_text("Крок 3 з 5 — Введіть ціну зі знижкою.\nНаприклад: 300")
    return OFFER_PRICE


async def offer_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = float(update.message.text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Ціна має бути числом. Наприклад: 300")
        return OFFER_PRICE
    if price <= 0:
        await update.message.reply_text("Ціна має бути більшою за нуль.")
        return OFFER_PRICE
    if price > context.user_data["new_offer"]["original_price"]:
        await update.message.reply_text("Ціна зі знижкою не може бути вищою за звичайну.")
        return OFFER_PRICE
    context.user_data["new_offer"]["price"] = price
    await update.message.reply_text("Крок 4 з 5 — Введіть кількість наборів.\nНаприклад: 5")
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
        "Крок 5 з 5 — Введіть час видачі.\nНаприклад: сьогодні 19:00–20:00"
    )
    return OFFER_PICKUP_TIME


async def offer_pickup_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pickup_time = update.message.text.strip()
    if len(pickup_time) < 3:
        await update.message.reply_text("Введіть час видачі трохи детальніше.")
        return OFFER_PICKUP_TIME
    context.user_data["new_offer"]["pickup_time"] = pickup_time
    await update.message.reply_text(
        "📷 Додайте фото набору або натисніть «Пропустити».",
        reply_markup=photo_skip_keyboard(),
    )
    return OFFER_PHOTO


async def _save_new_offer(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_file_id=None):
    new_offer = context.user_data.pop("new_offer", {})
    venue_id  = context.user_data.pop("admin_offer_venue_id", None)
    if venue_id:
        add_offer_by_venue_id(venue_id, new_offer["title"], new_offer["original_price"],
                              new_offer["price"], new_offer["quantity"],
                              new_offer["pickup_time"], photo_file_id)
    else:
        add_offer(owner_telegram_id=update.effective_user.id, title=new_offer["title"],
                  original_price=new_offer["original_price"], price=new_offer["price"],
                  quantity=new_offer["quantity"], pickup_time=new_offer["pickup_time"],
                  photo_file_id=photo_file_id)


async def offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    await _save_new_offer(update, context, photo_file_id=photo_file_id)
    await update.message.reply_text(
        "✅ Пропозицію додано з фото! Покупці вже можуть її бачити.",
        reply_markup=venue_keyboard(),
    )
    return ConversationHandler.END


async def offer_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _save_new_offer(update, context)
    await query.edit_message_text(
        "✅ Пропозицію додано! Покупці вже можуть її бачити.",
        reply_markup=venue_keyboard(),
    )
    return ConversationHandler.END


# ── Buyer flow ─────────────────────────────────────────────────────────────────

async def buyer_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "buyer_list_offers":
        offers = list_available_offers()
        if not offers:
            await query.edit_message_text(
                "Поки немає доступних пропозицій.", reply_markup=buyer_keyboard()
            )
            return
        await query.edit_message_text(
            "🔍 Доступні пропозиції:\n\nОберіть набір, щоб побачити деталі.",
            reply_markup=offer_keyboard(offers),
        )


async def show_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    offer_id = int(query.data.split("_")[1])
    offer = get_offer(offer_id)
    if offer is None or offer["quantity"] <= 0:
        await query.edit_message_text("Ця пропозиція вже недоступна.", reply_markup=buyer_keyboard())
        return
    card_text = f"{offer_card_text(offer)}\n\nПідтвердити бронювання?"
    keyboard   = booking_confirm_keyboard(offer_id)
    if offer["photo_file_id"]:
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.chat.send_photo(
            photo=offer["photo_file_id"], caption=card_text, reply_markup=keyboard
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
            "На жаль, ці набори вже закінчилися.", reply_markup=buyer_keyboard()
        )
        return

    confirmation = booking_confirmation_text(booking_id, offer)
    if query.message.caption is not None:
        try:
            await query.edit_message_caption(caption=confirmation, reply_markup=buyer_keyboard())
        except Exception:
            await query.message.chat.send_message(confirmation, reply_markup=buyer_keyboard())
    else:
        await query.edit_message_text(confirmation, reply_markup=buyer_keyboard())

    await send_notification(context.bot, offer["venue_owner_telegram_id"],
                            venue_notification_text(booking_id, offer, buyer_name, buyer.username),
                            "venue")
    await send_notification(context.bot, get_admin_chat_id(),
                            admin_notification_text(booking_id, offer, buyer), "admin")


# ══════════════════════════════════════════════════════════════════════════════
#  TEMPLATE SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

async def _show_templates_list(query_or_message, user_id, edit=True):
    """Helper: show templates list to the owner. query_or_message can be query or message."""
    venue = get_venue_by_telegram_id(user_id)
    if not venue:
        text = "Заклад не знайдено."
        if edit:
            await query_or_message.edit_message_text(text)
        else:
            await query_or_message.reply_text(text)
        return

    templates = get_templates_for_venue(venue["id"])
    if not templates:
        text = (
            "📦 Мої шаблони\n\n"
            "У вас ще немає шаблонів.\n\n"
            "Шаблон — це збережений набір, який можна активувати щодня одним натиском.\n"
            "Щоденно о 17:00 бот нагадає вам активувати набори."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Створити шаблон",  callback_data="tmpl_create")],
            [InlineKeyboardButton("← Назад",             callback_data="tmpl_back_venue")],
        ])
    else:
        text = "📦 Мої шаблони\n\n🟢 активний сьогодні  ⚫ неактивний"
        kb   = templates_list_keyboard(templates)

    if edit:
        await query_or_message.edit_message_text(text, reply_markup=kb)
    else:
        await query_or_message.reply_text(text, reply_markup=kb)


async def template_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all tmpl_* callbacks that don't require text input."""
    query   = update.callback_query
    await query.answer()
    data    = query.data
    user_id = query.from_user.id

    # ── List ──────────────────────────────────────────────────────────────────
    if data == "tmpl_list":
        await _show_templates_list(query, user_id, edit=True)
        return ConversationHandler.END

    # ── Back to venue menu ────────────────────────────────────────────────────
    if data == "tmpl_back_venue":
        venue = get_venue_by_telegram_id(user_id)
        if venue:
            instagram_line = f"📷 {venue['instagram']}\n" if venue["instagram"] else ""
            await query.edit_message_text(
                f"🏪 {venue['name']}\n"
                f"📍 {venue['address'] or '—'}\n"
                f"📞 {venue['phone'] or '—'}\n"
                f"{instagram_line}"
                f"👤 {venue['contact_person'] or '—'}",
                reply_markup=venue_keyboard(),
            )
        return ConversationHandler.END

    # ── View template detail ──────────────────────────────────────────────────
    if data.startswith("tmpl_view_"):
        template_id = int(data.split("_")[2])
        t = get_template(template_id)
        if not t:
            await query.edit_message_text("Шаблон не знайдено.")
            return ConversationHandler.END
        is_active = is_template_active_today(template_id)
        await query.edit_message_text(
            template_card_text(t),
            reply_markup=template_detail_keyboard(template_id, is_active),
        )
        return ConversationHandler.END

    # ── Deactivate ────────────────────────────────────────────────────────────
    if data.startswith("tmpl_deactivate_"):
        template_id = int(data.split("_")[2])
        deactivate_template_today(template_id)
        t = get_template(template_id)
        title = t["title"] if t else ""
        await query.edit_message_text(
            f"⏸️ «{title}» деактивовано на сьогодні.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← Шаблони", callback_data="tmpl_list")],
            ]),
        )
        return ConversationHandler.END

    # ── Delete (confirm) ──────────────────────────────────────────────────────
    if data.startswith("tmpl_del_") and not data.startswith("tmpl_delconfirm_"):
        template_id = int(data.split("_")[2])
        t = get_template(template_id)
        name = t["title"] if t else "?"
        await query.edit_message_text(
            f"⚠️ Видалити шаблон «{name}»?\n\nАктивна пропозиція на сьогодні також скасується.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Так, видалити", callback_data=f"tmpl_delconfirm_{template_id}")],
                [InlineKeyboardButton("← Назад",           callback_data=f"tmpl_view_{template_id}")],
            ]),
        )
        return ConversationHandler.END

    # ── Delete (confirm) ──────────────────────────────────────────────────────
    if data.startswith("tmpl_delconfirm_"):
        template_id = int(data.split("_")[2])
        delete_template(template_id)
        await query.edit_message_text(
            "✅ Шаблон видалено.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("← Мої шаблони", callback_data="tmpl_list")],
            ]),
        )
        return ConversationHandler.END

    # ── Start create template ─────────────────────────────────────────────────
    if data == "tmpl_create":
        venue = get_venue_by_telegram_id(user_id)
        if not venue:
            await query.edit_message_text("Заклад не знайдено. Зареєструйтесь через /start.")
            return ConversationHandler.END
        context.user_data["new_template"] = {"venue_id": venue["id"]}
        await query.edit_message_text(
            "📦 Новий шаблон\n\nКрок 1 з 4 — Введіть назву набору.\nНаприклад: Паста-сет вечірній"
        )
        return TEMPLATE_TITLE

    # ── Start activate template ───────────────────────────────────────────────
    if data.startswith("tmpl_activate_"):
        template_id = int(data.split("_")[2])
        t = get_template(template_id)
        if not t:
            await query.edit_message_text("Шаблон не знайдено.")
            return ConversationHandler.END
        context.user_data["activate_template_id"] = template_id
        context.user_data["activate_from_reminder"] = False
        await query.edit_message_text(
            f"▶️ Активувати «{t['title']}»\n\nСкільки наборів доступно сьогодні?"
        )
        return TEMPLATE_ACTIVATE_QTY

    # ── Start edit template ───────────────────────────────────────────────────
    if data.startswith("tmpl_edit_"):
        template_id = int(data.split("_")[2])
        context.user_data["edit_template_id"] = template_id
        await query.edit_message_text(
            "✏️ Що хочете змінити?",
            reply_markup=template_edit_fields_keyboard(template_id),
        )
        return TEMPLATE_EDIT_FIELD

    # ── Field selection during edit ───────────────────────────────────────────
    if data.startswith("tmpl_ef_"):
        parts = data.split("_")
        # format: tmpl_ef_{field}_{template_id}
        # field might be multi-word like original_price → parts[2] + parts[3] before last
        template_id = int(parts[-1])
        field       = "_".join(parts[2:-1])
        context.user_data["edit_template_id"]    = template_id
        context.user_data["edit_template_field"] = field

        field_labels = {
            "title":          "назву",
            "original_price": "звичайну ціну (грн)",
            "price":          "ціну LuckyMeal (грн)",
            "pickup_time":    "час видачі",
            "description":    "опис",
        }
        await query.edit_message_text(
            f"Введіть нову {field_labels.get(field, field)}:"
        )
        return TEMPLATE_EDIT_VALUE

    return ConversationHandler.END


# ── Template conversation state handlers ───────────────────────────────────────

async def template_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.strip()
    if len(title) < 2:
        await update.message.reply_text("Назва занадто коротка. Введіть ще раз.")
        return TEMPLATE_TITLE
    context.user_data["new_template"]["title"] = title
    await update.message.reply_text(
        "Крок 2 з 4 — Введіть звичайну ціну набору (грн).\nНаприклад: 760"
    )
    return TEMPLATE_ORIG_PRICE


async def template_orig_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введіть число. Наприклад: 760")
        return TEMPLATE_ORIG_PRICE
    if val <= 0:
        await update.message.reply_text("Ціна має бути більшою за нуль.")
        return TEMPLATE_ORIG_PRICE
    context.user_data["new_template"]["original_price"] = val
    await update.message.reply_text(
        "Крок 3 з 4 — Введіть ціну LuckyMeal (грн).\nНаприклад: 380"
    )
    return TEMPLATE_PRICE


async def template_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = float(update.message.text.strip().replace(",", "."))
    except ValueError:
        await update.message.reply_text("Введіть число. Наприклад: 380")
        return TEMPLATE_PRICE
    if val <= 0:
        await update.message.reply_text("Ціна має бути більшою за нуль.")
        return TEMPLATE_PRICE
    if val > context.user_data["new_template"]["original_price"]:
        await update.message.reply_text("Ціна LuckyMeal не може бути вищою за звичайну.")
        return TEMPLATE_PRICE
    context.user_data["new_template"]["price"] = val
    await update.message.reply_text(
        "Крок 4 з 4 — Введіть час видачі.\nНаприклад: 20:00–21:00"
    )
    return TEMPLATE_PICKUP_TIME


async def template_pickup_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    val = update.message.text.strip()
    if len(val) < 3:
        await update.message.reply_text("Введіть час видачі трохи детальніше.")
        return TEMPLATE_PICKUP_TIME
    context.user_data["new_template"]["pickup_time"] = val
    await update.message.reply_text(
        "📝 Додайте короткий опис набору (необов'язково).",
        reply_markup=skip_keyboard("tmpl_skip_description"),
    )
    return TEMPLATE_DESCRIPTION


async def template_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_template"]["description"] = update.message.text.strip() or None
    await update.message.reply_text(
        "📷 Надішліть фото набору (необов'язково).",
        reply_markup=skip_keyboard("tmpl_skip_photo"),
    )
    return TEMPLATE_PHOTO


async def template_description_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_template"]["description"] = None
    await query.edit_message_text(
        "📷 Надішліть фото набору (необов'язково).",
        reply_markup=skip_keyboard("tmpl_skip_photo"),
    )
    return TEMPLATE_PHOTO


async def _save_new_template(update: Update, context: ContextTypes.DEFAULT_TYPE, photo_file_id=None):
    nt = context.user_data.pop("new_template", {})
    template_id = create_template(
        venue_id       = nt["venue_id"],
        title          = nt["title"],
        original_price = nt["original_price"],
        price          = nt["price"],
        pickup_time    = nt["pickup_time"],
        photo_file_id  = photo_file_id,
        description    = nt.get("description"),
    )
    return template_id


async def template_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    template_id   = await _save_new_template(update, context, photo_file_id=photo_file_id)
    t = get_template(template_id)
    await update.message.reply_text(
        f"✅ Шаблон «{t['title']}» збережено!\n\n"
        f"Тепер ви можете активувати його щодня через «📦 Мої шаблони».\n"
        f"О 17:00 бот надішле нагадування.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Мої шаблони", callback_data="tmpl_list")],
        ]),
    )
    return ConversationHandler.END


async def template_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    template_id = await _save_new_template(update, context)
    t = get_template(template_id)
    await query.edit_message_text(
        f"✅ Шаблон «{t['title']}» збережено!\n\n"
        f"Тепер ви можете активувати його щодня через «📦 Мої шаблони».\n"
        f"О 17:00 бот надішле нагадування.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Мої шаблони", callback_data="tmpl_list")],
        ]),
    )
    return ConversationHandler.END


async def template_activate_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        qty = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Кількість має бути числом. Наприклад: 5")
        return TEMPLATE_ACTIVATE_QTY
    if qty <= 0:
        await update.message.reply_text("Кількість має бути більшою за нуль.")
        return TEMPLATE_ACTIVATE_QTY

    template_id   = context.user_data.pop("activate_template_id", None)
    from_reminder = context.user_data.pop("activate_from_reminder", False)

    if not template_id:
        await update.message.reply_text("Помилка: шаблон не знайдено. Спробуйте ще раз.")
        return ConversationHandler.END

    activate_template_today(template_id, qty)
    t = get_template(template_id)
    title = t["title"] if t else ""

    await update.message.reply_text(
        f"✅ Опубліковано! {qty} наборів «{title}» доступні для замовлення "
        f"о {t['pickup_time'] if t else ''}.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Мої шаблони", callback_data="tmpl_list")],
        ]),
    )

    if from_reminder:
        # Show remaining inactive templates for the reminder flow
        venue = get_venue_by_telegram_id(update.effective_user.id)
        if venue:
            remaining = [
                tmpl for tmpl in get_templates_for_venue(venue["id"])
                if not is_template_active_today(tmpl["id"])
            ]
            if remaining:
                buttons = []
                for tmpl in remaining:
                    buttons.append([InlineKeyboardButton(
                        f"▶️ {tmpl['title']}", callback_data=f"tmpl_reminder_activate_{tmpl['id']}"
                    )])
                buttons.append([InlineKeyboardButton("✅ Готово", callback_data="tmpl_reminder_done")])
                await update.message.reply_text(
                    "Ще є неактивні шаблони. Бажаєте активувати?",
                    reply_markup=InlineKeyboardMarkup(buttons),
                )

    return ConversationHandler.END


async def template_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field       = context.user_data.pop("edit_template_field", None)
    template_id = context.user_data.pop("edit_template_id",    None)
    value       = update.message.text.strip()

    if not field or not template_id:
        await update.message.reply_text("Помилка. Спробуйте ще раз через «📦 Мої шаблони».")
        return ConversationHandler.END

    # Convert numeric fields
    if field in ("original_price", "price"):
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            await update.message.reply_text("Введіть число.")
            return TEMPLATE_EDIT_VALUE

    update_template(template_id, **{field: value})
    t = get_template(template_id)
    await update.message.reply_text(
        f"✅ Оновлено!\n\n{template_card_text(t)}",
        reply_markup=template_detail_keyboard(template_id, is_template_active_today(template_id)),
    )
    return ConversationHandler.END


# ── Reminder callbacks ─────────────────────────────────────────────────────────

async def reminder_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles reminder_yes / reminder_no / tmpl_reminder_* callbacks."""
    query   = update.callback_query
    await query.answer()
    data    = query.data
    user_id = query.from_user.id

    if data == "reminder_no":
        await query.edit_message_text(
            "Зрозуміло! Якщо передумаєте — відкрийте /myvenue → 📦 Мої шаблони."
        )
        return ConversationHandler.END

    if data == "reminder_done" or data == "tmpl_reminder_done":
        venue = get_venue_by_telegram_id(user_id)
        templates = get_templates_for_venue(venue["id"]) if venue else []
        active_count = sum(1 for t in templates if is_template_active_today(t["id"]))
        await query.edit_message_text(
            f"✅ Готово! Сьогодні активних наборів: {active_count}.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Мої шаблони", callback_data="tmpl_list")],
            ]),
        )
        return ConversationHandler.END

    if data == "reminder_yes":
        venue = get_venue_by_telegram_id(user_id)
        if not venue:
            await query.edit_message_text("Заклад не знайдено.")
            return ConversationHandler.END
        templates = get_templates_for_venue(venue["id"])
        inactive  = [t for t in templates if not is_template_active_today(t["id"])]
        if not inactive:
            await query.edit_message_text(
                "🟢 Всі шаблони вже активні сьогодні!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 Мої шаблони", callback_data="tmpl_list")],
                ]),
            )
            return ConversationHandler.END
        buttons = []
        for t in inactive:
            buttons.append([InlineKeyboardButton(
                f"▶️ {t['title']} — {format_price(t['price'])}",
                callback_data=f"tmpl_reminder_activate_{t['id']}"
            )])
        buttons.append([InlineKeyboardButton("❌ Пропустити", callback_data="tmpl_reminder_done")])
        await query.edit_message_text(
            "Оберіть шаблони для активації:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return ConversationHandler.END

    if data.startswith("tmpl_reminder_activate_"):
        template_id = int(data.split("_")[3])
        t = get_template(template_id)
        if not t:
            await query.edit_message_text("Шаблон не знайдено.")
            return ConversationHandler.END
        context.user_data["activate_template_id"]    = template_id
        context.user_data["activate_from_reminder"]  = True
        await query.edit_message_text(
            f"▶️ Скільки наборів «{t['title']}» доступно сьогодні?"
        )
        return TEMPLATE_ACTIVATE_QTY

    return ConversationHandler.END


# ── Scheduled jobs ─────────────────────────────────────────────────────────────

async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Sent daily at 17:00 Kyiv time to all venue owners who have templates."""
    owner_ids = get_all_venue_owner_ids()
    for owner_id in owner_ids:
        venue = get_venue_by_telegram_id(owner_id)
        if not venue:
            continue
        templates = get_templates_for_venue(venue["id"])
        if not templates:
            continue
        inactive = [t for t in templates if not is_template_active_today(t["id"])]
        if not inactive:
            continue  # All already active, no need to remind

        template_lines = "\n".join(f"• {t['title']}" for t in inactive)
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=(
                    f"🔔 Нагадування LuckyMeal\n\n"
                    f"Час активувати набори на сьогодні!\n\n"
                    f"Неактивних шаблонів: {len(inactive)}\n"
                    f"{template_lines}\n\n"
                    f"Хочете продавати сьогодні?"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Так", callback_data="reminder_yes"),
                        InlineKeyboardButton("❌ Ні",  callback_data="reminder_no"),
                    ]
                ]),
            )
        except Exception as error:
            logging.warning("Could not send reminder to %s: %s", owner_id, error)


async def daily_reset_job(context: ContextTypes.DEFAULT_TYPE):
    """Called at 00:05 Kyiv time — deactivates all template offers from yesterday."""
    reset_expired_template_offers()
    logging.info("Daily reset: expired template offers deactivated.")


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════

async def loadvenues_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return

    existing = {v["name"] for v in get_all_venues()}
    added, skipped = [], []

    for v in SEED_VENUES:
        if v["name"] in existing:
            skipped.append(v["name"])
        else:
            admin_add_venue(
                name=v["name"], category=v["category"],
                address=None, phone=None, instagram=None,
                description=None, pickup=1,
            )
            added.append(v["name"])

    lines = [f"✅ Додано {len(added)} закладів:\n"]
    for name in added:
        lines.append(f"• {name}")
    if skipped:
        lines.append(f"\n⏭ Вже існують ({len(skipped)}): {', '.join(skipped)}")
    lines.append("\nТепер додай адреси та телефони через /admin → Всі заклади → Редагувати.")
    await update.message.reply_text("\n".join(lines))


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return ConversationHandler.END
    await update.message.reply_text("🛠 Адмін-панель LuckyMeal", reply_markup=admin_menu_keyboard())
    return ConversationHandler.END


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("⛔ Доступ заборонено", show_alert=True)
        return ConversationHandler.END

    data = query.data

    if data == "adm_menu":
        await query.edit_message_text("🛠 Адмін-панель LuckyMeal", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END

    if data == "adm_stats":
        s = get_stats()
        await query.edit_message_text(
            f"📊 Статистика LuckyMeal\n\n"
            f"🏪 Закладів всього: {s['venues_total']}\n"
            f"✅ Активних: {s['venues_active']}\n"
            f"🍽️ Активних пропозицій: {s['offers_active']}\n"
            f"❤️ Бронювань всього: {s['bookings_total']}\n"
            f"📦 Шаблонів всього: {s['templates_total']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Меню", callback_data="adm_menu")]]),
        )
        return ConversationHandler.END

    if data == "adm_list":
        venues = get_all_venues()
        if not venues:
            await query.edit_message_text(
                "Ще немає жодного закладу.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Додати заклад", callback_data="adm_add")],
                    [InlineKeyboardButton("← Меню",          callback_data="adm_menu")],
                ]),
            )
            return ConversationHandler.END
        await query.edit_message_text(
            f"📋 Всі заклади ({len(venues)}):\n✅ активний  ⏸ неактивний  🔧 управляє адмін",
            reply_markup=admin_venues_keyboard(venues),
        )
        return ConversationHandler.END

    if data.startswith("adm_venue_"):
        venue_id = int(data.split("_")[2])
        venue = get_venue_by_id(venue_id)
        if not venue:
            await query.edit_message_text("Заклад не знайдено.")
            return ConversationHandler.END
        await query.edit_message_text(
            venue_info_text(venue),
            reply_markup=admin_venue_detail_keyboard(venue_id, venue["status"]),
        )
        return ConversationHandler.END

    if data.startswith("adm_activate_") or data.startswith("adm_deactivate_"):
        parts      = data.split("_")
        venue_id   = int(parts[2])
        new_status = "active" if data.startswith("adm_activate_") else "inactive"
        admin_update_venue(venue_id, status=new_status)
        venue = get_venue_by_id(venue_id)
        await query.edit_message_text(
            venue_info_text(venue),
            reply_markup=admin_venue_detail_keyboard(venue_id, venue["status"]),
        )
        return ConversationHandler.END

    if data.startswith("adm_del_"):
        venue_id = int(data.split("_")[2])
        venue    = get_venue_by_id(venue_id)
        name     = venue["name"] if venue else "?"
        await query.edit_message_text(
            f"⚠️ Видалити «{name}»?\n\nВсі пропозиції та шаблони цього закладу також будуть видалені.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Так, видалити", callback_data=f"adm_delconfirm_{venue_id}")],
                [InlineKeyboardButton("← Назад",           callback_data=f"adm_venue_{venue_id}")],
            ]),
        )
        return ConversationHandler.END

    if data.startswith("adm_delconfirm_"):
        venue_id = int(data.split("_")[2])
        admin_delete_venue(venue_id)
        await query.edit_message_text("✅ Заклад видалено.", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END

    if data == "adm_add":
        context.user_data["adm_new"] = {}
        await query.edit_message_text("➕ Новий заклад\n\nКрок 1 — Введіть назву закладу:")
        return ADMIN_ADD_NAME

    if data.startswith("adm_edit_"):
        venue_id = int(data.split("_")[2])
        context.user_data["adm_edit_venue_id"] = venue_id
        await query.edit_message_text(
            "✏️ Що хочете відредагувати?",
            reply_markup=admin_edit_fields_keyboard(venue_id),
        )
        return ADMIN_EDIT_FIELD

    if data.startswith("adm_link_"):
        venue_id = int(data.split("_")[2])
        context.user_data["adm_link_venue_id"] = venue_id
        venue = get_venue_by_id(venue_id)
        await query.edit_message_text(
            f"🔗 Прив'язати власника до «{venue['name'] if venue else '?'}»\n\n"
            f"Введіть Telegram ID власника.\n"
            f"(Власник може дізнатись свій ID командою /myid в боті)"
        )
        return ADMIN_LINK_TELEGRAM

    if data.startswith("adm_offer_"):
        venue_id = int(data.split("_")[2])
        venue    = get_venue_by_id(venue_id)
        context.user_data["admin_offer_venue_id"] = venue_id
        context.user_data["new_offer"] = {}
        await query.edit_message_text(
            f"➕ Нова пропозиція для «{venue['name'] if venue else '?'}»\n\n"
            f"Крок 1 з 5 — Введіть назву набору:\nНаприклад: Вечірній паста-сет"
        )
        return ADMIN_OFFER_TITLE

    if data.startswith("adm_cat_"):
        idx = int(data.split("_")[2])
        context.user_data["adm_new"]["category"] = VENUE_CATEGORIES[idx]
        await query.edit_message_text("Крок 3 — Введіть адресу:\nНаприклад: Київ, вул. Ярославська, 12")
        return ADMIN_ADD_ADDRESS

    if data.startswith("adm_ecat_"):
        idx      = int(data.split("_")[2])
        venue_id = context.user_data.get("adm_edit_venue_id")
        admin_update_venue(venue_id, category=VENUE_CATEGORIES[idx])
        venue = get_venue_by_id(venue_id)
        await query.edit_message_text(
            f"✅ Категорію оновлено.\n\n{venue_info_text(venue)}",
            reply_markup=admin_venue_detail_keyboard(venue_id, venue["status"]),
        )
        return ConversationHandler.END

    if data.startswith("adm_pickup_"):
        pickup = 1 if data.endswith("_yes") else 0
        context.user_data["adm_new"]["pickup"] = pickup
        d = context.user_data["adm_new"]
        venue_id = admin_add_venue(
            name=d["name"], category=d.get("category"),
            address=d.get("address"), phone=d.get("phone"),
            instagram=d.get("instagram"), description=d.get("description"),
            pickup=pickup,
        )
        context.user_data.pop("adm_new", None)
        venue = get_venue_by_id(venue_id)
        await query.edit_message_text(
            f"✅ Заклад додано!\n\n{venue_info_text(venue)}",
            reply_markup=admin_venue_detail_keyboard(venue_id, venue["status"]),
        )
        return ConversationHandler.END

    if data.startswith("adm_ef_"):
        parts    = data.split("_")
        field    = parts[2]
        venue_id = int(parts[3])
        context.user_data["adm_edit_venue_id"] = venue_id
        context.user_data["adm_edit_field"]    = field

        if field == "category":
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(VENUE_CATEGORIES[i], callback_data=f"adm_ecat_{i}")]
                 for i in range(len(VENUE_CATEGORIES))]
            )
            await query.edit_message_text("Оберіть нову категорію:", reply_markup=kb)
            return ADMIN_EDIT_FIELD

        field_labels = {
            "name": "назву", "address": "адресу", "phone": "телефон",
            "instagram": "Instagram", "contact_person": "контактну особу", "description": "опис",
        }
        await query.edit_message_text(f"Введіть нову {field_labels.get(field, field)}:")
        return ADMIN_EDIT_VALUE

    return ConversationHandler.END


# ── Admin conversation text handlers ──────────────────────────────────────────

async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("Назва занадто коротка. Введіть ще раз.")
        return ADMIN_ADD_NAME
    context.user_data["adm_new"]["name"] = name
    await update.message.reply_text("Крок 2 — Оберіть категорію:", reply_markup=category_keyboard("adm_cat"))
    return ADMIN_ADD_CATEGORY


async def admin_add_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adm_new"]["address"] = update.message.text.strip() or None
    await update.message.reply_text("Крок 4 — Введіть телефон:", reply_markup=skip_keyboard("adm_skip_phone"))
    return ADMIN_ADD_PHONE


async def admin_add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adm_new"]["phone"] = update.message.text.strip() or None
    await update.message.reply_text(
        "Крок 5 — Введіть Instagram (наприклад: @bakery_kyiv):",
        reply_markup=skip_keyboard("adm_skip_instagram"),
    )
    return ADMIN_ADD_INSTAGRAM


async def admin_add_instagram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adm_new"]["instagram"] = update.message.text.strip() or None
    await update.message.reply_text(
        "Крок 6 — Введіть короткий опис закладу:",
        reply_markup=skip_keyboard("adm_skip_description"),
    )
    return ADMIN_ADD_DESCRIPTION


async def admin_add_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["adm_new"]["description"] = update.message.text.strip() or None
    await update.message.reply_text("Крок 7 — Самовивіз доступний?", reply_markup=pickup_keyboard("adm_pickup"))
    return ADMIN_ADD_PICKUP


async def admin_add_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "adm_skip_phone":
        context.user_data["adm_new"]["phone"] = None
        await query.edit_message_text(
            "Крок 5 — Введіть Instagram (наприклад: @bakery_kyiv):",
            reply_markup=skip_keyboard("adm_skip_instagram"),
        )
        return ADMIN_ADD_INSTAGRAM

    if data == "adm_skip_instagram":
        context.user_data["adm_new"]["instagram"] = None
        await query.edit_message_text(
            "Крок 6 — Введіть короткий опис закладу:",
            reply_markup=skip_keyboard("adm_skip_description"),
        )
        return ADMIN_ADD_DESCRIPTION

    if data == "adm_skip_description":
        context.user_data["adm_new"]["description"] = None
        await query.edit_message_text("Крок 7 — Самовивіз доступний?", reply_markup=pickup_keyboard("adm_pickup"))
        return ADMIN_ADD_PICKUP

    return ConversationHandler.END


async def admin_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field    = context.user_data.get("adm_edit_field")
    venue_id = context.user_data.get("adm_edit_venue_id")
    value    = update.message.text.strip()
    admin_update_venue(venue_id, **{field: value})
    venue = get_venue_by_id(venue_id)
    context.user_data.pop("adm_edit_field", None)
    await update.message.reply_text(
        f"✅ Оновлено.\n\n{venue_info_text(venue)}",
        reply_markup=admin_venue_detail_keyboard(venue_id, venue["status"]),
    )
    return ConversationHandler.END


async def admin_link_telegram(update: Update, context: ContextTypes.DEFAULT_TYPE):
    venue_id = context.user_data.get("adm_link_venue_id")
    try:
        owner_id = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Telegram ID має бути числом. Спробуйте ще раз.")
        return ADMIN_LINK_TELEGRAM
    link_venue_to_owner(venue_id, owner_id)
    venue = get_venue_by_id(venue_id)
    context.user_data.pop("adm_link_venue_id", None)
    await update.message.reply_text(
        f"✅ Власника прив'язано!\n\nTelegram ID {owner_id} тепер є власником «{venue['name'] if venue else '?'}».\n"
        f"Власник може управляти пропозиціями через /myvenue.",
        reply_markup=admin_venue_detail_keyboard(venue_id, venue["status"] if venue else "active"),
    )
    return ConversationHandler.END


# Admin offer creation reuses venue offer states
async def admin_offer_title(update, context):      return await offer_title(update, context)
async def admin_offer_orig(update, context):       return await offer_original_price(update, context)
async def admin_offer_price_handler(update, context): return await offer_price(update, context)
async def admin_offer_qty(update, context):        return await offer_quantity(update, context)
async def admin_offer_time(update, context):       return await offer_pickup_time(update, context)
async def admin_offer_photo_handler(update, context): return await offer_photo(update, context)
async def admin_offer_photo_skip_handler(update, context): return await offer_photo_skip(update, context)


# ── Bot setup ──────────────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeChat

    # Commands visible to everyone
    public_commands = [
        BotCommand("start",       "🏠 Головна"),
        BotCommand("offers",      "🔍 Пропозиції"),
        BotCommand("mybookings",  "❤️ Мої бронювання"),
        BotCommand("myvenue",     "🏪 Мій заклад"),
        BotCommand("help",        "ℹ️ Допомога"),
        BotCommand("myid",        "Мій Telegram ID"),
        BotCommand("cancel",      "Скасувати поточну дію"),
    ]
    await application.bot.set_my_commands(
        public_commands, scope=BotCommandScopeAllPrivateChats()
    )

    # Extra commands visible only to admin
    admin_id = get_admin_chat_id()
    if admin_id:
        await application.bot.set_my_commands(
            public_commands + [
                BotCommand("admin",      "🛠 Адмін-панель"),
                BotCommand("loadvenues", "📥 Завантажити всі заклади"),
            ],
            scope=BotCommandScopeChat(chat_id=int(admin_id)),
        )

    # ── Daily scheduler (17:00 reminder + midnight reset) ──────────────────────
    if application.job_queue:
        # Ukraine is permanently UTC+3
        kyiv = timezone(timedelta(hours=3))
        application.job_queue.run_daily(
            daily_reminder_job,
            time=dt_time(17, 0, 0, tzinfo=kyiv),
            name="daily_reminder",
        )
        application.job_queue.run_daily(
            daily_reset_job,
            time=dt_time(0, 5, 0, tzinfo=kyiv),
            name="daily_reset",
        )
        logging.info("Scheduled: daily reminder at 17:00 Kyiv, reset at 00:05 Kyiv.")
    else:
        logging.warning("JobQueue not available — install python-telegram-bot[job-queue].")


def build_application(token):
    application = Application.builder().token(token).post_init(post_init).build()

    # ── Template conversation ──────────────────────────────────────────────────
    template_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(template_callback_handler, pattern="^tmpl_"),
            CallbackQueryHandler(reminder_callback_handler, pattern="^reminder_"),
        ],
        states={
            TEMPLATE_TITLE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, template_title)],
            TEMPLATE_ORIG_PRICE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, template_orig_price)],
            TEMPLATE_PRICE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, template_price)],
            TEMPLATE_PICKUP_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, template_pickup_time)],
            TEMPLATE_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, template_description),
                CallbackQueryHandler(template_description_skip, pattern="^tmpl_skip_description$"),
            ],
            TEMPLATE_PHOTO: [
                MessageHandler(filters.PHOTO & ~filters.COMMAND, template_photo),
                CallbackQueryHandler(template_photo_skip, pattern="^tmpl_skip_photo$"),
            ],
            TEMPLATE_ACTIVATE_QTY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, template_activate_qty),
                # Allow reminder callbacks while waiting for quantity
                CallbackQueryHandler(reminder_callback_handler, pattern="^(reminder_|tmpl_reminder_)"),
                CallbackQueryHandler(template_callback_handler, pattern="^tmpl_"),
            ],
            TEMPLATE_EDIT_FIELD: [
                CallbackQueryHandler(template_callback_handler, pattern="^tmpl_"),
            ],
            TEMPLATE_EDIT_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, template_edit_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # ── Main conversation (venue registration + offer creation) ────────────────
    main_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(choose_role,    pattern="^(role_venue|role_buyer|main_menu)$"),
            CallbackQueryHandler(venue_actions,  pattern="^venue_"),
        ],
        states={
            REGISTER_NAME:           [MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_name)],
            REGISTER_ADDRESS:        [MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_address)],
            REGISTER_PHONE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_phone)],
            REGISTER_INSTAGRAM:      [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_instagram),
                CallbackQueryHandler(register_venue_instagram_skip, pattern="^skip_instagram$"),
            ],
            REGISTER_CONTACT_PERSON: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_venue_contact_person)],
            OFFER_TITLE:             [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_title)],
            OFFER_ORIGINAL_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_original_price)],
            OFFER_PRICE:             [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_price)],
            OFFER_QUANTITY:          [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_quantity)],
            OFFER_PICKUP_TIME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, offer_pickup_time)],
            OFFER_PHOTO:             [
                MessageHandler(filters.PHOTO & ~filters.COMMAND, offer_photo),
                CallbackQueryHandler(offer_photo_skip, pattern="^skip_photo$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # ── Admin conversation ─────────────────────────────────────────────────────
    admin_conversation = ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_command),
            CallbackQueryHandler(admin_menu_callback, pattern="^adm_"),
        ],
        states={
            ADMIN_ADD_NAME:       [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
            ADMIN_ADD_CATEGORY:   [CallbackQueryHandler(admin_menu_callback, pattern="^adm_cat_")],
            ADMIN_ADD_ADDRESS:    [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_address),
                CallbackQueryHandler(admin_add_skip_callback, pattern="^adm_skip_"),
            ],
            ADMIN_ADD_PHONE:      [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_phone),
                CallbackQueryHandler(admin_add_skip_callback, pattern="^adm_skip_"),
            ],
            ADMIN_ADD_INSTAGRAM:  [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_instagram),
                CallbackQueryHandler(admin_add_skip_callback, pattern="^adm_skip_"),
            ],
            ADMIN_ADD_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_description),
                CallbackQueryHandler(admin_add_skip_callback, pattern="^adm_skip_"),
            ],
            ADMIN_ADD_PICKUP:     [CallbackQueryHandler(admin_menu_callback, pattern="^adm_pickup_")],
            ADMIN_EDIT_FIELD:     [CallbackQueryHandler(admin_menu_callback, pattern="^adm_(ef_|ecat_|venue_)")],
            ADMIN_EDIT_VALUE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_value)],
            ADMIN_LINK_TELEGRAM:  [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_link_telegram)],
            ADMIN_OFFER_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_offer_title)],
            ADMIN_OFFER_ORIG:     [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_offer_orig)],
            ADMIN_OFFER_PRICE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_offer_price_handler)],
            ADMIN_OFFER_QTY:      [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_offer_qty)],
            ADMIN_OFFER_TIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_offer_time)],
            ADMIN_OFFER_PHOTO:    [
                MessageHandler(filters.PHOTO & ~filters.COMMAND, admin_offer_photo_handler),
                CallbackQueryHandler(admin_offer_photo_skip_handler, pattern="^skip_photo$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    # Register handlers (order matters — more specific first)
    application.add_handler(CommandHandler("start",       start))
    application.add_handler(CommandHandler("help",        help_command))
    application.add_handler(CommandHandler("myid",        myid_command))
    application.add_handler(CommandHandler("cancel",      cancel))
    application.add_handler(CommandHandler("offers",      offers_command))
    application.add_handler(CommandHandler("mybookings",  mybookings_command))
    application.add_handler(CommandHandler("myvenue",     myvenue_command))
    application.add_handler(CommandHandler("loadvenues",  loadvenues_command))
    application.add_handler(template_conversation)
    application.add_handler(admin_conversation)
    application.add_handler(main_conversation)
    application.add_handler(CallbackQueryHandler(buyer_actions,            pattern="^buyer_list_offers$"))
    application.add_handler(CallbackQueryHandler(show_offer,               pattern="^offer_[0-9]+$"))
    application.add_handler(CallbackQueryHandler(confirm_booking_callback, pattern="^confirm_[0-9]+$"))

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

