import logging
import html
import re
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode
import feedparser

logging.basicConfig(format="%(asctime)s [%(levelname)s] - %(message)s", level=logging.WARNING)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8950692065:AAH2AnVZX_ITxxosh1YpsXTTO_0QM9SPmr0"
ALERT_INTERVAL = 1800

NEWS_SOURCES = {
    "forexlive": {"name": "ForexLive", "url": "https://www.forexlive.com/feed/news", "emoji": "📡"},
    "reuters": {"name": "Reuters", "url": "https://feeds.reuters.com/reuters/businessNews", "emoji": "📰"},
    "marketwatch": {"name": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/economy-politics/", "emoji": "🏦"},
    "investing_ru": {"name": "Investing RU", "url": "https://ru.investing.com/rss/news.rss", "emoji": "📊"},
}

HIGH_IMPACT = ["PMI","NFP","non-farm","CPI","inflation","Fed","Federal Reserve","ECB","FOMC","GDP","unemployment","payrolls","Powell","Lagarde","rate decision","hike","cut rates","DXY","EUR/USD","ФРС","ЕЦБ","инфляц","ВВП","безработиц","ставка","занятость"]
MEDIUM_IMPACT = ["retail sales","ISM","PPI","PCE","trade balance","ZEW","IFO","Michigan","durable goods","manufacturing","розничные","торговый баланс"]
EUR_USD_KEYS = ["EUR","USD","евро","доллар","EUR/USD","DXY","валют","форекс","курс"]

CALENDAR = [
    {"день": "Понедельник", "время": "10:00 CET", "событие": "Германия PMI Производство", "важность": "🔴 ВЫСОКАЯ", "пары": "EUR/USD, DXY"},
    {"день": "Вторник", "время": "11:00 CET", "событие": "Индекс ZEW", "важность": "🔴 ВЫСОКАЯ", "пары": "EUR/USD"},
    {"день": "Среда", "время": "14:15 CET", "событие": "США ADP занятость", "важность": "🔴 ВЫСОКАЯ", "пары": "DXY, EUR/USD"},
    {"день": "Среда", "время": "16:00 CET", "событие": "США ISM услуги", "важность": "🔴 ВЫСОКАЯ", "пары": "DXY"},
    {"день": "Четверг", "время": "14:30 CET", "событие": "США Заявки на пособие", "важность": "🟡 СРЕДНЯЯ", "пары": "DXY"},
    {"день": "Пятница", "время": "14:30 CET", "событие": "США NFP занятость вне с/х", "важность": "🔴 ВЫСОКАЯ", "пары": "DXY, EUR/USD, все пары"},
    {"день": "1-й пн мес.", "время": "10:00 CET", "событие": "ЕС PMI Производство", "важность": "🔴 ВЫСОКАЯ", "пары": "EUR/USD"},
    {"день": "3-я ср мес.", "время": "20:00 CET", "событие": "США Решение FOMC по ставке", "важность": "🔴 ВЫСОКАЯ", "пары": "DXY, ВСЕ"},
]

PMI_GUIDE = "📊 <b>Гид по PMI -> EUR/USD (SMC)</b>\n\n<i>PMI - индикатор деловой активности. Порог 50.</i>\n\n🟢 <b>PMI выше 55</b>\n  EUR/USD вверх, DXY вниз\n  Ищи лонг EUR/USD после CHoCH M15/H1\n\n🟡 <b>PMI 50-55</b>\n  EUR/USD умеренно вверх\n  Подтверди через H4\n\n🔴 <b>PMI ниже 50</b>\n  EUR/USD вниз, DXY вверх\n  Ищи шорт EUR/USD\n\n<b>Другие индикаторы:</b>\n- NFP выше прогноза -> DXY вверх\n- CPI выше прогноза -> DXY вверх\n- Ставка ФРС вверх -> DXY вверх, EUR/USD вниз\n- Ставка ЕЦБ вверх -> EUR/USD вверх\n\n💡 <i>Жди закрытия свечи после релиза!</i>"
NFP_GUIDE = "📋 <b>Гид по NFP</b>\n\n<i>Первая пятница месяца, 14:30 CET.\nСамый важный индикатор для доллара.</i>\n\n🟢 <b>NFP выше прогноза</b>\n  DXY вверх, EUR/USD вниз\n  Шорт EUR/USD после CHoCH\n\n🔴 <b>NFP ниже прогноза</b>\n  DXY вниз, EUR/USD вверх\n  Лонг EUR/USD\n\n⚠️ <b>Правила в день NFP:</b>\n- Не входи за 30 мин до данных\n- Первые 15 мин не торгуй\n- Жди CHoCH + OB на M5/M15\n- Уменьши позицию в 2 раза"
DXY_GUIDE = "📈 <b>Гид по DXY -> EUR/USD</b>\n\n<i>DXY - индекс доллара. Евро = 57.6% корзины.\nСредняя корреляция за 10 лет: -0.90</i>\n\n🔴 <b>DXY пробивает вверх</b>\n  -> EUR/USD шорт, подтверди CHoCH H1\n\n🟢 <b>DXY пробивает вниз</b>\n  -> EUR/USD лонг, подтверди CHoCH H1\n\n⚠️ <b>Дивергенция</b>\n  -> Оба растут или падают\n  -> Сигнал слабости, лучше не торговать\n\n💡 <i>Всегда проверяй DXY перед входом!</i>"

seen_articles = set()
subscribed_users = set()
user_settings = {}

def get_settings(uid):
    if uid not in user_settings:
        user_settings[uid] = {"high_only": False, "eur_only": False}
    return user_settings[uid]

def classify(title, summary=""):
    text = (title + " " + summary).upper()
    for kw in HIGH_IMPACT:
        if kw.upper() in text:
            return "🔴"
    for kw in MEDIUM_IMPACT:
        if kw.upper() in text:
            return "🟡"
    return "⚪"

def is_eur(title, summary=""):
    text = (title + " " + summary).upper()
    return any(k.upper() in text for k in EUR_USD_KEYS)

def strip_tags(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()

def build_msg(entry, src_key):
    src = NEWS_SOURCES[src_key]
    title = html.escape((entry.get("title") or "Без заголовка")[:120])
    link = entry.get("link", "")
    raw = entry.get("summary") or entry.get("description") or ""
    summary = html.escape(strip_tags(raw)[:250])
    impact = classify(entry.get("title", ""), raw)
    eur_tag = "  💱 <b>EUR/USD</b>" if is_eur(entry.get("title", ""), raw) else ""
    pub = entry.get("published", "")
    if pub:
        try:
            from email.utils import parsedate_to_datetime
            pub = parsedate_to_datetime(pub).strftime("%d.%m %H:%M UTC")
        except:
            pub = pub[:16]
    lines = [f"{src['emoji']} <b>{src['name']}</b>  {impact}{eur_tag}", f"<b>{title}</b>"]
    if summary:
        lines.append(f"<i>{summary}...</i>")
    if pub:
        lines.append(f"🕐 {pub}")
    if link:
        lines.append(f'<a href="{link}">Читать далее</a>')
    return "\n".join(lines)

def fetch_news(src_key, n=5):
    try:
        return feedparser.parse(NEWS_SOURCES[src_key]["url"]).entries[:n]
    except Exception as e:
        logger.warning(f"Ошибка {src_key}: {e}")
        return []

def main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📰 Все новости", callback_data="news_all"), InlineKeyboardButton("🔴 Только важные", callback_data="news_high")],
        [InlineKeyboardButton("💱 EUR/USD новости", callback_data="news_eur"), InlineKeyboardButton("📅 Календарь", callback_data="calendar")],
        [InlineKeyboardButton("📊 Гид PMI", callback_data="guide_pmi"), InlineKeyboardButton("📋 Гид NFP", callback_data="guide_nfp"), InlineKeyboardButton("📈 Гид DXY", callback_data="guide_dxy")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings"), InlineKeyboardButton("🔔 Подписка", callback_data="subscribe")],
    ])

def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("<- Главное меню", callback_data="main")]])

def settings_kb(uid):
    s = get_settings(uid)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Только важные" if s["high_only"] else "☐ Только важные", callback_data="tog_high")],
        [InlineKeyboardButton("✅ Только EUR/USD" if s["eur_only"] else "☐ Только EUR/USD", callback_data="tog_eur")],
        [InlineKeyboardButton("<- Главное меню", callback_data="main")],
    ])

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = html.escape(update.effective_user.first_name)
    await update.message.reply_html(
        f"👋 Привет, <b>{name}</b>!\n\nЯ <b>MacroTrader Bot</b> - слежу за макроэкономикой и влиянием на <b>EUR/USD</b> и <b>DXY</b>.\n\n<b>Что умею:</b>\n📰 Новости из нескольких источников\n🔴 Фильтр важных событий (PMI, NFP, CPI, ФРС)\n💱 Лента EUR/USD\n📅 Экономический календарь\n📊 Гиды по PMI, NFP, DXY\n🔔 Алерты каждые 30 мин\n\nВыбери действие:",
        reply_markup=main_kb()
    )

async def news_handler(reply_fn, uid=0, high_only=False, eur_only=False):
    s = get_settings(uid) if uid else {"high_only": high_only, "eur_only": eur_only}
    hi = s["high_only"] or high_only
    eu = s["eur_only"] or eur_only
    await reply_fn("⏳ <i>Загружаю новости...</i>")
    collected = []
    for src_key in NEWS_SOURCES:
        for entry in fetch_news(src_key, 4):
            if hi and classify(entry.get("title",""), entry.get("summary","")) != "🔴":
                continue
            if eu and not is_eur(entry.get("title",""), entry.get("summary","")):
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
            logger.warning(e)
    await reply_fn("─────────────────", reply_markup=back_kb())

async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    async def r(text, reply_markup=None, disable_web_page_preview=False):
        await q.message.reply_html(text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
    d = q.data
    if d == "main":
        await r("📋 <b>Главное меню:</b>", reply_markup=main_kb())
    elif d == "news_all":
        await news_handler(r, uid=uid)
    elif d == "news_high":
        await news_handler(r, uid=uid, high_only=True)
    elif d == "news_eur":
        await news_handler(r, uid=uid, eur_only=True)
    elif d == "calendar":
        lines = ["📅 <b>Экономический календарь недели</b>\n"]
        cur = ""
        for ev in CALENDAR:
            if ev["день"] != cur:
                cur = ev["день"]
                lines.append(f"\n<b>-- {cur} --</b>")
            lines.append(f"{ev['важность']}  <b>{ev['время']}</b>\n   {ev['событие']}\n   <i>Влияет на: {ev['пары']}</i>")
        lines.append("\n🔴 Высокая  🟡 Средняя  ⚪ Низкая")
        await r("\n".join(lines), reply_markup=back_kb())
    elif d == "guide_pmi":
        await r(PMI_GUIDE, reply_markup=back_kb())
    elif d == "guide_nfp":
        await r(NFP_GUIDE, reply_markup=back_kb())
    elif d == "guide_dxy":
        await r(DXY_GUIDE, reply_markup=back_kb())
    elif d == "settings":
        sub = "🔔 Подписка активна" if uid in subscribed_users else "🔕 Подписка отключена"
        await r(f"⚙️ <b>Настройки</b>\n\n{sub}", reply_markup=settings_kb(uid))
    elif d == "tog_high":
        s = get_settings(uid)
        s["high_only"] = not s["high_only"]
        await r(f"Фильтр 'Только важные' {'включён ✅' if s['high_only'] else 'выключен ☐'}", reply_markup=settings_kb(uid))
    elif d == "tog_eur":
        s = get_settings(uid)
        s["eur_only"] = not s["eur_only"]
        await r(f"Фильтр 'Только EUR/USD' {'включён ✅' if s['eur_only'] else 'выключен ☐'}", reply_markup=settings_kb(uid))
    elif d == "subscribe":
        if uid in subscribed_users:
            subscribed_users.discard(uid)
            await r("🔕 <b>Алерты отключены.</b>", reply_markup=back_kb())
        else:
            subscribed_users.add(uid)
            await r("🔔 <b>Алерты включены!</b>\nБуду присылать важные новости каждые 30 мин.", reply_markup=back_kb())

async def check_news_job(ctx: ContextTypes.DEFAULT_TYPE):
    if not subscribed_users:
        return
    new_items = []
    for src_key in NEWS_SOURCES:
        for entry in fetch_news(src_key, 5):
            key = entry.get("id") or entry.get("link","") or entry.get("title","")
            if key in seen_articles:
                continue
            if classify(entry.get("title",""), entry.get("summary","")) != "🔴":
                continue
            seen_articles.add(key)
            new_items.append((src_key, entry))
    for uid in list(subscribed_users):
        s = get_settings(uid)
        for src_key, entry in new_items[:3]:
            if s["eur_only"] and not is_eur(entry.get("title",""), entry.get("summary","")):
                continue
            try:
                await ctx.bot.send_message(chat_id=uid, text="🚨 <b>ВАЖНОЕ СОБЫТИЕ</b>\n\n" + build_msg(entry, src_key), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except:
                subscribed_users.discard(uid)

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(button))
    app.job_queue.run_repeating(check_news_job, interval=ALERT_INTERVAL, first=60)
    print("MacroTrader Bot запущен v20")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
