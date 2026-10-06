"""
QR Code Generator - a Telegram bot that needs ONLY a Telegram bot token.
QR images are generated on the server with the `qrcode` library (no external API).

Setup:
    pip install -r requirements.txt
    export BOT_TOKEN="123456:ABC..."      (Windows: set BOT_TOKEN=123456:ABC...)
    python main.py
"""
import io
import os

import qrcode
from qrcode.constants import ERROR_CORRECT_M
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]
MAX_LEN = 1000

WELCOME = (
    "👋 QR Code Generator\n\n"
    "I turn links, text, Wi-Fi details, phone numbers and emails into QR codes.\n\n"
    "Pick a type below, or just send me any text or link and I'll make a QR for it."
)

MAIN_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔗 Link / Text", callback_data="kind:text")],
    [InlineKeyboardButton("📶 Wi-Fi", callback_data="kind:wifi")],
    [InlineKeyboardButton("📞 Phone", callback_data="kind:phone"),
     InlineKeyboardButton("✉️ Email", callback_data="kind:email")],
])

SECURITY_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("WPA/WPA2", callback_data="sec:WPA"),
     InlineKeyboardButton("WEP", callback_data="sec:WEP")],
    [InlineKeyboardButton("No password", callback_data="sec:nopass")],
])

RESULT_MENU = InlineKeyboardMarkup([
    [InlineKeyboardButton("📎 Send as file (best quality)", callback_data="file")],
    [InlineKeyboardButton("🏠 New QR code", callback_data="home")],
])

PROMPTS = {
    "text": "Send me the link or text you want in the QR code.",
    "phone": "Send me the phone number (e.g. +2348012345678).",
    "email": "Send me the email address.",
}


# ---------------------------------------------------------------- helpers
def make_qr(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def wifi_escape(value: str) -> str:
    for ch in ('\\', ';', ',', ':', '"'):
        value = value.replace(ch, '\\' + ch)
    return value


def build_wifi(ssid: str, password: str, security: str) -> str:
    if security == "nopass":
        return f"WIFI:T:nopass;S:{wifi_escape(ssid)};;"
    return f"WIFI:T:{security};S:{wifi_escape(ssid)};P:{wifi_escape(password)};;"


async def send_qr(message, ud, payload: str, label: str):
    ud["payload"] = payload
    ud["step"] = None
    try:
        photo = make_qr(payload)
    except Exception:
        await message.reply_text(
            "That's too long or can't be encoded. Try something shorter.",
            reply_markup=MAIN_MENU,
        )
        return
    await message.reply_photo(photo=photo, caption=f"✅ QR code ready: {label}",
                              reply_markup=RESULT_MENU)


# ---------------------------------------------------------------- handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(WELCOME, reply_markup=MAIN_MENU)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    ud = context.user_data

    if data == "home":
        ud.clear()
        await q.message.reply_text(WELCOME, reply_markup=MAIN_MENU)

    elif data.startswith("kind:"):
        ud.clear()
        kind = data.split(":", 1)[1]
        ud["kind"] = kind
        if kind == "wifi":
            ud["step"] = "ssid"
            await q.message.reply_text("What's the Wi-Fi network name (SSID)?")
        else:
            ud["step"] = "value"
            await q.message.reply_text(PROMPTS[kind])

    elif data.startswith("sec:"):
        security = data.split(":", 1)[1]
        if ud.get("kind") != "wifi" or "ssid" not in ud:
            await q.message.reply_text("Let's start over:", reply_markup=MAIN_MENU)
            return
        payload = build_wifi(ud["ssid"], ud.get("password", ""), security)
        await send_qr(q.message, ud, payload, f"Wi-Fi \"{ud['ssid']}\"")

    elif data == "file":
        payload = ud.get("payload")
        if not payload:
            await q.message.reply_text("Nothing to send yet:", reply_markup=MAIN_MENU)
            return
        await q.message.reply_document(document=make_qr(payload), filename="qrcode.png")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    text = update.message.text.strip()
    step = ud.get("step")

    if len(text) > MAX_LEN:
        await update.message.reply_text(f"Please keep it under {MAX_LEN} characters.")
        return

    if step == "ssid":
        ud["ssid"] = text
        ud["step"] = "password"
        await update.message.reply_text("Now send the Wi-Fi password (or any text if the network is open).")

    elif step == "password":
        ud["password"] = text
        ud["step"] = "security"
        await update.message.reply_text("Choose the security type:", reply_markup=SECURITY_MENU)

    elif step == "value":
        kind = ud.get("kind", "text")
        if kind == "phone":
            number = "".join(c for c in text if c.isdigit() or c == "+")
            if len(number) < 5:
                await update.message.reply_text("That doesn't look like a phone number. Try again.")
                return
            await send_qr(update.message, ud, f"tel:{number}", number)
        elif kind == "email":
            if "@" not in text or "." not in text:
                await update.message.reply_text("That doesn't look like an email address. Try again.")
                return
            await send_qr(update.message, ud, f"mailto:{text}", text)
        else:
            payload = "https://" + text if text.lower().startswith("www.") else text
            await send_qr(update.message, ud, payload, payload[:40])

    elif step == "security":
        await update.message.reply_text("Please tap one of the security buttons:", reply_markup=SECURITY_MENU)

    else:
        # Quick mode: any text sent while idle becomes a QR code
        payload = "https://" + text if text.lower().startswith("www.") else text
        await send_qr(update.message, ud, payload, payload[:40])


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("Bot is running... press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
