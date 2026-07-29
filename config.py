import os
import streamlit as st
from datetime import datetime

# ===== API KEY'LER =====
try:
    API_KEYS = dict(st.secrets["GEMINI_KEYS"])
    if not API_KEYS:
        raise ValueError("API_KEYS boş")
except Exception as e:
    st.error(f"🔑 API anahtarları bulunamadı: {e}")
    st.stop()

# ===== MODEL LİSTELERİ =====
VIDEO_ANALIZ_MODELLERI = ["gemini-3.6-flash", "gemini-2.5-flash"]
METIN_MODELLERI = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
SES_MODELLERI = ["gemini-2.5-flash-preview-tts"]

# ===== COOLDOWN SÜRELERİ =====
COOLDOWN_SUNUCU = 15 * 60
COOLDOWN_BULUNAMADI = 24 * 60 * 60
COOLDOWN_DIGER = 5 * 60
COOLDOWN_FREE_TIER_YOK = 7 * 24 * 60 * 60
IP_BAN_KORUMA = 1.0
QUOTA_RETRY_DEFAULT = 60

# ===== DİĞER SABİTLER =====
MAX_INPUT_KARAKTER = 900_000
KAYIT_DOSYASI = "kayitlar.json"
MAX_KAYIT = 5
SES_OMRU_SANIYE = 24 * 60 * 60  # 24 saat
SES_HIZ_CARpanI = 1.0

TURKCE_AYLAR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

def guncel_tarih_metni() -> str:
    simdi = datetime.now()
    return f"{simdi.day} {TURKCE_AYLAR[simdi.month]} {simdi.year}"

def model_arama_destekliyor_mu(model_adi: str) -> bool:
    return model_adi.startswith("gemini-2.5") or model_adi.startswith("gemini-3")
