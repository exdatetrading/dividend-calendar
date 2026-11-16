"""EX-DATE RESULTS: lightweight Telegram bot polled by GitHub Actions."""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN = os.environ["RESULTS_BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"
ROOT = Path(__file__).resolve().parent.parent
CALENDAR_URL = "https://exdatetrading.github.io/dividend-calendar/"


def api(method, params=None):
    payload = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(API + method, data=payload)
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error in {method}: {data.get('description')}")
    return data["result"]


def keyboard():
    return json.dumps({"inline_keyboard": [
        [{"text": "📊 Результаты", "callback_data": "results"},
         {"text": "📈 Статистика", "callback_data": "stats"}],
        [{"text": "📅 Дивидендный календарь", "url": CALENDAR_URL}]
    ]}, ensure_ascii=False)


def send(chat_id, message):
    api("sendMessage", {"chat_id": chat_id, "text": message, "reply_markup": keyboard()})


def trades():
    data = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    rows = data.get("trades", [])
    if not isinstance(rows, list):
        raise ValueError("results.json: 'trades' must be a list")
    return sorted((t for t in rows if t.get("status") == "closed"),
                  key=lambda t: str(t.get("closed_at", "")), reverse=True)


def signed(value):
    return f"{float(value):+,.2f}"


def show_results(chat_id):
    items = trades()
    if not items:
        send(chat_id, "📊 EX-DATE RESULTS\n\nЗакрытых подтверждённых сделок пока нет.")
        return
    lines = ["📊 EX-DATE RESULTS", "Последние закрытые сделки:\n"]
    for t in items[:10]:
        pnl = float(t["pnl_usd"])
        indicator = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
        lines.append(f"{indicator} {t['ticker']} · {t['side']}\n"
                     f"Закрыта: {t['closed_at']}\n"
                     f"Результат: {signed(pnl)} USD\n"
                     f"Доходность: {signed(t['return_pct'])}%\n"
                     "🔒 Точки входа и выхода не публикуются\n")
    send(chat_id, "\n".join(lines))


def show_stats(chat_id):
    items = trades()
    if not items:
        send(chat_id, "📈 EX-DATE PERFORMANCE\n\nСтатистики пока нет.")
        return
    pnl_values = [float(t["pnl_usd"]) for t in items]
    wins = sum(p > 0 for p in pnl_values)
    losses = sum(p < 0 for p in pnl_values)
    flats = len(items) - wins - losses
    total = sum(pnl_values)
    send(chat_id, f"📈 EX-DATE PERFORMANCE\n\n"
         f"Закрытых сделок: {len(items)}\n"
         f"🟢 Прибыльных: {wins}\n🔴 Убыточных: {losses}\n"
         f"⚪ Без результата: {flats}\n"
         f"Доля прибыльных: {wins / len(items) * 100:.1f}%\n"
         f"Суммарный P&L: {signed(total)} USD\n\n"
         "Статистика основана на внесённых результатах. "
         "Доходность в прошлом не гарантирует будущую.")


def handle(update):
    if "callback_query" in update:
        callback = update["callback_query"]
        api("answerCallbackQuery", {"callback_query_id": callback["id"]})
        msg = callback.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        command = callback.get("data", "")
    elif "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        command = msg.get("text", "").split("@")[0].split(" ")[0].strip()
    else:
        return
    if chat_id is None:
        return
    if command in ("results", "/results"):
        show_results(chat_id)
    elif command in ("stats", "/stats"):
        show_stats(chat_id)
    else:
        send(chat_id, "🔴 EX-DATE RESULTS\n\n"
             "Результаты закрытых сделок вокруг дивидендных событий.\n\n"
             "📊 История сделок\n📈 Общая статистика\n"
             "🔒 Точки входа и выхода не публикуются.\n\n"
             "Выберите раздел ниже:")


def main():
    # Webhook and getUpdates are mutually exclusive.
    webhook = api("getWebhookInfo")
    if webhook.get("url"):
        raise RuntimeError("Webhook is active. Remove it before using GitHub Actions polling.")
    updates = api("getUpdates", {"timeout": 0, "limit": 100,
                                  "allowed_updates": json.dumps(["message", "callback_query"])})
    for update in updates:
        handle(update)
        # Telegram confirms updates strictly below the supplied offset.
        # Only acknowledge AFTER handling so failures can be retried.
        api("getUpdates", {"offset": update["update_id"] + 1, "timeout": 0, "limit": 1})


if __name__ == "__main__":
    main()
