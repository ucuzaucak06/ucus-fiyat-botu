import os
import logging
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ─────────────────────────────────────────────
# AYARLAR — sadece buraya yaz
# ─────────────────────────────────────────────
TELEGRAM_TOKEN  = "B8237346432:AAH0lHmI08QqtnJ3yiTa05fUftCIj1t98jA"
SKYSCANNER_KEY  = "uc643373167396223405725428773537"
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Konuşma adımları
KALKIS, VARIS, TARIH = range(3)

SKYSCANNER_URL = (
    "https://partners.api.skyscanner.net"
    "/apiservices/v3/flights/indicative/search"
)

# 30+ piyasa (market) listesi — fiyat karşılaştırması için
MARKETS = [
    ("TR", "tr-TR", "TRY"),
    ("DE", "de-DE", "EUR"),
    ("FR", "fr-FR", "EUR"),
    ("NL", "nl-NL", "EUR"),
    ("BE", "fr-BE", "EUR"),
    ("AT", "de-AT", "EUR"),
    ("IT", "it-IT", "EUR"),
    ("ES", "es-ES", "EUR"),
    ("PL", "pl-PL", "PLN"),
    ("CZ", "cs-CZ", "CZK"),
    ("HU", "hu-HU", "HUF"),
    ("RO", "ro-RO", "RON"),
    ("BG", "bg-BG", "BGN"),
    ("GR", "el-GR", "EUR"),
    ("PT", "pt-PT", "EUR"),
    ("SE", "sv-SE", "SEK"),
    ("NO", "nb-NO", "NOK"),
    ("DK", "da-DK", "DKK"),
    ("FI", "fi-FI", "EUR"),
    ("CH", "de-CH", "CHF"),
    ("GB", "en-GB", "GBP"),
    ("IE", "en-IE", "EUR"),
    ("US", "en-US", "USD"),
    ("CA", "en-CA", "CAD"),
    ("AU", "en-AU", "AUD"),
    ("IN", "en-IN", "INR"),
    ("AE", "en-AE", "AED"),
    ("SA", "ar-SA", "SAR"),
    ("EG", "ar-EG", "EGP"),
    ("ZA", "en-ZA", "ZAR"),
    ("JP", "ja-JP", "JPY"),
    ("SG", "en-SG", "SGD"),
    ("TH", "th-TH", "THB"),
    ("MX", "es-MX", "MXN"),
    ("BR", "pt-BR", "BRL"),
    ("RU", "ru-RU", "RUB"),
    ("UA", "uk-UA", "UAH"),
    ("KW", "ar-KW", "KWD"),
    ("QA", "ar-QA", "QAR"),
    ("HK", "zh-HK", "HKD"),
]

# Döviz → EUR sabit kur tablosu (yaklaşık değerler)
EUR_RATES = {
    "EUR": 1.0,
    "TRY": 0.028,
    "GBP": 1.17,
    "USD": 0.92,
    "CAD": 0.68,
    "AUD": 0.60,
    "INR": 0.011,
    "AED": 0.25,
    "SAR": 0.25,
    "EGP": 0.019,
    "ZAR": 0.050,
    "JPY": 0.0063,
    "SGD": 0.69,
    "THB": 0.026,
    "MXN": 0.053,
    "BRL": 0.18,
    "RUB": 0.010,
    "UAH": 0.022,
    "KWD": 3.00,
    "QAR": 0.25,
    "HKD": 0.12,
    "PLN": 0.23,
    "CZK": 0.041,
    "HUF": 0.0026,
    "RON": 0.20,
    "BGN": 0.51,
    "SEK": 0.088,
    "NOK": 0.086,
    "DKK": 0.134,
    "CHF": 1.04,
    "CHF": 1.04,
}

def skyscanner_ara(kalkis_iata, varis_iata, tarih_str, market, locale, currency):
    """Tek bir market için Skyscanner Indicative fiyatını çeker."""
    try:
        yil, ay, gun = tarih_str.split("-")
        payload = {
            "query": {
                "market": market,
                "locale": locale,
                "currency": currency,
                "queryLegs": [
                    {
                        "originPlace": {"queryPlace": {"iata": kalkis_iata.upper()}},
                        "destinationPlace": {"queryPlace": {"iata": varis_iata.upper()}},
                        "fixedDate": {
                            "year": int(yil),
                            "month": int(ay),
                            "day": int(gun),
                        },
                    }
                ],
            }
        }
        headers = {"x-api-key": SKYSCANNER_KEY, "Content-Type": "application/json"}
        r = requests.post(SKYSCANNER_URL, json=payload, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        quotes = data.get("content", {}).get("results", {}).get("quotes", {})
        if not quotes:
            return None
        # En ucuz fiyatı bul
        en_ucuz = None
        for q in quotes.values():
            fiyat = q.get("minPrice", {}).get("amount")
            if fiyat:
                fiyat_sayi = float(fiyat) / 1000  # Skyscanner mikro birim kullanır
                if en_ucuz is None or fiyat_sayi < en_ucuz:
                    en_ucuz = fiyat_sayi
        return en_ucuz
    except Exception as e:
        logger.error(f"Hata ({market}): {e}")
        return None


def eur_cevir(miktar, para_birimi):
    """Verilen tutarı EUR'ya çevirir."""
    kur = EUR_RATES.get(para_birimi, None)
    if kur is None or miktar is None:
        return None
    return round(miktar * kur, 2)


# ─────────────────────────────────────────────
# TELEGRAM KONUŞMA AKIŞI
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✈️ *Uçuş Fiyat Karşılaştırma Botuna Hoşgeldin!*\n\n"
        "30+ ülke pazarında Skyscanner fiyatlarını karşılaştırır ve en ucuzunu bulur.\n\n"
        "Başlamak için /ara komutunu kullan.",
        parse_mode="Markdown",
    )

async def ara_baslat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛫 *Kalkış havalimanı IATA kodunu yaz:*\n"
        "_(Örnek: IST, SAW, ESB)_",
        parse_mode="Markdown",
    )
    return KALKIS

async def kalkis_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kalkis = update.message.text.strip().upper()
    if len(kalkis) != 3:
        await update.message.reply_text("❌ Lütfen 3 harfli IATA kodu gir. (Örnek: IST)")
        return KALKIS
    context.user_data["kalkis"] = kalkis
    await update.message.reply_text(
        f"✅ Kalkış: *{kalkis}*\n\n🛬 *Varış havalimanı IATA kodunu yaz:*\n_(Örnek: LHR, CDG, JFK)_",
        parse_mode="Markdown",
    )
    return VARIS

async def varis_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    varis = update.message.text.strip().upper()
    if len(varis) != 3:
        await update.message.reply_text("❌ Lütfen 3 harfli IATA kodu gir. (Örnek: LHR)")
        return VARIS
    context.user_data["varis"] = varis
    await update.message.reply_text(
        f"✅ Varış: *{varis}*\n\n📅 *Uçuş tarihini yaz:*\n_(Format: YYYY-AA-GG — Örnek: 2025-08-15)_",
        parse_mode="Markdown",
    )
    return TARIH

async def tarih_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tarih = update.message.text.strip()
    try:
        datetime.strptime(tarih, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "❌ Tarih formatı yanlış. Lütfen şu şekilde yaz: *YYYY-AA-GG*\nÖrnek: 2025-08-15",
            parse_mode="Markdown",
        )
        return TARIH

    context.user_data["tarih"] = tarih
    kalkis = context.user_data["kalkis"]
    varis  = context.user_data["varis"]

    await update.message.reply_text(
        f"🔍 *{kalkis} → {varis}* ({tarih}) için\n"
        f"30+ ülke pazarında fiyatlar aranıyor...\n\n⏳ _Bu işlem 30-60 saniye sürebilir._",
        parse_mode="Markdown",
    )

    # Tüm marketlerde ara
    sonuclar = []
    for market, locale, currency in MARKETS:
        fiyat = skyscanner_ara(kalkis, varis, tarih, market, locale, currency)
        if fiyat is not None:
            eur = eur_cevir(fiyat, currency)
            if eur is not None:
                sonuclar.append({
                    "market": market,
                    "currency": currency,
                    "fiyat_yerel": fiyat,
                    "fiyat_eur": eur,
                })

    if not sonuclar:
        await update.message.reply_text(
            "😕 Bu rota için hiçbir markette fiyat bulunamadı.\n"
            "IATA kodlarını ve tarihi kontrol et.",
        )
        return ConversationHandler.END

    # EUR'ya göre sırala
    sonuclar.sort(key=lambda x: x["fiyat_eur"])

    # En ucuz 10'u göster
    mesaj = f"✈️ *{kalkis} → {varis}* | 📅 {tarih}\n"
    mesaj += "━━━━━━━━━━━━━━━━━━━━\n"
    mesaj += f"🏆 *En ucuz {min(10, len(sonuclar))} pazar (EUR bazında):*\n\n"

    for i, s in enumerate(sonuclar[:10], 1):
        mesaj += (
            f"{i}. 🌍 `{s['market']}` — "
            f"*{s['fiyat_eur']:.0f} EUR* "
            f"({s['fiyat_yerel']:.0f} {s['currency']})\n"
        )

    en_ucuz = sonuclar[0]
    mesaj += "\n━━━━━━━━━━━━━━━━━━━━\n"
    mesaj += (
        f"💰 *En ucuz pazar:* `{en_ucuz['market']}` — "
        f"*{en_ucuz['fiyat_eur']:.0f} EUR*\n\n"
    )
    mesaj += f"_Toplam {len(sonuclar)} pazarda fiyat bulundu._\n"
    mesaj += "_Fiyatlar gösterge niteliğindedir (Skyscanner Indicative API)._"

    await update.message.reply_text(mesaj, parse_mode="Markdown")
    return ConversationHandler.END

async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ İşlem iptal edildi. Yeni arama için /ara yaz.")
    return ConversationHandler.END

async def hata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Hata: {context.error}")

# ─────────────────────────────────────────────
# ANA ÇALIŞMA
# ─────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("ara", ara_baslat)],
        states={
            KALKIS: [MessageHandler(filters.TEXT & ~filters.COMMAND, kalkis_al)],
            VARIS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, varis_al)],
            TARIH:  [MessageHandler(filters.TEXT & ~filters.COMMAND, tarih_al)],
        },
        fallbacks=[CommandHandler("iptal", iptal)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_error_handler(hata)

    logger.info("🤖 Bot başlatılıyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
