"""Sabitler, API anahtarları, model listeleri, tarih yardımcıları."""
import streamlit as st
from datetime import datetime

# --- API Keys (Streamlit Secrets) ---
try:
    GEMINI_KEYS = dict(st.secrets["GEMINI_KEYS"])
except Exception:
    GEMINI_KEYS = {}

try:
    TELEGRAM_BOT_TOKEN = str(st.secrets["TELEGRAM_BOT_TOKEN"])
except Exception:
    TELEGRAM_BOT_TOKEN = ""

try:
    TELEGRAM_CHAT_ID = str(st.secrets["TELEGRAM_CHAT_ID"])
except Exception:
    TELEGRAM_CHAT_ID = ""

# --- Cooldown / Retry sabitleri (saniye) ---
COOLDOWN_QUOTA = 60
COOLDOWN_UNAVAILABLE = 900
COOLDOWN_GENERIC = 300
COOLDOWN_NOT_FOUND = 86400
COOLDOWN_FREE_TIER_YOK = 604800

# --- Model listeleri ---
VIDEO_ANALIZ_MODELLERI = ["gemini-3.6-flash", "gemini-2.5-flash"]
METIN_MODELLERI = [
    "gemini-3.6-flash",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
SES_MODELI = "gemini-2.5-flash-preview-tts"

# --- Kayıt / ses sabitleri ---
KAYIT_DOSYASI = "kayitlar.json"
MAX_KAYIT = 5
SES_DOSYA_OMRU_SAAT = 24

# --- Tarih ---
AYLAR_TR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
GUNLER_TR = [
    "Pazartesi", "Salı", "Çarşamba", "Perşembe",
    "Cuma", "Cumartesi", "Pazar",
]


def guncel_tarih_metni() -> str:
    simdi = datetime.now()
    return (
        f"{simdi.day} {AYLAR_TR[simdi.month - 1]} {simdi.year}, "
        f"{GUNLER_TR[simdi.weekday()]}"
    )
