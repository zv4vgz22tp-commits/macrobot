"""
MacroTrader Bot - Telegram бот для отслеживания макроэкономических новостей
Полностью на русском языке
"""

import logging
import asyncio
import html
import re
from datetime import datetime

import feedparser
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    level=logging.WARNING,
)
logger = logging.getLogger(__name__)

# ----------------------------------------------
# ТОКЕН - вставь свой
# ----------------------------------------------
BOT_TOKEN = "8950692065:AAH2AnVZX_ITxxosh1YpsXTTO_0QM9SPmr0"
ALERT_INTERVAL_MINUTES = 30

# ----------------------------------------------
# ИСТОЧНИКИ НОВОСТЕЙ
# ----------------------------------------------
NEWS_SOURCES = {
    "investing_ru": {
        "name": "Investing.com RU",
        "url": "https://ru.investing.com/rss/news.rss",
        "emoji": "📊",
    },
    "fxstreet_ru": {
        "name": "FXStreet RU",
        "url": "https://ru.fxstreet.com/rss",
        "emoji": "💹",
    },
    "forexlive": {
        "name": "ForexLive",
        "url": "https://www.forexlive.com/feed/news",
        "emoji": "📡",
    },
    "reuters": {
        "name": "Reuters Рынки",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "emoji": "📰",
    },
    "marketwatch": {
        "name": "MarketWatch",
        "url": "https://feeds.marketwatch.com/marketwatch/economy-politics/",
        "emoji": "🏦",
    },
}

# ----------------------------------------------
# КЛЮЧЕВЫЕ СЛОВА ДЛЯ КЛАССИФИКАЦИИ
# ----------------------------------------------
HIGH_IMPACT = [
    "PMI", "NFP", "non-farm", "CPI", "inflation", "инфляц",
    "Fed", "Federal Reserve", "ECB", "ЕЦБ", "ФРС",
    "interest rate", "процентная ставка", "ставка",
    "FOMC", "GDP", "ВВП", "unemployment", "безработиц",
    "jobless", "payrolls", "Powell", "Lagarde", "Пауэлл", "Лагард",
    "rate decision", "решение по ставке", "hike", "cut rates",
    "DXY", "EUR/USD", "dollar index", "индекс доллара",
    "нон-фарм", "занятость",
]

MEDIUM_IMPACT = [
    "retail sales", "розничные продажи", "ISM", "housing", "жильё",
    "PPI", "PCE", "trade balance", "торговый баланс",
    "consumer confidence", "потребительское доверие",
    "ZEW", "IFO", "Ifo", "Michigan", "durable goods",
    "промышленное производство", "manufacturing", "услуги",
]

EUR_USD_KEYS = [
    "EUR", "USD", "евро", "доллар", "форекс", "EUR/USD",
    "курс", "DXY", "валют",
]

# ----------------------------------------------
# ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ
# ----------------------------------------------
CALENDAR = [
    {"день": "Понедельник", "время": "10:00 CET", "событие": "🇩🇪 PMI Производство Германия",        "важность": "🔴 ВЫСОКАЯ", "пары": "EUR/USD, DXY"},
    {"день": "Понедельник", "время": "10:30 CET", "событие": "🇬🇧 PMI Производство Великобритания",  "важность": "🟡 СРЕДНЯЯ", "пары": "GBP/USD"},
    {"день": "Вторник",     "время": "11:00 CET", "событие": "🇪🇺 Индекс ZEW - настроения",          "важность": "🔴 ВЫСОКАЯ", "пары": "EUR/USD"},
    {"день": "Среда",       "время": "14:15 CET", "событие": "🇺🇸 ADP - занятость в частном секторе","важность": "🔴 ВЫСОКАЯ", "пары": "DXY, EUR/USD"},
    {"день": "Среда",       "время": "16:00 CET", "событие": "🇺🇸 ISM - сфера услуг",                "важность": "🔴 ВЫСОКАЯ", "пары": "DXY"},
    {"день": "Четверг",     "время": "14:30 CET", "событие": "🇺🇸 Первичные заявки на пособие",       "важность": "🟡 СРЕДНЯЯ", "пары": "DXY"},
    {"день": "Пятница",     "время": "14:30 CET", "событие": "🇺🇸 NFP - занятость вне с/х",           "важность": "🔴 ВЫСОКАЯ", "пары": "DXY, EUR/USD, все пары"},
    {"день": "Пятница",     "время": "14:30 CET", "событие": "🇺🇸 Уровень безработицы",               "важность": "🔴 ВЫСОКАЯ", "пары": "DXY"},
    {"день": "1-й пн мес.", "время": "10:00 CET", "событие": "🇪🇺 Итоговый PMI Производство ЕС",      "важность": "🔴 ВЫСОКАЯ", "пары": "EUR/USD"},
    {"день": "3-я ср мес.", "время": "20:00 CET", "событие": "🇺🇸 Решение FOMC по процентной ставке","важность": "🔴 ВЫСОКАЯ", "пары": "DXY, ВСЕ ПАРЫ"},
]

# ----------------------------------------------
# ГИДЫ ПО ИНДИКАТОРАМ
# ----------------------------------------------
PMI_GUIDE = """📊 <b>Гид по PMI -> EUR/USD (SMC-контекст)</b>

<i>PMI - ведущий индикатор деловой активности.
Порог 50: выше = рост, ниже = сокращение.</i>

━━━━━━━━━━━━━━━━━━━━
🟢 <b>PMI выше 55 - Сильный рост</b>
  💱 EUR/USD ↑ - бычий сигнал для евро
  📈 DXY ↓ - вероятно ослабление доллара
  🎯 <i>Ищи лонг EUR/USD после CHoCH на M15/H1</i>

━━━━━━━━━━━━━━━━━━━━
🟡 <b>PMI 50-55 - Умеренный рост</b>
  💱 EUR/USD умеренно ↑
  📈 DXY нейтрально
  🎯 <i>Подтверди через структуру H4 перед входом</i>

━━━━━━━━━━━━━━━━━━━━
🔴 <b>PMI ниже 50 - Сокращение</b>
  💱 EUR/USD ↓ - медвежий сигнал для евро
  📈 DXY ↑ - вероятно укрепление доллара
  🎯 <i>Ищи шорт EUR/USD, следи за ликвидностью выше</i>

━━━━━━━━━━━━━━━━━━━━
<b>Другие ключевые индикаторы:</b>
* <b>NFP выше прогноза</b> -> DXY ↑, EUR/USD ↓
* <b>CPI выше прогноза</b> -> Fed ужесточает -> DXY ↑
* <b>Ставка ФРС ↑</b> -> DXY ↑, EUR/USD ↓
* <b>Ставка ЕЦБ ↑</b> -> EUR/USD ↑, DXY ↓
* <b>ВВП выше прогноза</b> -> укрепление нац. валюты

💡 <i>Всегда жди закрытия свечи после релиза!</i>"""

NFP_GUIDE = """📋 <b>Гид по NFP (Нон-Фарм Пейроллс)</b>

<i>Выходит каждую первую пятницу месяца в 14:30 CET.
Самый важный индикатор для доллара.</i>

━━━━━━━━━━━━━━━━━━━━
🟢 <b>NFP выше прогноза</b>
  📈 DXY ↑ резкий рост
  💱 EUR/USD ↓ падение
  🎯 <i>Шорт EUR/USD после подтверждения структуры</i>

━━━━━━━━━━━━━━━━━━━━
🔴 <b>NFP ниже прогноза</b>
  📈 DXY ↓ падение
  💱 EUR/USD ↑ рост
  🎯 <i>Лонг EUR/USD, но жди окончания волатильности</i>

━━━━━━━━━━━━━━━━━━━━
⚠️ <b>Правила торговли в день NFP:</b>
* Не входи за 30 мин до выхода данных
* Первые 5-15 мин - сильная волатильность, не торгуй
* Жди CHoCH + OB на M5/M15 после успокоения рынка
* Уменьши размер позиции в 2 раза"""

DXY_GUIDE = """📈 <b>Гид по DXY -> EUR/USD корреляция</b>

<i>DXY - индекс доллара против корзины 6 валют.
Евро занимает 57.6% корзины.</i>

━━━━━━━━━━━━━━━━━━━━
<b>Средняя корреляция за 10 лет: -0.90</b>
В 90% дней они движутся противоположно.

━━━━━━━━━━━━━━━━━━━━
📊 <b>Как использовать DXY в SMC:</b>

🔴 <b>DXY пробивает уровень вверх</b>
  -> EUR/USD ищи шорт
  -> Подтверди CHoCH на H1

🟢 <b>DXY пробивает уровень вниз</b>
  -> EUR/USD ищи лонг
  -> Подтверди CHoCH на H1

⚠️ <b>Дивергенция DXY и EUR/USD</b>
  -> Оба растут или оба падают
  -> Сигнал слабости движения
  -> Лучше не торговать или уменьши размер

━━━━━━━━━━━━━━━━━━━━
💡 <i>Всегда проверяй DXY перед входом в EUR/USD!</i>"""

# ----------------------------------------------
# СОСТОЯНИЕ
# ----------------------------------------------
seen_articles: set = set()
subscribed_users: set = set()
user_settings: dict = {}


def get_settings(uid: int) -> dict:
    if uid not in user_settings:
        user_settings[uid] = {"high_only": False, "eur_only": False}
    return user_settings[uid]


def classify(title: str, summary: str = "") -> str:
    text = (title + " " + summary).upper()
    for kw in HIGH_IMPACT:
        if kw.upper() in text:
            return "🔴"
    for kw in MEDIUM_IMPACT:
        if kw.upper() in text:
            return "🟡"
    return "⚪"


def is_eur_usd(title: str, summary: str = "") -> bool:
    text = (title + " " + summary).upper()
    return any(k.upper() in text for k in EUR_USD_KEYS)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def build_msg(entry: dict, src_key: str) -> str:
    src = NEWS_SOURCES[src_key]
    title = html.escape((entry.get("title") or "Без заголовка")[:120])
    link = entry.get("link", "")
    raw_summary = entry.get("summary") or entry.get("description") or ""
    summary = html.escape(strip_html(raw_summary)[:250])
    impact = classify(entry.get("title", ""), raw_summary)
    eur_tag = "  💱 <b>EUR/USD</b>" if is_eur_usd(entry.get("title", ""), raw_summary) else ""

    pub = entry.get("published", "")
    if pub:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub)
            pub = dt.strftime("%d.%m %H:%M UTC")
        except Exception:
            pub = pub[:16]

    lines = [f"{src['emoji']} <b>{src['name']}</b>  {impact}{eur_tag}"]
    lines.append(f"<b>{title}</b>")
    if summary:
        lines.append(f"<i>{summary}…</i>")
    if pub:
        lines.append(f"🕐 {pub}")
    if link:
        lines.append(f"<a href='{link}'>Читать -></a>")
    return "\n".join(lines)


def fetch(src_key: str, n: int = 5) -> list:
    try:
        feed = feedparser.parse(NEWS_SOURCES[src_key]["url"])
        return feed.entries[:n]
    except Exception as e:
        logger.warning(f"Ошибка загрузки {src_key}: {e}")
        return []


# ----------------------------------------------
# КЛАВИАТУРЫ
# ----------------------------------------------
def main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📰 Все новости",        callback_data="news_all"),
            InlineKeyboardButton("🔴 Только важные",      callback_data="news_high"),
        ],
        [
            InlineKeyboardButton("💱 EUR/USD новости",    callback_data="news_eur"),
            InlineKeyboardButton("📅 Календарь недели",   callback_data="calendar"),
        ],
        [
            InlineKeyboardButton("📊 Гид PMI",            callback_data="guide_pmi"),
            InlineKeyboardButton("📋 Гид NFP",            callback_data="guide_nfp"),
            InlineKeyboardButton("📈 Гид DXY",            callback_data="guide_dxy"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки алертов", callback_data="settings"),
            InlineKeyboardButton("🔔 Подписка",           callback_data="subscribe"),
        ],
    ])


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("<- Главное меню", callback_data="main")]])


def settings_kb(uid: int) -> InlineKeyboardMarkup:
    s = get_settings(uid)
    h = "✅ Только важные (High)" if s["high_only"] else "☐ Только важные (High)"
    e = "✅ Только EUR/USD" if s["eur_only"] else "☐ Только EUR/USD"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(h, callback_data="tog_high")],
        [InlineKeyboardButton(e, callback_data="tog_eur")],
        [InlineKeyboardButton("<- Главное меню", callback_data="main")],
    ])


# ----------------------------------------------
# КОМАНДЫ
# ----------------------------------------------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = html.escape(update.effective_user.first_name)
    text = (
        f"👋 Привет, <b>{name}</b>!\n\n"
        f"Я <b>MacroTrader Bot</b> - слежу за макроэкономическими новостями "
        f"и помогаю понимать их влияние на <b>EUR/USD</b> и <b>DXY</b>.\n\n"
        f"<b>Что умею:</b>\n"
        f"📰 Новости из русских и английских источников\n"
        f"🔴 Фильтр важных событий (PMI, NFP, CPI, ФРС, ЕЦБ)\n"
        f"💱 Отдельная лента EUR/USD\n"
        f"📅 Экономический календарь недели\n"
        f"📊 Гиды: как PMI, NFP и DXY влияют на курс\n"
        f"🔔 Алерты каждые {ALERT_INTERVAL_MINUTES} мин\n\n"
        f"Выбери действие:"
    )
    await update.message.reply_html(text, reply_markup=main_kb())


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html("📋 <b>Главное меню:</b>", reply_markup=main_kb())


# ----------------------------------------------
# ОТПРАВКА НОВОСТЕЙ
# ----------------------------------------------
async def send_news(reply_fn, uid: int = 0, high_only=False, eur_only=False):
    s = get_settings(uid) if uid else {"high_only": high_only, "eur_only": eur_only}
    hi = s["high_only"] or high_only
    eu = s["eur_only"] or eur_only

    await reply_fn("⏳ <i>Загружаю новости…</i>")

    collected = []
    for src_key in NEWS_SOURCES:
        for entry in fetch(src_key, 4):
            impact = classify(entry.get("title", ""), entry.get("summary", ""))
            if hi and impact != "🔴":
                continue
            if eu and not is_eur_usd(entry.get("title", ""), entry.get("summary", "")):
                continue
            collected.append((src_key, entry))
            if len(collected) >= 7:
                break
        if len(collected) >= 7:
            break

    if not collected:
        await reply_fn("😔 Нет новостей по выбранным фильтрам.", reply_markup=back_kb())
        return

    for src_key, entry in collected[:6]:
        try:
            await reply_fn(build_msg(entry, src_key), disable_web_page_preview=True)
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"Ошибка отправки: {e}")

    await reply_fn("-----------------", reply_markup=back_kb())


async def send_calendar(reply_fn):
    lines = ["📅 <b>Экономический календарь недели</b>\n"]
    current_day = ""
    for ev in CALENDAR:
        if ev["день"] != current_day:
            current_day = ev["день"]
            lines.append(f"\n<b>-- {current_day} --</b>")
        lines.append(
            f"{ev['важность']}  <b>{ev['время']}</b>\n"
            f"   {ev['событие']}\n"
            f"   <i>Влияет на: {ev['пары']}</i>"
        )
    lines.append("\n🔴 Высокая  🟡 Средняя  ⚪ Низкая")
    await reply_fn("\n".join(lines), reply_markup=back_kb())


# ----------------------------------------------
# ОБРАБОТЧИК КНОПОК
# ----------------------------------------------
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    async def reply(text, reply_markup=None, disable_web_page_preview=False):
        try:
            await q.message.reply_html(
                text, reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except Exception as e:
            logger.warning(f"Ошибка: {e}")

    d = q.data

    if d == "main":
        await reply("📋 <b>Главное меню:</b>", reply_markup=main_kb())
    elif d == "news_all":
        await send_news(reply, uid=uid)
    elif d == "news_high":
        await send_news(reply, uid=uid, high_only=True)
    elif d == "news_eur":
        await send_news(reply, uid=uid, eur_only=True)
    elif d == "calendar":
        await send_calendar(reply)
    elif d == "guide_pmi":
        await reply(PMI_GUIDE, reply_markup=back_kb())
    elif d == "guide_nfp":
        await reply(NFP_GUIDE, reply_markup=back_kb())
    elif d == "guide_dxy":
        await reply(DXY_GUIDE, reply_markup=back_kb())
    elif d == "settings":
        s = get_settings(uid)
        sub = "🔔 Подписка активна" if uid in subscribed_users else "🔕 Подписка отключена"
        await reply(
            f"⚙️ <b>Настройки алертов</b>\n\n{sub}\n\nФильтры для автоматических уведомлений:",
            reply_markup=settings_kb(uid)
        )
    elif d == "tog_high":
        s = get_settings(uid)
        s["high_only"] = not s["high_only"]
        status = "включён ✅" if s["high_only"] else "выключен ☐"
        await reply(f"Фильтр «Только важные>> {status}", reply_markup=settings_kb(uid))
    elif d == "tog_eur":
        s = get_settings(uid)
        s["eur_only"] = not s["eur_only"]
        status = "включён ✅" if s["eur_only"] else "выключен ☐"
        await reply(f"Фильтр «Только EUR/USD>> {status}", reply_markup=settings_kb(uid))
    elif d == "subscribe":
        if uid in subscribed_users:
            subscribed_users.discard(uid)
            await reply("🔕 <b>Алерты отключены.</b>", reply_markup=back_kb())
        else:
            subscribed_users.add(uid)
            await reply(
                f"🔔 <b>Алерты включены!</b>\n"
                f"Буду присылать важные новости каждые {ALERT_INTERVAL_MINUTES} мин.\n"
                f"Фильтры можно настроить в ⚙️ Настройках.",
                reply_markup=back_kb()
            )


# ----------------------------------------------
# ФОНОВАЯ ЗАДАЧА - проверка новых новостей
# ----------------------------------------------
async def check_news_job(ctx: ContextTypes.DEFAULT_TYPE):
    if not subscribed_users:
        return

    new_items = []
    for src_key in NEWS_SOURCES:
        for entry in fetch(src_key, 5):
            key = entry.get("id") or entry.get("link", "") or entry.get("title", "")
            if key in seen_articles:
                continue
            if classify(entry.get("title", ""), entry.get("summary", "")) != "🔴":
                continue
            seen_articles.add(key)
            new_items.append((src_key, entry))

    if not new_items:
        return

    for uid in list(subscribed_users):
        s = get_settings(uid)
        for src_key, entry in new_items[:3]:
            if s["eur_only"] and not is_eur_usd(entry.get("title", ""), entry.get("summary", "")):
                continue
            msg = "🚨 <b>ВАЖНОЕ СОБЫТИЕ</b>\n\n" + build_msg(entry, src_key)
            try:
                await ctx.bot.send_message(
                    chat_id=uid, text=msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
                await asyncio.sleep(0.2)
            except Exception:
                subscribed_users.discard(uid)


# ----------------------------------------------
# ЗАПУСК
# ----------------------------------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu",  cmd_menu))
    app.add_handler(CallbackQueryHandler(button))

    app.job_queue.run_repeating(
        check_news_job,
        interval=ALERT_INTERVAL_MINUTES * 60,
        first=60,
    )

    async def post_init(app):
        await app.bot.set_my_commands([
            BotCommand("start", "Запустить бота"),
            BotCommand("menu",  "Главное меню"),
        ])
    app.post_init = post_init

    print("✅ MacroTrader Bot запущен (RU). Алерты каждые", ALERT_INTERVAL_MINUTES, "мин.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

