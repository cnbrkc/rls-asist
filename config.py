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

# ===== KELİME HESAPLAMA =====
KELIME_HIZI_ORANI = 2.4   # TTS Türkçe ~1.7 k/s, 2.0 hedefle → AI biraz fazlaysa bile video süresine yakın kalır
KELIME_YUVARLAMA = 5      # En yakın 5'in katına yuvarla

# ===== İÇERİK TONU =====
TON_EGLENCE = "eglence"
TON_DENGELI = "dengeli"
TON_BILGI = "bilgi"
TON_TEKNIK = "teknik"

TON_ETIKETLERI = {
    TON_EGLENCE: "🎭 Eğlence Ağırlıklı (%25 bilgi)",
    TON_DENGELI: "⚖️ Dengeli (%50 bilgi)",
    TON_BILGI: "🧠 Bilgi Ağırlıklı (%75 bilgi)",
    TON_TEKNIK: "📊 Teknik Odaklı (%90 bilgi)",
}

# ===== DİĞER SABİTLER =====
MAX_INPUT_KARAKTER = 900_000
KAYIT_DOSYASI = "kayitlar.json"
MAX_KAYIT = 5
SES_OMRU_SANIYE = 24 * 60 * 60  # 24 saat
SES_HIZ_CARPANI = 1.2

# ===== VİDEO SABİTLERİ =====
VIDEO_FORMATLARI = ['mp4', 'mov', 'webm']
MAX_VIDEO_BOYUT = 50 * 1024 * 1024  # 50 MB
MIN_SURE_SANIYE = 1
MAX_SURE_SANIYE = 300

# ===== SES SABİTLERİ =====
SES_ORNEK_HIZI = 24000
SES_KANAL = 1
SES_GENISLIK = 2

# ===== VİDEO İŞLEME SABİTLERİ =====
HEDEF_2K_Y = 1440
VIDEO_CRF = 28
VIDEO_PRESET = "ultrafast"

# ===== SES SEÇENEKLERİ =====
SES_SECENEKLERI = [
    "Autonoe (Parlak - Kadın)", "Puck (Enerjik - Erkek)",
    "Aoede (Yumuşak - Kadın)", "Callirrhoe (Doğal - Kadın)",
    "Kore (Net - Kadın)", "Leda (Dinamik - Kadın)",
    "Zephyr (Parlak - Kadın)", "Charon (Bilgi - Erkek)",
    "Orus (Sert - Erkek)", "Iapetus (Akıcı - Erkek)",
    "Umbriel (Rahat - Erkek)"
]

TURKCE_AYLAR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

# ===== ULTIMATE PIPELINE — AŞAMA LİSTESİ (progress bar için) =====
# ui.py bu listeyi kullanarak ilerleme çubuğunu çizer.
PIPELINE_ADIMLARI = [
    "🎥 Video analiz ediliyor (Forensic)...",
    "🔎 Gerçekler doğrulanıyor (Research / Fact Lock)...",
    "🧠 Hikâye seçiliyor (Editorial Brain)...",
    "🎙️ Reels hazırlanıyor (Cover + Hook + Voiceover)...",
    "📝 Caption + hashtag hazırlanıyor...",
    "🧵 Threads hazırlanıyor...",
    "🔍 Son kalite kontrol (QA)...",
    "🎧 Ses üretiliyor (TTS)...",
    "🎬 Video hazırlanıyor (render)...",
]

def guncel_tarih_metni() -> str:
    simdi = datetime.now()
    return f"{simdi.day} {TURKCE_AYLAR[simdi.month]} {simdi.year}"

def model_arama_destekliyor_mu(model_adi: str) -> bool:
    return model_adi.startswith("gemini-2.5") or model_adi.startswith("gemini-3")
