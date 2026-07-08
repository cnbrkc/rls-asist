import streamlit as st
from google import genai
from google.genai import types
import json
import os
import re
import time
import traceback
import wave

# ============================================================
# otoXtra — Otomatik Reels Asistanı
# GÜVENLİ VERSİYON: API key'ler artık koda gömülü DEĞİL.
# Tüm anahtarlar Streamlit Secrets'tan (güvenli kasa) okunuyor.
# ============================================================

# ------------------------------------------------------------
# API KEY YAPILANDIRMASI (Streamlit Secrets'tan okunuyor)
# ------------------------------------------------------------
try:
    API_KEYS = dict(st.secrets["GEMINI_KEYS"])
    if not API_KEYS:
        raise ValueError("API_KEYS boş")
except Exception as e:
    st.error("🔑 API anahtarları Streamlit Secrets'ta bulunamadı veya boş! Lütfen Secrets ayarlarını kontrol edin.")
    st.stop()

# ------------------------------------------------------------
# COOLDOWN SÜRELERİ (saniye)
# ------------------------------------------------------------
COOLDOWN_KOTA = 24 * 60 * 60       # 24 saat (429 - o key o modeli kullanamaz)
COOLDOWN_SUNUCU = 15 * 60           # 15 dk (503 - o model herkes için çöktü)
COOLDOWN_BULUNAMADI = 24 * 60 * 60  # 24 saat (404 - o model yok)
COOLDOWN_DIGER = 5 * 60             # 5 dk (belirsiz hata)
IP_BAN_KORUMA = 1.0                 # 1 sn (istekler arası bekleme)

# ------------------------------------------------------------
# MODEL LİSTELERİ (Temmuz 2026 - Güncel)
# ------------------------------------------------------------
METIN_MODELLERI = [
    "gemini-3.5-flash",
    "gemini-3.1-pro",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]

SES_MODELLERI = [
    "gemini-3.1-flash-tts",
    "gemini-2.5-flash-preview-tts",
]

VIDEO_ANALIZ_MODELLERI = [
    "gemini-3.5-flash",
    "gemini-3.1-pro",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

# ------------------------------------------------------------
# AKILLI ROUTER
# ------------------------------------------------------------
class SmartRouter:
    """
    Banlama mantığı:
      - 429 (kota)      → KEY+MODEL banlanır (o key o modeli 24 saat kullanamaz)
      - 503 (sunucu)     → MODEL banlanır (hiçbir key o modeli 15 dk kullanamaz)
      - 404 (bulunamadı) → MODEL banlanır (hiçbir key o modeli 24 saat kullanamaz)
      - diğer            → KEY+MODEL banlanır (5 dk)
    Kontrol sırası: MODEL banı → KEY banı → KEY+MODEL banı
    """

    def __init__(self):
        if "blacklist" not in st.session_state:
            st.session_state.blacklist = {}

    # --- Blacklist yönetimi ---

    def _is_banned(self, mail: str, model: str) -> bool:
        """Verilen mail+model kullanabilir mi? (3 katmanlı kontrol)"""
        now = time.time()
        bl = st.session_state.blacklist

        # 1) MODEL banı var mı? (tüm key'ler için)
        model_key = f"*+{model}"
        if model_key in bl:
            if now < bl[model_key]:
                return True
            else:
                del bl[model_key]

        # 2) KEY banı var mı? (tüm modeller için)
        key_ban = f"{mail}+*"
        if key_ban in bl:
            if now < bl[key_ban]:
                return True
            else:
                del bl[key_ban]

        # 3) KEY+MODEL banı var mı?
        combo_key = f"{mail}+{model}"
        if combo_key in bl:
            if now < bl[combo_key]:
                return True
            else:
                del bl[combo_key]

        return False

    def _ban(self, mail: str, model: str, cooldown: int, scope: str):
        """
        scope: 'combo' (key+model), 'model' (tüm key'ler), 'key' (tüm modeller)
        """
        if scope == "model":
            st.session_state.blacklist[f"*+{model}"] = time.time() + cooldown
        elif scope == "key":
            st.session_state.blacklist[f"{mail}+*"] = time.time() + cooldown
        else:
            st.session_state.blacklist[f"{mail}+{model}"] = time.time() + cooldown

    def _parse_hata(self, hata_metni: str):
        """
        Hata metninden (scope, cooldown) döndürür.
        scope: 'combo' | 'model' | 'key'
        """
        h = hata_metni.lower()

        if "429" in hata_metni or "resource_exhausted" in h or "quota" in h:
            return "combo", COOLDOWN_KOTA          # key+model ban
        if "503" in hata_metni or "unavailable" in h:
            return "model", COOLDOWN_SUNUCU         # model ban (herkes için)
        if "404" in hata_metni or "not_found" in h:
            return "model", COOLDOWN_BULUNAMADI     # model ban (herkes için)
        return "combo", COOLDOWN_DIGER              # belirsiz → key+model

    def _handle_hata(self, mail, model, hata_metni, log_ekle):
        """Hatayı loglar, banlar ve ('devam' | 'break_model') döndürür."""
        scope, cooldown = self._parse_hata(hata_metni)

        if scope == "model":
            # Model herkes için banlandı, key döngüsünü kır, sonraki modele geç
            ban_sure = f"{cooldown // 60} dk" if cooldown < 3600 else f"{cooldown // 3600} saat"
            log_ekle(f"   ❌ {model} MODEL bazlı hata → TÜM key'ler için {ban_sure} banlandı")
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"

        else:
            # Key+model banlandı, diğer key'e geç
            ban_sure = f"{cooldown // 60} dk" if cooldown < 3600 else f"{cooldown // 3600} saat"
            log_ekle(f"   ⚠️ {mail} kotası/hatası → {model} ile {ban_sure} banlandı, diğer key deneniyor")
            self._ban(mail, model, cooldown, scope)
            time.sleep(IP_BAN_KORUMA)
            return "devam"

    # --- Üretim metodları ---

    def metin_uret(self, video_icerigi, system_prompt, response_schema, log_ekle):
        son_hata = None
        for model_adi in METIN_MODELLERI:
            log_ekle(f"🧠 Model deneniyor: {model_adi}")
            model_denendi = False

            for mail, api_key in API_KEYS.items():
                if self._is_banned(mail, model_adi):
                    log_ekle(f"   ⏸️ {mail} + {model_adi} banlı, atlanıyor")
                    continue

                model_denendi = True
                log_ekle(f"   🚀 {mail} ile {model_adi} deneniyor...")

                try:
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model=model_adi,
                        contents=video_icerigi,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            response_mime_type="application/json",
                            response_schema=response_schema,
                        ),
                    )
                    veri = json.loads(response.text)
                    log_ekle(f"   ✅ Başarılı → {mail} + {model_adi}")
                    time.sleep(IP_BAN_KORUMA)
                    return veri, f"{mail}+{model_adi}"

                except Exception as e:
                    son_hata = e
                    aksiyon = self._handle_hata(mail, model_adi, str(e), log_ekle)
                    if aksiyon == "break_model":
                        break  # model döngüsünden çık, sonraki modele geç

            if not model_denendi:
                log_ekle(f"   ⏸️ {model_adi} tüm key'ler için banlı, atlanıyor")

        raise son_hata if son_hata else Exception("Tüm model+key kombinasyonları başarısız veya banlı.")

    def ses_uret(self, metin, ses_adi, cikti_dosyasi, log_ekle):
        son_hata = None
        for model_adi in SES_MODELLERI:
            log_ekle(f"🎙️ Model deneniyor: {model_adi}")
            model_denendi = False

            for mail, api_key in API_KEYS.items():
                if self._is_banned(mail, model_adi):
                    log_ekle(f"   ⏸️ {mail} + {model_adi} banlı, atlanıyor")
                    continue

                model_denendi = True
                log_ekle(f"   🚀 {mail} ile {model_adi} deneniyor...")

                try:
                    client = genai.Client(api_key=api_key)
                    tts_response = client.models.generate_content(
                        model=model_adi,
                        contents=metin,
                        config=types.GenerateContentConfig(
                            response_modalities=["AUDIO"],
                            speech_config=types.SpeechConfig(
                                voice_config=types.VoiceConfig(
                                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                        voice_name=ses_adi
                                    )
                                )
                            ),
                        ),
                    )
                    audio_data = tts_response.candidates[0].content.parts[0].inline_data.data
                    with wave.open(cikti_dosyasi, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(audio_data)
                    log_ekle(f"   ✅ Başarılı → {mail} + {model_adi}")
                    time.sleep(IP_BAN_KORUMA)
                    return True, f"{mail}+{model_adi}"

                except Exception as e:
                    son_hata = e
                    aksiyon = self._handle_hata(mail, model_adi, str(e), log_ekle)
                    if aksiyon == "break_model":
                        break

            if not model_denendi:
                log_ekle(f"   ⏸️ {model_adi} tüm key'ler için banlı, atlanıyor")

        log_ekle("❌ Hiçbir ses modeli başarılı olamadı.")
        return False, None

    def video_analiz_et(self, video_bytes, mime_type, kullanici_notlari, log_ekle):
        son_hata = None
        video_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)

        ek_notlar_bolumu = ""
        if kullanici_notlari.strip():
            ek_notlar_bolumu = f"""
            ÖNEMLİ: Kullanıcı videoyu analiz ettirirken sana şu EK İSTEKLERİ/ODAK NOKTALARINI iletti. 
            Analizini yaparken bu istekleri MUTLAKA dikkate al ve videodaki ilgili detayları bu istekler ışığında değerlendir:
            --- KULLANICININ EK İSTEKLERİ ---
            {kullanici_notlari}
            -------------------------------
            """

        analiz_promptu = f"""Sen Türkiye'de sosyal medya (Instagram Reels, TikTok, YouTube Shorts) algoritmalarını ve Türk izleyicisinin psikolojisini avucunun içi gibi bilen, 'viral DNA' çıkaran uzman bir strateistsin.
Yüklediğim videoyu kare kare, sesiyle birlikte analiz et. Amacımız bu videodaki en çarpıcı detayları bulup Türkiye'de patlama yapacak bir kurgu stratejisi oluşturmak.

Bana şu başlıklarda çok net, maddeler halinde rapor ver:

1. VİRAL DETAYLAR & TÜRK İZLEYİCİSİ KANCASI: Videoda Türk izleyicisinin gözünü durduracak, merak uyandıracak veya tartışma yaratacak spesifik detaylar neler? (Örn: Beklenmedik bir fiyat, rakip markayla acımasız bir kıyaslama, günlük hayattan sinir bozucu ama gerçek bir detay, 'bizden biri' hissi veren bir dert). Türkiye piyasası için güncel değilse veya eksikse kendi güncel verilerinle düzelt.
2. KURGU & HIZLANDIRMA STRATEJİSİ: Kullanıcı bu videoyu kurgularken hızlandıracak/krıpacak. Videonun en vurucu 3-4 görsel anını (B-roll, yakın çekim, hızlanma anı) belirt ve "Seslendirme bu anlarda şu tempoda gitmeli" diye not düş.
3. HOOK (GİRİŞ KANCASI) ÖNERİSİ: Videonun ilk 3 saniyesinde izleyiciyi tokat gibi çarpacak, 'kaydırma'yı durduracak o spesifik cümleyi veya görsel efekti öner. (Örn: "Bu arabayı almadan önce bu fiyatı görün...", "Hyundai bayisi bunu duyunca sinirlenecek ama...")
4. KANIŞTIRICI KAPANIŞ (CTA/LOOP) ÖNERİSİ: Videonun son 3 saniyesinde izleyiciyi yorum yapmaya itecek veya videoyu tekrar izletmek için sonunu başına bağlayacak o kritik cümleyi öner.
{ek_notlar_bolumu}

Bu bilgileri, bir sonraki adımda benim 'kurallar.txt' dosyamdaki formata göre seslendirme metni üretmen için bana ham veri olarak ver. Doğrudan analiz sonucunu yaz, ekstra konuşma yapma."""

        for model_adi in VIDEO_ANALIZ_MODELLERI:
            log_ekle(f"🔍 Model deneniyor: {model_adi}")
            model_denendi = False

            for mail, api_key in API_KEYS.items():
                if self._is_banned(mail, model_adi):
                    log_ekle(f"   ⏸️ {mail} + {model_adi} banlı, atlanıyor")
                    continue

                model_denendi = True
                log_ekle(f"   🚀 {mail} ile {model_adi} deneniyor...")

                try:
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model=model_adi,
                        contents=[video_part, analiz_promptu],
                    )
                    log_ekle(f"   ✅ Başarılı → {mail} + {model_adi}")
                    time.sleep(IP_BAN_KORUMA)
                    return response.text, f"{mail}+{model_adi}"

                except Exception as e:
                    son_hata = e
                    aksiyon = self._handle_hata(mail, model_adi, str(e), log_ekle)
                    if aksiyon == "break_model":
                        break

            if not model_denendi:
                log_ekle(f"   ⏸️ {model_adi} tüm key'ler için banlı, atlanıyor")

        raise son_hata if son_hata else Exception("Hiçbir model videoyu analiz edemedi.")


# ------------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# ------------------------------------------------------------

def markdown_temizle(metin: str) -> str:
    if not isinstance(metin, str):
        return ""
    return re.sub(r"\*\*|__", "", metin).strip()


def kapak_basliklarini_formatla(liste) -> str:
    if not isinstance(liste, list) or not liste:
        return markdown_temizle(str(liste)) if liste else "(Kapak başlığı üretilemedi.)"
    satirlar = []
    for i, secenek in enumerate(liste, start=1):
        if isinstance(secenek, dict):
            ana = re.sub(r"[*_#`]", "", str(secenek.get("ana", ""))).strip()
            alt = re.sub(r"[*_#`]", "", str(secenek.get("alt", ""))).strip()
        else:
            ana, alt = re.sub(r"[*_#`]", "", str(secenek)).strip(), ""
        if alt:
            satirlar.append(f"{i}) {ana}\n    {alt}")
        else:
            satirlar.append(f"{i}) {ana}")
    return "\n\n".join(satirlar)


def muzik_onerisini_formatla(muzik_onerisi) -> str:
    if not isinstance(muzik_onerisi, dict):
        return "(Müzik önerisi üretilemedi.)"
    tarz = markdown_temizle(str(muzik_onerisi.get("tarz", "")))
    sarkilar = muzik_onerisi.get("sarki_onerileri", []) or []
    satirlar = [f"Telifsiz Tarz / Mod: {tarz}", ""]
    for s in sarkilar:
        satirlar.append(f"- {markdown_temizle(str(s))}")
    if not sarkilar:
        satirlar.append("(Şarkı önerisi üretilemedi.)")
    return "\n".join(satirlar)


# ------------------------------------------------------------
# SAYFA AYARLARI
# ------------------------------------------------------------
st.set_page_config(page_title="otoXtra Asistanım", page_icon="🏎️", layout="wide")

st.markdown(
    """
    <style>
    pre, code { white-space: pre-wrap !important; word-break: break-word !important; overflow-wrap: anywhere !important; }
    @media (max-width: 640px) {
        .block-container { padding-left: 0.9rem; padding-right: 0.9rem; padding-top: 1.2rem; }
        h2, h3 { font-size: 1.05rem !important; }
        .stButton button { width: 100%; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.subheader("🏎️ otoXtra — Otomatik Reels Asistanı")
st.caption("Viral referans videonuzu yükleyin veya konunuzu yazın; otoXtra Türk izleyicisi için gerisini halletsin!")

if "sonuc" not in st.session_state:
    st.session_state.sonuc = None
if "log_satirlari" not in st.session_state:
    st.session_state.log_satirlari = []

router = SmartRouter()

# ------------------------------------------------------------
# SOL MENÜ
# ------------------------------------------------------------
with st.sidebar:
    st.header("🎙️ Ses Ayarları")
    ses_secimi = st.selectbox("Seslendiren Seçimi", [
        "Autonoe (Parlak ve Canlı - Kadın)", "Puck (Eğlenceli ve Enerjik - Erkek)",
        "Aoede (Havadar ve Yumuşak - Kadın)", "Callirrhoe (Rahat ve Doğal - Kadın)",
        "Kore (Net ve Kendinden Emin - Kadın)", "Leda (Genç ve Dinamik - Kadın)",
        "Zephyr (Parlak - Kadın)", "Charon (Bilgilendirici - Erkek)",
        "Orus (Net ve Sert - Erkek)", "Iapetus (Temiz ve Akıcı - Erkek)", "Umbriel (Rahat - Erkek)"
    ])

    st.divider()
    st.header("🔑 API Key Havuzu")
    for mail in API_KEYS.keys():
        st.caption(f"• {mail}")

    # Blacklist durumu göster
    if st.session_state.blacklist:
        st.divider()
        st.header("🚫 Aktif Banlar")
        now = time.time()
        aktif_ban = {k: v for k, v in st.session_state.blacklist.items() if v > now}
        if aktif_ban:
            for ban_key, bitis in aktif_ban.items():
                kalan = int(bitis - now)
                if kalan > 3600:
                    kalan_str = f"{kalan // 3600}s {kalan % 3600 // 60}dk"
                else:
                    kalan_str = f"{kalan // 60}dk"
                st.caption(f"⛔ {ban_key} ({kalan_str})")
        else:
            st.caption("✅ Ban yok")
    else:
        st.caption("✅ Ban yok")

# ------------------------------------------------------------
# ANA ARAYÜZ
# ------------------------------------------------------------
uploaded_video = st.file_uploader(
    "🎥 Viral Referans Videonu Yükle (Otomatik Analiz Edilsin)",
    type=['mp4', 'mov', 'webm'],
    help="Videoyu yüklersen, AI videoyu izleyip Türk izleyicisi için viral strateji kurar."
)

if uploaded_video is not None:
    st.video(uploaded_video)
    if uploaded_video.size > 20 * 1024 * 1024:
        st.error("⚠️ Video 20 MB'tan büyük! Ücretsiz API limiti için lütfen videoyu sıkıştır (720p).")

konu_ve_istekler = st.text_area(
    "🎬 Videonun konusu ve özel istekler",
    height=150,
    placeholder="Paragraf 1: Videonun genel konusu\n\nParagraf 2: Özel istekler / odaklanılacak detaylar",
)

sc1, sc2 = st.columns([1, 3])
with sc1:
    sure_saniye = st.number_input("⏱️ Hedef Süre (saniye)", min_value=5, max_value=180, value=30, step=5)

buton_tiklandi = st.button("🚀 otoXtra İçeriğini Üret!")
log_kutusu = st.empty()


def gunlugu_ciz():
    if st.session_state.log_satirlari:
        log_kutusu.code("\n".join(st.session_state.log_satirlari), language=None)
    else:
        log_kutusu.empty()


def log_ekle(satir: str):
    st.session_state.log_satirlari.append(satir)
    gunlugu_ciz()


gunlugu_ciz()

# ------------------------------------------------------------
# ÜRETİM
# ------------------------------------------------------------
if buton_tiklandi:
    st.session_state.log_satirlari = []
    log_ekle("🚀 Üretim başladı...")

    try:
        analiz_metni = ""
        if uploaded_video is not None and uploaded_video.size <= 20 * 1024 * 1024:
            log_ekle("🎥 Video yükleniyor ve analiz ediliyor...")
            video_bytes = uploaded_video.getvalue()
            mime_type = uploaded_video.type

            analiz_metni, analiz_modeli = router.video_analiz_et(
                video_bytes, mime_type, konu_ve_istekler, log_ekle
            )
            log_ekle("🧠 Video analiz tamamlandı, kurallara göre içerik üretiliyor...")

            video_icerigi = (
                f"ANALİZ EDİLEN VİDEODAN ÇIKARILAN BİLGİLER VE STRATEJİ:\n{analiz_metni}\n\n"
                f"KULLANICININ GİRDİĞİ TEMEL KONU / NOTLAR:\n"
                f"{konu_ve_istekler.strip() if konu_ve_istekler.strip() else 'Kullanıcı ek not düşmedi, sadece analizdeki viral detayları kullan.'}"
            )
        else:
            if not konu_ve_istekler.strip():
                st.warning("Lütfen videonun konusunu yazın veya bir referans video yükleyin.")
                st.stop()
            video_icerigi = f"VİDEO KONUSU VE ÖZEL İSTEKLER:\n{konu_ve_istekler.strip()}"

        # Kuralları oku
        try:
            with open("kurallar.txt", "r", encoding="utf-8") as f:
                BENIM_GEM_KURALLARIM = f.read()
        except FileNotFoundError:
            st.error("⚠️ 'kurallar.txt' dosyası bulunamadı!")
            st.stop()

        system_prompt = BENIM_GEM_KURALLARIM + f"""

ÖNEMLİ SİSTEM TALİMATI (otoXtra Uygulaması - ÇOK KRİTİK KURALLAR):

1. SÜRE VE KURGU MANTIĞI (ÇOK ÖNEMLİ): 
Kullanıcının aşağıda belirttiği HEDEF SÜRE: {sure_saniye} saniye. 
Orijinal referans video daha uzun veya kısa olsa bile BU SÜREYİ IGNOR ET. Kullanıcı videoyu kurguda hızlandırıp/krıparak tam olarak {sure_saniye} saniyeye getirecektir. 
Sen seslendirme metnini, kurallar.txt'teki kelime sayısı formülünü kullanarak TAM OLARAK {sure_saniye} saniyeye uygun uzunlukta yaz.

2. TELİFSİZ MÜZİK KURALI (ÇOK ÖNEMLİ):
Önerdiğin müzikler KESİNLİKLE telifsiz (royalty-free / no copyright) olmalıdır. 
Telifli ana akım şarkılar (pop, rap, ünlü sanatçılar) ÖNERME. 
Bunun yerine şunları öner: "Kevin MacLeod tarzı", "NCS (NoCopyrightSounds) Electronic", "YouTube Audio Library'deki Patrick Patrikios/Aakash Gandhi altyapıları", "Instagram Ticari Müzik Kütüphanesi'ndeki telifsiz Phonk/Lo-Fi/Cinematic aramaları".

3. ÇIKTI FORMATI:
Yukarıdaki otoXtra kurallarına GÖRE üretim yap. NİHAİ ÇIKTIYI sadece aşağıdaki JSON alanlarına göre ver:

- seslendirme_metni: {sure_saniye} saniyeye tam uyan, 4 vuruş yapısına uygun, TTS motoruna gidecek düz metin. Markdown KULLANMA.
- reels_aciklamasi: Katmanlı Instagram açıklaması + en sonda 5 hashtag. Markdown KULLANMA.
- kapak_basliklari: 5 farklı kapak başlığı. "ana" (TAMAMI BÜYÜK HARF) ve "alt" alanları. Markdown KULLANMA.
- muzik_onerisi: "tarz" (Telifsiz bir tür, örn: royalty-free phonk) ve GERÇEKTEN TELİFSİZ olan 3 şarkı/sanatçı önerisi ("sarki_onerileri" listesi).

alt_metin alanı İSTENMİYOR, üretme.
"""

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "seslendirme_metni": {"type": "STRING"},
                "reels_aciklamasi": {"type": "STRING"},
                "kapak_basliklari": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {"ana": {"type": "STRING"}, "alt": {"type": "STRING"}},
                        "required": ["ana", "alt"],
                    },
                },
                "muzik_onerisi": {
                    "type": "OBJECT",
                    "properties": {
                        "tarz": {"type": "STRING"},
                        "sarki_onerileri": {"type": "ARRAY", "items": {"type": "STRING"}},
                    },
                    "required": ["tarz", "sarki_onerileri"],
                },
            },
            "required": ["seslendirme_metni", "reels_aciklamasi", "kapak_basliklari", "muzik_onerisi"],
        }

        # Metin üret
        veri, kullanilan_metin_modeli = router.metin_uret(
            video_icerigi, system_prompt, response_schema, log_ekle
        )

        # Ses üret
        secilen_ses_ingilizce = ses_secimi.split(" ")[0]
        ses_dosyasi = "seslendirme.wav"
        ses_basarili, kullanilan_ses_modeli = router.ses_uret(
            veri["seslendirme_metni"], secilen_ses_ingilizce, ses_dosyasi, log_ekle
        )

        log_ekle("🎵 Telifsiz müzik önerisi içerikle birlikte üretildi.")
        log_ekle("🏁 Tüm işlem tamamlandı.")

        st.session_state.sonuc = {
            "veri": veri,
            "ses_basarili": ses_basarili,
            "ses_dosyasi": ses_dosyasi,
            "secilen_ses_ingilizce": secilen_ses_ingilizce,
            "kullanilan_metin_modeli": kullanilan_metin_modeli,
            "kullanilan_ses_modeli": kullanilan_ses_modeli,
        }

    except Exception:
        hata_detay = traceback.format_exc()
        log_ekle("❌ HATA OLUŞTU — işlem tamamlanamadı:")
        log_ekle(hata_detay)
        st.error("Sistemde bir hata oluştu. Yukarıdaki süreç kutusunun tamamını kopyalayıp bana gönderirsen hemen bakarım.")

# ------------------------------------------------------------
# SONUÇLARI GÖSTER
# ------------------------------------------------------------
if st.session_state.sonuc:
    sonuc = st.session_state.sonuc
    veri = sonuc["veri"]
    ses_basarili = sonuc["ses_basarili"]
    ses_dosyasi = sonuc["ses_dosyasi"]
    secilen_ses_ingilizce = sonuc["secilen_ses_ingilizce"]
    kullanilan_metin_modeli = sonuc.get("kullanilan_metin_modeli", "?")
    kullanilan_ses_modeli = sonuc.get("kullanilan_ses_modeli", "?")

    st.success(f"✅ otoXtra İçeriği Başarıyla Üretti! (Metin: {kullanilan_metin_modeli})")

    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🔄 Yeniden Sorgu (Temizle)"):
            st.session_state.sonuc = None
            st.session_state.log_satirlari = []
            st.rerun()

    st.markdown("### 🎧 Medya Dosyaları")
    mcol1, mcol2 = st.columns(2)

    with mcol1:
        st.markdown(f"**🎙️ Seslendirme** (model: {kullanilan_ses_modeli})")
        if ses_basarili and os.path.exists(ses_dosyasi):
            st.audio(ses_dosyasi)
            with open(ses_dosyasi, "rb") as f:
                st.download_button(
                    f"⬇️ {secilen_ses_ingilizce} Sesini İndir (.wav)",
                    f, file_name="seslendirme.wav", mime="audio/wav",
                )
        else:
            st.warning("Ses dosyası bulunamadı. Lütfen tekrar üretin.")

    with mcol2:
        st.markdown("**🎵 Telifsiz Müzik Önerisi**")
        muzik_metni = muzik_onerisini_formatla(veri.get("muzik_onerisi"))
        st.code(muzik_metni, language=None)

    st.divider()
    st.markdown("### 📝 otoXtra Metin İçerikleri")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("1️⃣ Reels Açıklaması (Caption & Etiketler)")
        st.caption("Kutunun sağ üst köşesindeki ikonla direkt kopyalayabilirsin.")
        st.code(markdown_temizle(veri.get("reels_aciklamasi", "")), language=None)

    with col2:
        st.subheader("2️⃣ Kapak Başlığı Alternatifleri")
        st.caption("Kutunun sağ üst köşesindeki ikonla direkt kopyalayabilirsin.")
        st.code(kapak_basliklarini_formatla(veri.get("kapak_basliklari")), language=None)

    with st.expander("🎙️ Seslendirme Metni (kontrol için)"):
        st.code(markdown_temizle(veri.get("seslendirme_metni", "")), language=None)

