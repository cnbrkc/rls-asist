import streamlit as st
from google import genai
from google.genai import types
import json
import os
import re
import time
import wave
import tempfile
import uuid
import base64
from datetime import datetime, timedelta
import requests as http_requests

# ============================================================
# KAYIT DOSYASI YARDIMCILARI
# ============================================================
KAYIT_DOSYASI = "kayitlar.json"
MAX_KAYIT = 5
SES_DOSYA_OMRU_SAAT = 24


def kayitlari_yukle() -> list:
    if not os.path.exists(KAYIT_DOSYASI):
        return []
    try:
        with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def kayit_ekle(veri: dict) -> list:
    kayitlar = kayitlari_yukle()
    veri["tarih"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    veri["kayit_zamani"] = datetime.now().isoformat()
    kayitlar.insert(0, veri)
    kayitlar = kayitlar[:MAX_KAYIT]
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(kayitlar, f, ensure_ascii=False, indent=2)
    eski_sesleri_temizle(kayitlar)
    return kayitlar


def eski_sesleri_temizle(kayitlar: list):
    simdi = datetime.now()
    for k in kayitlar:
        try:
            kayit_zamani = datetime.fromisoformat(k.get("kayit_zamani", ""))
            if (simdi - kayit_zamani).total_seconds() > SES_DOSYA_OMRU_SAAT * 3600:
                yol = k.get("ses_dosyasi", "")
                if yol and os.path.exists(yol):
                    os.remove(yol)
                    k["ses_dosyasi"] = None
        except (ValueError, TypeError):
            pass


def kayitlari_kaydet(kayitlar: list):
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(kayitlar, f, ensure_ascii=False, indent=2)


# ============================================================
# PROMPT YÜKLEME YARDIMCILARI
# ============================================================
def prompt_dosyasi_oku(dosya_adi: str) -> str:
    yol = os.path.join(os.path.dirname(__file__), dosya_adi)
    if not os.path.exists(yol):
        return ""
    with open(yol, "r", encoding="utf-8") as f:
        return f.read()


def guncel_tarih_metni() -> str:
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    simdi = datetime.now()
    return f"{simdi.day} {aylar[simdi.month - 1]} {simdi.year}, {gunler[simdi.weekday()]}"


def guncellik_talimatini_hazirla() -> str:
    sablon = prompt_dosyasi_oku("guncellik_talimati.txt")
    if not sablon:
        return ""
    return sablon.replace("{bugunun_tarihi}", guncel_tarih_metni())


def sistem_talimatini_hazirla(sure_saniye: int, kelime_sayisi: int, bilgi_orani: str) -> str:
    sablon = prompt_dosyasi_oku("sistem_talimati.txt")
    if not sablon:
        return ""
    min_kelime = max(5, int(kelime_sayisi * 0.9))
    max_kelime = int(kelime_sayisi * 1.1)
    return (sablon
            .replace("{guncellik_talimati}", guncellik_talimatini_hazirla())
            .replace("{sure_saniye}", str(sure_saniye))
            .replace("{kelime_sayisi}", str(kelime_sayisi))
            .replace("{min_kelime}", str(min_kelime))
            .replace("{max_kelime}", str(max_kelime))
            .replace("{bilgi_orani}", bilgi_orani))


def video_analiz_promptunu_hazirla(ek_notlar: str, sure_saniye: int) -> str:
    sablon = prompt_dosyasi_oku("video_analiz_promptu.txt")
    if not sablon:
        return ""
    if ek_notlar.strip():
        ek_bolum = f"\n\n## KULLANICININ EK NOTLARI (ÖNCELİKLİ)\n{ek_notlar.strip()}\n"
    else:
        ek_bolum = ""
    return (sablon
            .replace("{ek_notlar_bolumu}", ek_bolum)
            .replace("{guncellik_talimati}", guncellik_talimatini_hazirla())
            .replace("{sure_saniye}", str(sure_saniye)))


# ============================================================
# API KEY + TELEGRAM YAPILANDIRMASI (Streamlit Secrets)
# ============================================================
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


# ============================================================
# AYARLAR VE SABİTLER
# ============================================================
COOLDOWN_QUOTA = 60
COOLDOWN_UNAVAILABLE = 900
COOLDOWN_GENERIC = 300
COOLDOWN_NOT_FOUND = 86400
COOLDOWN_FREE_TIER_YOK = 604800

VIDEO_ANALIZ_MODELLERI = ["gemini-3.6-flash", "gemini-2.5-flash"]
METIN_MODELLERI = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
SES_MODELI = "gemini-2.5-flash-preview-tts"

AYLAR_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================
def markdown_temizle(metin: str) -> str:
    metin = metin.strip()
    if metin.startswith("```"):
        metin = re.sub(r"^```(?:json)?\s*", "", metin)
        metin = re.sub(r"\s*```$", "", metin)
    return metin.strip()


def json_parse(metin: str) -> dict:
    metin = markdown_temizle(metin)
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        eslesme = re.search(r'\{.*\}', metin, re.DOTALL)
        if eslesme:
            try:
                return json.loads(eslesme.group())
            except json.JSONDecodeError:
                pass
    return {}


def gecici_dosya_olustur(veri: bytes, uzanti: str = ".wav") -> str:
    yol = os.path.join(tempfile.gettempdir(), f"otoxtra_{uuid.uuid4().hex}{uzanti}")
    with open(yol, "wb") as f:
        f.write(veri)
    return yol


def sekmeyi_aktif_tut():
    st.markdown("""
    <script>
    setInterval(function() {
        window.postMessage({type: "keepAlive"}, "*");
    }, 30000);
    </script>
    """, unsafe_allow_html=True)


# ============================================================
# TELEGRAM GÖNDERİM YARDIMCILARI
# ============================================================
def telegram_mesaj_gonder(bot_token: str, chat_id: str, metin: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": metin}
        resp = http_requests.post(url, json=payload, timeout=30)
        return resp.status_code == 200
    except Exception:
        return False


def telegram_ses_gonder(bot_token: str, chat_id: str, dosya_yolu: str, baslik: str = "otoXtra_seslendirme") -> bool:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
        with open(dosya_yolu, "rb") as f:
            resp = http_requests.post(
                url,
                data={"chat_id": chat_id, "title": baslik, "performer": "otoXtra"},
                files={"audio": (f"{baslik}.wav", f, "audio/wav")},
                timeout=60,
            )
        return resp.status_code == 200
    except Exception:
        return False


def telegram_toplu_gonder(bot_token: str, chat_id: str, veri: dict, ses_dosyasi: str = None, log_ekle=None) -> dict:
    sonuclar = {"basarili": 0, "basarisiz": 0, "detay": []}

    def _gonder(mesaj: str, etiket: str):
        ok = telegram_mesaj_gonder(bot_token, chat_id, mesaj)
        if ok:
            sonuclar["basarili"] += 1
            sonuclar["detay"].append(f"✅ {etiket}")
            if log_ekle:
                log_ekle(f"📤 {etiket} → gönderildi")
        else:
            sonuclar["basarisiz"] += 1
            sonuclar["detay"].append(f"❌ {etiket}")
            if log_ekle:
                log_ekle(f"❌ {etiket} → BAŞARISIZ")
        time.sleep(0.5)

    # 1) Seslendirme Metni
    ses_metni = veri.get("seslendirme_metni", "").strip()
    if ses_metni:
        _gonder(f"🎙️ SESLENDİRME METNİ\n{'─' * 30}\n\n{ses_metni}", "Seslendirme Metni")

    # 2) Reels Açıklaması + Hashtagler
    aciklama = veri.get("reels_aciklamasi", "").strip()
    hashtagler = veri.get("reels_hashtagleri", [])
    if aciklama:
        hashtag_str = ""
        if hashtagler and isinstance(hashtagler, list):
            hashtag_str = "\n\n" + " ".join([h if str(h).startswith("#") else f"#{h}" for h in hashtagler])
        _gonder(f"📝 REELS AÇIKLAMASI\n{'─' * 30}\n\n{aciklama}{hashtag_str}", "Reels Açıklaması")

    # 3) Kapak Başlıkları (TEK TEK)
    kapaklar = veri.get("kapak_basliklari", [])
    if kapaklar and isinstance(kapaklar, list):
        for i, secenek in enumerate(kapaklar, start=1):
            if isinstance(secenek, dict):
                ana = secenek.get("ana", "").strip()
                alt = secenek.get("alt", "").strip()
                mesaj = f"🏷️ KAPAK BAŞLIĞI {i}\n{'─' * 30}\n\n{ana}"
                if alt:
                    mesaj += f"\n{alt}"
            else:
                mesaj = f"🏷️ KAPAK BAŞLIĞI {i}\n{'─' * 30}\n\n{str(secenek).strip()}"
            _gonder(mesaj, f"Kapak Başlığı {i}")

    # 4) Threads Açıklaması
    threads = veri.get("threads_aciklamasi", "").strip()
    if threads:
        _gonder(f"🧵 THREADS AÇIKLAMASI\n{'─' * 30}\n\n{threads}", "Threads Açıklaması")

    # 5) Ses Dosyası
    if ses_dosyasi and os.path.exists(ses_dosyasi):
        ok = telegram_ses_gonder(bot_token, chat_id, ses_dosyasi, "otoXtra_seslendirme")
        if ok:
            sonuclar["basarili"] += 1
            sonuclar["detay"].append("✅ Ses Dosyası")
            if log_ekle:
                log_ekle("📤 Ses Dosyası → gönderildi")
        else:
            sonuclar["basarisiz"] += 1
            sonuclar["detay"].append("❌ Ses Dosyası")
            if log_ekle:
                log_ekle("❌ Ses Dosyası → BAŞARISIZ")

    return sonuclar


# ============================================================
# AKILLI YÖNLENDİRİCİ (SmartRouter)
# ============================================================
class SmartRouter:
    def __init__(self):
        if "blacklist" not in st.session_state:
            st.session_state.blacklist = {}

    def _is_banned(self, mail: str, model: str) -> bool:
        bl = st.session_state.blacklist
        simdi = time.time()
        for anahtar in [f"{mail}:{model}", model]:
            if anahtar in bl:
                if simdi < bl[anahtar]:
                    return True
                else:
                    del bl[anahtar]
        return False

    def _ban(self, mail: str, model: str, sure: int, scope: str = "combo"):
        simdi = time.time()
        bl = st.session_state.blacklist
        if scope == "model":
            bl[model] = simdi + sure
        elif scope == "key":
            for m in METIN_MODELLERI + VIDEO_ANALIZ_MODELLERI + [SES_MODELI]:
                bl[f"{mail}:{m}"] = simdi + sure
        else:
            bl[f"{mail}:{model}"] = simdi + sure

    def _retry_delay_cikar(self, hata_metni: str) -> int:
        eslesme = re.search(r'retryDelay["\s:]+(\d+)', hata_metni)
        if eslesme:
            return int(eslesme.group(1))
        eslesme = re.search(r'(\d+)s', hata_metni)
        if eslesme:
            return int(eslesme.group(1))
        return 0

    def _parse_hata(self, hata: Exception) -> dict:
        hata_str = str(hata).lower()
        sonuc = {"tip": "generic", "cooldown": COOLDOWN_GENERIC, "scope": "combo", "aksiyon": "devam"}

        if "free tier" in hata_str and ("limit: 0" in hata_str or "limit\": 0" in hata_str):
            sonuc.update({"tip": "free_tier_yok", "cooldown": COOLDOWN_FREE_TIER_YOK, "scope": "model", "aksiyon": "break_model"})
        elif "429" in hata_str or "quota" in hata_str or "resource_exhausted" in hata_str:
            delay = self._retry_delay_cikar(str(hata))
            sonuc.update({"tip": "quota", "cooldown": max(delay, COOLDOWN_QUOTA)})
        elif "503" in hata_str or "unavailable" in hata_str:
            sonuc.update({"tip": "unavailable", "cooldown": COOLDOWN_UNAVAILABLE})
        elif "404" in hata_str or "not found" in hata_str:
            sonuc.update({"tip": "not_found", "cooldown": COOLDOWN_NOT_FOUND, "scope": "model", "aksiyon": "break_model"})

        return sonuc

    def _handle_hata(self, mail: str, model: str, hata: Exception, log_ekle=None):
        bilgi = self._parse_hata(hata)
        self._ban(mail, model, bilgi["cooldown"], bilgi["scope"])
        if log_ekle:
            log_ekle(f"⚠️ {mail[:3]}*** / {model}: {bilgi['tip']} ({bilgi['cooldown']}sn ban)")
        return bilgi["aksiyon"]

    def _make_request(self, modeller: list, istek_fn, log_ekle=None):
        for model in modeller:
            for mail, key in GEMINI_KEYS.items():
                if self._is_banned(mail, model):
                    continue
                try:
                    client = genai.Client(api_key=key)
                    sonuc = istek_fn(client, model)
                    if log_ekle:
                        log_ekle(f"✅ {mail[:3]}*** / {model}")
                    return sonuc
                except Exception as e:
                    aksiyon = self._handle_hata(mail, model, e, log_ekle)
                    if aksiyon == "break_model":
                        break
        return None

    def metin_uret(self, system_prompt: str, user_prompt: str, response_schema: dict,
                   modeller: list = None, arama: bool = False, log_ekle=None):
        if modeller is None:
            modeller = METIN_MODELLERI

        tools = []
        if arama:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.9,
            top_p=0.95,
        )
        if tools:
            config.tools = tools

        def istek(client, model):
            return client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )

        yanit = self._make_request(modeller, istek, log_ekle)
        if yanit is None:
            return None
        return yanit.text

    def ses_uret(self, metin: str, ses_adi: str, log_ekle=None):
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=ses_adi)
                )
            ),
        )

        def istek(client, model):
            return client.models.generate_content(
                model=model,
                contents=metin,
                config=config,
            )

        yanit = self._make_request([SES_MODELI], istek, log_ekle)
        if yanit is None:
            return None

        try:
            audio_data = yanit.candidates[0].content.parts[0].inline_data.data
            dosya_yolu = gecici_dosya_olustur(audio_data, ".wav")
            return dosya_yolu
        except (IndexError, AttributeError):
            return None

    def video_analiz_et(self, video_bytes: bytes, prompt: str, log_ekle=None):
        config = types.GenerateContentConfig(
            temperature=0.7,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

        def istek(client, model):
            return client.models.generate_content(
                model=model,
                contents=[video_part, prompt],
                config=config,
            )

        yanit = self._make_request(VIDEO_ANALIZ_MODELLERI, istek, log_ekle)
        if yanit is None:
            return None
        return yanit.text


# ============================================================
# SAYFA AYARLARI
# ============================================================
st.set_page_config(
    page_title="otoXtra",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)

if "sonuc" not in st.session_state:
    st.session_state.sonuc = None
if "log_satirlari" not in st.session_state:
    st.session_state.log_satirlari = []
if "gecici_ses_dosyalari" not in st.session_state:
    st.session_state.gecici_ses_dosyalari = []

router = SmartRouter()
sekmeyi_aktif_tut()


# ============================================================
# SOL MENÜ (SIDEBAR)
# ============================================================
with st.sidebar:
    st.markdown("## 🚗 otoXtra")
    st.caption("Otomobil Reels & Threads Üretici")
    st.divider()

    SES_SECENEKLERI = {
        "Autonoe (Parlak - Kadın)": "Autonoe",
        "Puck (Enerjik - Erkek)": "Puck",
        "Aoede (Yumuşak - Kadın)": "Aoede",
        "Callirrhoe (Doğal - Kadın)": "Callirrhoe",
        "Kore (Net - Kadın)": "Kore",
        "Leda (Dinamik - Kadın)": "Leda",
        "Zephyr (Parlak - Kadın)": "Zephyr",
        "Charon (Bilgi - Erkek)": "Charon",
        "Orus (Sert - Erkek)": "Orus",
        "Iapetus (Akıcı - Erkek)": "Iapetus",
        "Umbriel (Rahat - Erkek)": "Umbriel",
    }
    secilen_ses_label = st.selectbox("🎙️ Ses Seçimi", list(SES_SECENEKLERI.keys()), index=0)
    secilen_ses = SES_SECENEKLERI[secilen_ses_label]

    st.divider()

    st.markdown("**🔑 API Durumu**")
    if not GEMINI_KEYS:
        st.error("⛔ API key bulunamadı! Streamlit Secrets'ı kontrol edin.")
    else:
        for mail in GEMINI_KEYS:
            st.caption(f"✅ {mail[:3]}***")
        bl = st.session_state.get("blacklist", {})
        if bl:
            st.warning(f"⚠️ {len(bl)} aktif ban")

    st.divider()

    st.markdown("**📤 Telegram**")
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        st.caption("✅ Telegram bağlı")
    else:
        st.warning("⚠️ Streamlit Secrets'a TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ekle")

    st.divider()

    st.markdown("**📜 Geçmiş Üretimler**")
    kayitlar = kayitlari_yukle()
    if not kayitlar:
        st.caption("Henüz üretim yok.")
    else:
        for idx, k in enumerate(kayitlar):
            tarih = k.get("tarih", "?")
            sure = k.get("sure", "?")
            if st.button(f"📌 {tarih} ({sure}sn)", key=f"kayit_{idx}", use_container_width=True):
                st.session_state.sonuc = k
                st.rerun()


# ============================================================
# ANA ARAYÜZ
# ============================================================
st.markdown("# 🚗 otoXtra")
st.markdown("Otomobil temalı **Instagram Reels** + **Threads** içeriği üretir.")

col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 🎬 Video (Opsiyonel)")
    video_dosyasi = st.file_uploader(
        "Video yükle (max 20MB)",
        type=["mp4", "mov", "avi", "webm"],
        help="Video yüklerseniz AI önce videoyu analiz eder.",
    )

    analiz_notlari = st.text_area(
        "📝 Analiz Notları",
        placeholder="Video hakkında ek bilgiler...\nÖrn: Bu bir BMW M4, drag yarışı sahnesi var...",
        height=100,
    )

with col2:
    st.markdown("### ⚙️ Üretim Ayarları")

    uretim_notlari = st.text_area(
        "📝 Üretim Notları",
        placeholder="İçerik hakkında istekler...\nÖrn: Daha agresif ton kullan, fiyat karşılaştırması yap...",
        height=100,
    )

    sure_saniye = st.slider("⏱️ Hedef Süre (saniye)", 5, 180, 30, 5)

    TON_SECENEKLERI = {
        "🎭 Eğlence Ağırlıklı": "Her 4 cümleden 1'i bilgi, 3'ü eğlence/duygu olsun.",
        "⚖️ Dengeli": "Her 2 cümleden 1'i bilgi, 1'i eğlence/duygu olsun.",
        "🧠 Bilgi Ağırlıklı": "Her 4 cümleden 3'ü bilgi, 1'i eğlence/duygu olsun.",
        "📊 Teknik Odaklı": "Her 10 cümleden 9'u bilgi/teknik, 1'i eğlence olsun.",
    }
    ton_label = st.selectbox("🎯 İçerik Tonu", list(TON_SECENEKLERI.keys()), index=1)
    bilgi_orani = TON_SECENEKLERI[ton_label]

kelime_sayisi = round(sure_saniye * 2.8 / 5) * 5
st.info(f"📐 Hedef: **{sure_saniye} saniye** → **~{kelime_sayisi} kelime** (±%10)")

st.divider()

if st.button("🚀 ÜRET", type="primary", use_container_width=True, disabled=(not GEMINI_KEYS)):
    st.session_state.log_satirlari = []
    log_ekle = lambda msg: st.session_state.log_satirlari.append(msg)

    progress = st.progress(0, text="Başlatılıyor...")

    # ADIM 1: VİDEO ANALİZ
    analiz_metni = ""
    if video_dosyasi is not None:
        progress.progress(10, text="📹 Video analiz ediliyor...")
        log_ekle("📹 Video analiz başlatıldı...")
        video_bytes = video_dosyasi.read()
        analiz_prompt = video_analiz_promptunu_hazirla(analiz_notlari, sure_saniye)
        analiz_metni = router.video_analiz_et(video_bytes, analiz_prompt, log_ekle)
        if analiz_metni:
            log_ekle("✅ Video analizi tamamlandı.")
        else:
            log_ekle("⚠️ Video analizi başarısız, notlarla devam ediliyor.")
            analiz_metni = analiz_notlari
    else:
        analiz_metni = analiz_notlari if analiz_notlari.strip() else "Genel otomobil içeriği üret."

    # ADIM 2: METİN ÜRETİMİ
    progress.progress(35, text="✍️ Metin üretiliyor...")
    log_ekle("✍️ Metin üretimi başlatıldı...")

    kurallar = prompt_dosyasi_oku("kurallar.txt")
    sistem_talimati = sistem_talimatini_hazirla(sure_saniye, kelime_sayisi, bilgi_orani)
    system_prompt = f"{kurallar}\n\n---\n\n{sistem_talimati}"

    user_prompt = f"""## VİDEO ANALİZİ / GİRDİ
{analiz_metni}

## ÜRETİM NOTLARI
{uretim_notlari if uretim_notlari.strip() else 'Ek not yok.'}

## HEDEF
- Süre: {sure_saniye} saniye
- Kelime: ~{kelime_sayisi} (±%10)
- Ton: {ton_label}

Yukarıdaki kurallara ve düşünce zincirine uyarak JSON çıktısını üret."""

    response_schema = {
        "type": "OBJECT",
        "properties": {
            "beyin_firtinasi": {"type": "STRING"},
            "veri_kilitleme": {"type": "STRING"},
            "oz_elestiri": {"type": "STRING"},
            "seslendirme_metni": {"type": "STRING"},
            "reels_aciklamasi": {"type": "STRING"},
            "reels_hashtagleri": {"type": "ARRAY", "items": {"type": "STRING"}},
            "kapak_basliklari": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "ana": {"type": "STRING"},
                        "alt": {"type": "STRING"},
                    },
                },
            },
        },
        "required": ["beyin_firtinasi", "veri_kilitleme", "oz_elestiri",
                     "seslendirme_metni", "reels_aciklamasi", "reels_hashtagleri", "kapak_basliklari"],
    }

    metin_yanit = router.metin_uret(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_schema=response_schema,
        modeller=METIN_MODELLERI,
        arama=False,
        log_ekle=log_ekle,
    )

    if not metin_yanit:
        st.error("❌ Metin üretimi başarısız. Tüm API key'ler tükendi veya banlı.")
        st.stop()

    veri = json_parse(metin_yanit)
    if not veri:
        st.error("❌ Model çıktısı parse edilemedi.")
        st.code(metin_yanit[:2000])
        st.stop()

    log_ekle("✅ Metin üretimi tamamlandı.")

    # ADIM 3: THREADS ÜRETİMİ
    progress.progress(60, text="🧵 Threads metni üretiliyor...")
    log_ekle("🧵 Threads üretimi başlatıldı...")

    threads_promptu = prompt_dosyasi_oku("threads_promptu.txt")
    reels_aciklama = veri.get("reels_aciklamasi", "")

    threads_schema = {
        "type": "OBJECT",
        "properties": {
            "threads_aciklamasi": {"type": "STRING"},
        },
        "required": ["threads_aciklamasi"],
    }

    threads_yanit = router.metin_uret(
        system_prompt=threads_promptu,
        user_prompt=f"Bu reels açıklamasından Threads paylaşım metni üret:\n\n{reels_aciklama}",
        response_schema=threads_schema,
        modeller=METIN_MODELLERI,
        arama=False,
        log_ekle=log_ekle,
    )

    threads_aciklamasi = ""
    if threads_yanit:
        threads_veri = json_parse(threads_yanit)
        threads_aciklamasi = threads_veri.get("threads_aciklamasi", "")
    if not threads_aciklamasi:
        threads_aciklamasi = reels_aciklama[:500]
        log_ekle("⚠️ Threads üretimi başarısız, reels açıklaması kullanıldı.")
    else:
        log_ekle("✅ Threads üretimi tamamlandı.")

    veri["threads_aciklamasi"] = threads_aciklamasi

    # ADIM 4: SES ÜRETİMİ
    progress.progress(80, text="🎙️ Ses üretiliyor...")
    log_ekle(f"🎙️ Ses üretimi başlatıldı ({secilen_ses})...")

    seslendirme_metni = veri.get("seslendirme_metni", "")
    ses_dosyasi = router.ses_uret(seslendirme_metni, secilen_ses, log_ekle)

    ses_basarili = False
    if ses_dosyasi:
        st.session_state.gecici_ses_dosyalari.append(ses_dosyasi)
        ses_basarili = True
        log_ekle("✅ Ses üretimi tamamlandı.")
    else:
        log_ekle("⚠️ Ses üretimi başarısız.")

    # SONUÇ KAYDI
    progress.progress(100, text="✅ Tamamlandı!")

    sonuc = {
        "veri": veri,
        "ses_dosyasi": ses_dosyasi,
        "ses_basarili": ses_basarili,
        "ses_adi": secilen_ses,
        "sure": sure_saniye,
        "kelime": kelime_sayisi,
        "ton": ton_label,
        "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kayit_zamani": datetime.now().isoformat(),
    }

    kayit_verisi = {
        "veri": veri,
        "ses_dosyasi": ses_dosyasi,
        "ses_basarili": ses_basarili,
        "ses_adi": secilen_ses,
        "sure": sure_saniye,
        "kelime": kelime_sayisi,
        "ton": ton_label,
    }
    kayit_ekle(kayit_verisi)

    st.session_state.sonuc = sonuc
    st.rerun()


# ============================================================
# SONUÇLAR
# ============================================================
if st.session_state.sonuc:
    sonuc = st.session_state.sonuc
    veri = sonuc.get("veri", sonuc)

    st.divider()
    st.markdown("## 📋 Üretim Sonucu")
    st.success(f"✅ Üretim tamamlandı — {sonuc.get('tarih', '')} | {sonuc.get('sure', '?')}sn | ~{sonuc.get('kelime', '?')} kelime")

    # --- TELEGRAM GÖNDERİM BUTONU ---
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        if st.button("📤 Telegram'a Gönder (Tüm Çıktılar)", use_container_width=True, type="primary"):
            with st.spinner("Telegram'a gönderiliyor..."):
                tg_sonuc = telegram_toplu_gonder(
                    bot_token=TELEGRAM_BOT_TOKEN,
                    chat_id=TELEGRAM_CHAT_ID,
                    veri=veri,
                    ses_dosyasi=sonuc.get("ses_dosyasi") if sonuc.get("ses_basarili") else None,
                    log_ekle=lambda msg: st.session_state.log_satirlari.append(msg),
                )
            if tg_sonuc["basarisiz"] == 0:
                st.success(f"✅ Tüm çıktılar Telegram'a gönderildi! ({tg_sonuc['basarili']} mesaj)")
            else:
                st.warning(f"⚠️ {tg_sonuc['basarili']} gönderildi, {tg_sonuc['basarisiz']} başarısız.")
                st.caption(" | ".join(tg_sonuc["detay"]))
    else:
        st.info("📤 Telegram için: Streamlit Cloud → Settings → Secrets'a TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID ekle.")

    # --- SES ---
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown("### 🎙️ Seslendirme")
        if sonuc.get("ses_basarili") and sonuc.get("ses_dosyasi") and os.path.exists(sonuc["ses_dosyasi"]):
            with open(sonuc["ses_dosyasi"], "rb") as f:
                st.audio(f.read(), format="audio/wav")
        else:
            st.warning("Ses dosyası mevcut değil.")

    with c2:
        st.markdown("### 🔄 Yeniden Ses")
        yeni_metin = st.text_area("Metni düzenle", value=veri.get("seslendirme_metni", ""), height=120, key="yeniden_ses_metin")
        if st.button("🔊 Yeniden Üret", use_container_width=True):
            with st.spinner("Ses üretiliyor..."):
                yeni_dosya = router.ses_uret(yeni_metin, sonuc.get("ses_adi", "Autonoe"))
            if yeni_dosya:
                st.session_state.gecici_ses_dosyalari.append(yeni_dosya)
                sonuc["ses_dosyasi"] = yeni_dosya
                sonuc["ses_basarili"] = True
                st.rerun()
            else:
                st.error("Ses üretimi başarısız.")

    # --- SESLENDİRME METNİ ---
    st.markdown("### 📝 Seslendirme Metni")
    st.text_area("", value=veri.get("seslendirme_metni", ""), height=200, disabled=True, key="ses_metin_goster")

    # --- REELS AÇIKLAMASI ---
    st.markdown("### 📱 Reels Açıklaması")
    st.text_area("", value=veri.get("reels_aciklamasi", ""), height=200, disabled=True, key="reels_aciklama_goster")

    # --- HASHTAGLER ---
    st.markdown("### #️⃣ Hashtagler")
    hashtagler = veri.get("reels_hashtagleri", [])
    if hashtagler:
        st.code(" ".join([h if str(h).startswith("#") else f"#{h}" for h in hashtagler]))

    # --- KAPAK BAŞLIKLARI ---
    st.markdown("### 🏷️ Kapak Başlıkları")
    kapaklar = veri.get("kapak_basliklari", [])
    if kapaklar:
        for i, k in enumerate(kapaklar, 1):
            if isinstance(k, dict):
                st.markdown(f"**{i}.** `{k.get('ana', '')}` — _{k.get('alt', '')}_")
            else:
                st.markdown(f"**{i}.** `{k}`")

    # --- THREADS ---
    st.markdown("### 🧵 Threads Açıklaması")
    st.text_area("", value=veri.get("threads_aciklamasi", ""), height=120, disabled=True, key="threads_goster")

    # --- DÜŞÜNCE ZİNCİRİ ---
    with st.expander("🧠 Düşünce Zinciri (CoT)"):
        st.markdown("**Beyin Fırtınası:**")
        st.text(veri.get("beyin_firtinasi", ""))
        st.markdown("**Veri Kilitleme:**")
        st.text(veri.get("veri_kilitleme", ""))
        st.markdown("**Öz Eleştiri:**")
        st.text(veri.get("oz_elestiri", ""))

    # --- LOG ---
    if st.session_state.log_satirlari:
        with st.expander("📜 İşlem Günlüğü"):
            for satir in st.session_state.log_satirlari:
                st.caption(satir)
