import streamlit as st
import streamlit.components.v1 as components
import time
import os
import uuid
import traceback
import re

# Kendi modüllerimiz
from config import API_KEYS, SES_HIZ_CARpanI, MAX_INPUT_KARAKTER
from utils import (
    kayitlari_yukle, tum_kayitlari_sil, kayit_ekle,
    eski_ses_dosyalarini_temizle, prompt_dosyasini_oku,
    sistem_talimati_olustur, markdown_temizle, kapak_basliklarini_formatla,
    temp_dosya_temizle
)
from router import SmartRouter

# ============================================================
# SAYFA AYARLARI
# ============================================================
st.set_page_config(page_title="otoXtra", page_icon="🏎️", layout="wide")

st.markdown("""
<style>
    .main .block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stTextArea textarea { font-size: 14px; }
    .stButton button { width: 100%; height: 48px; font-size: 16px; font-weight: 600; }
    [data-testid="stCaptionContainer"] { font-size: 12px; margin-bottom: 0.25rem; }
    [data-testid="stVideo"] video { max-height: 200px; }
    .streamlit-expanderHeader { font-size: 14px; }
    .gecmis-item { padding: 8px; margin: 4px 0; border-radius: 6px; cursor: pointer; }
    .gecmis-item:hover { background-color: #f0f0f0; }
</style>
""", unsafe_allow_html=True)

st.markdown("### 🏎️ otoXtra")
st.caption("Reels + Threads otomatik üretim")

# ============================================================
# SESSION STATE BAŞLATMA
# ============================================================
if "sonuc" not in st.session_state:
    st.session_state.sonuc = None
if "log_satirlari" not in st.session_state:
    st.session_state.log_satirlari = []
if "gecici_ses_dosyalari" not in st.session_state:
    st.session_state.gecici_ses_dosyalari = []

# Widget'lar için session state başlangıç değerleri
if "sure_saniye" not in st.session_state:
    st.session_state.sure_saniye = 30
if "video_analiz_notlari" not in st.session_state:
    st.session_state.video_analiz_notlari = ""
if "metin_uretim_notlari" not in st.session_state:
    st.session_state.metin_uretim_notlari = ""
if "icerik_tonu" not in st.session_state:
    st.session_state.icerik_tonu = "⚖️ Dengeli (%50 bilgi)"

router = SmartRouter()
eski_ses_dosyalarini_temizle()

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("**🎙️ Ses**")
    ses_secimi = st.selectbox(
        "Seslendiren",
        [
            "Autonoe (Parlak - Kadın)", "Puck (Enerjik - Erkek)",
            "Aoede (Yumuşak - Kadın)", "Callirrhoe (Doğal - Kadın)",
            "Kore (Net - Kadın)", "Leda (Dinamik - Kadın)",
            "Zephyr (Parlak - Kadın)", "Charon (Bilgi - Erkek)",
            "Orus (Sert - Erkek)", "Iapetus (Akıcı - Erkek)",
            "Umbriel (Rahat - Erkek)"
        ],
        label_visibility="collapsed",
        key="ses_secimi"   # key eklendi
    )

    st.markdown("**🔑 Key'ler**")
    for mail in API_KEYS.keys():
        st.caption(f"• {mail}")

    if st.session_state.blacklist:
        st.markdown("**🚫 Banlar**")
        now = time.time()
        aktif_ban = {k: v for k, v in st.session_state.blacklist.items() if v > now}
        if aktif_ban:
            for ban_key, bitis in aktif_ban.items():
                kalan = int(bitis - now)
                kalan_str = f"{kalan // 3600}s" if kalan > 3600 else f"{kalan // 60}dk"
                st.caption(f"⛔ {ban_key} ({kalan_str})")
        else:
            st.caption("✅ Temiz")

    st.divider()
    st.markdown("**📜 Geçmiş Üretimler**")

    kayitlar = kayitlari_yukle()
    if kayitlar:
        st.caption(f"Son {len(kayitlar)} üretim:")
        for i, kayit in enumerate(reversed(kayitlar)):
            if st.button(
                f"📝 {kayit.get('tarih', '?')} ({kayit.get('sure_saniye', '?')}sn - {kayit.get('ses_adi', '?')})",
                key=f"kayit_{i}",
                use_container_width=True
            ):
                st.session_state.sonuc = {
                    "veri": {
                        "seslendirme_metni": kayit.get("seslendirme_metni", ""),
                        "reels_aciklamasi": kayit.get("reels_aciklamasi", ""),
                        "reels_hashtagleri": kayit.get("reels_hashtagleri", []),
                        "kapak_basliklari": kayit.get("kapak_basliklari", []),
                        "threads_aciklamasi": kayit.get("threads_aciklamasi", ""),
                    },
                    "ses_basarili": False,
                    "ses_dosyasi": "",
                    "secilen_ses_ingilizce": kayit.get("ses_adi", ""),
                    "kullanilan_metin_modeli": "geçmiş",
                    "kullanilan_ses_modeli": "geçmiş",
                    "kullanilan_threads_modeli": "geçmiş",
                }
                st.rerun()
    else:
        st.caption("Henüz kayıt yok")

    if kayitlar and st.button("🗑️ Tüm Geçmişi Sil", use_container_width=True):
        tum_kayitlari_sil()
        st.rerun()

# ============================================================
# ANA ARAYÜZ
# ============================================================
uploaded_video = st.file_uploader(
    "🎥 Referans Video",
    type=['mp4', 'mov', 'webm'],
    help="Yüklersen AI analiz eder, yüklemezsen aşağıya kendi analizini yazarsın",
    key="video_uploader"   # key eklendi
)
video_buyuk = uploaded_video is not None and uploaded_video.size > 20 * 1024 * 1024

if uploaded_video is not None:
    st.video(uploaded_video)
    if video_buyuk:
        st.warning("⚠️ Video 20 MB üstü! Sıkıştırın.")

c1, c2 = st.columns(2)
with c1:
    video_analiz_notlari = st.text_area(
        "🔍 Analiz Notları",
        height=90,
        placeholder="Video varsa: 'Motor sesi bul'\nVideo yoksa: Kendi analizin",
        key="video_analiz_notlari"   # key eklendi
    )
with c2:
    metin_uretim_notlari = st.text_area(
        "✍️ Üretim Notları",
        height=90,
        placeholder="'Fiyat söyleme'\n'Performans vurgula'",
        key="metin_uretim_notlari"   # key eklendi
    )

# --- SORUN GİDERİLDİ: Bu satıra key eklendi ve değer int() ile garanti edildi ---
sure_saniye = int(st.number_input(
    "⏱️ Hedef Süre (sn)",
    min_value=5,
    max_value=180,
    value=st.session_state.sure_saniye,
    step=5,
    key="sure_saniye"   # ← BURASI ÇOK ÖNEMLİ
))

icerik_tonu = st.radio(
    "🎯 İçerik Tonu",
    ["🎭 Eğlence Ağırlıklı (%25 bilgi)", "⚖️ Dengeli (%50 bilgi)", "🧠 Bilgi Ağırlıklı (%75 bilgi)", "📊 Teknik Odaklı (%90 bilgi)"],
    index=1,
    horizontal=True,
    key="icerik_tonu"   # key eklendi
)

buton_tiklandi = st.button("🚀 ÜRET!", disabled=video_buyuk, use_container_width=True)

progress_bar = st.empty()
log_kutusu = st.empty()

# ============================================================
# LOG VE İLERLEME FONKSİYONLARI
# ============================================================
def gunlugu_ciz() -> None:
    if st.session_state.log_satirlari:
        log_kutusu.code("\n".join(st.session_state.log_satirlari), language=None)
    else:
        log_kutusu.empty()

def log_ekle(satir: str) -> None:
    st.session_state.log_satirlari.append(satir)
    gunlugu_ciz()

def ilerlemeyi_guncelle(adim: int, toplam: int, mesaj: str) -> None:
    progress_bar.progress(adim / toplam, text=mesaj)

def sekmeyi_aktif_tut() -> None:
    components.html("""
    <script>
    async function keepAlive() {
        if ('wakeLock' in navigator) {
            try {
                let wakeLock = await navigator.wakeLock.request('screen');
                document.addEventListener('visibilitychange', async () => {
                    if (wakeLock !== null && document.visibilityState === 'visible') {
                        wakeLock = await navigator.wakeLock.request('screen');
                    }
                });
            } catch (err) {}
        }
        try {
            var audioContext = new (window.AudioContext || window.webkitAudioContext)();
            var oscillator = audioContext.createOscillator();
            var gainNode = audioContext.createGain();
            gainNode.gain.value = 0.00001;
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            setInterval(() => { if (audioContext.state === 'suspended') audioContext.resume(); }, 2000);
            oscillator.start(0);
            window.addEventListener('beforeunload', function() { oscillator.stop(); });
        } catch(e) {}
    }
    keepAlive();
    </script>
    """, height=0)

gunlugu_ciz()

# ============================================================
# ÜRETİM AKIŞI
# ============================================================
if buton_tiklandi:
    sekmeyi_aktif_tut()
    st.session_state.log_satirlari = []
    log_ekle("🚀 Üretim başladı...")
    ilerlemeyi_guncelle(0, 4, "Başlatılıyor...")

    try:
        # ADIM 1: Video Analiz
        ilerlemeyi_guncelle(1, 4, "🎥 Video analiz ediliyor...")
        if uploaded_video is not None:
            log_ekle("🎥 Video analiz ediliyor...")
            analiz_metni, _ = router.video_analiz_et(
                uploaded_video.getvalue(),
                uploaded_video.type or "video/mp4",
                video_analiz_notlari,
                sure_saniye,
                log_ekle
            )
            log_ekle("🧠 Analiz tamamlandı, üretiliyor...")
        else:
            if not video_analiz_notlari.strip():
                st.warning("⚠️ Video yok, analiz notu yazın.")
                st.stop()
            analiz_metni = video_analiz_notlari.strip()
            log_ekle("📝 Manuel analiz kullanılıyor...")

        video_icerigi = f"VİDEO ANALİZ SONUCU:\n{analiz_metni}\n\nMETİN ÜRETİM NOTLARI:\n{metin_uretim_notlari.strip() if metin_uretim_notlari.strip() else 'Ek not yok.'}"

        if len(video_icerigi) > MAX_INPUT_KARAKTER:
            kirpilmis = video_icerigi[:MAX_INPUT_KARAKTER]
            kesim_noktasi = max(kirpilmis.rfind(" "), kirpilmis.rfind("."))
            video_icerigi = kirpilmis[:kesim_noktasi if kesim_noktasi > int(MAX_INPUT_KARAKTER * 0.9) else MAX_INPUT_KARAKTER].strip()
            log_ekle("⚠️ İçerik kısaltıldı.")

        # ADIM 2: Metin Üretimi
        ilerlemeyi_guncelle(2, 4, "✍️ Metin üretiliyor...")
        system_prompt = prompt_dosyasini_oku("kurallar.txt") + sistem_talimati_olustur(sure_saniye, icerik_tonu)

        response_schema = {
            "type": "OBJECT",
            "properties": {
                "beyin_firtinasi": {"type": "STRING", "description": "Seslendirme metnini yazmadan ÖNCE buraya stratejini yaz. Videodaki görsel akışa göre 4 vuruşu nasıl eşleştireceğini ve Türk psikolojisine hangi senaryoyu sokacağını planla."},
                "veri_kilitleme": {"type": "STRING", "description": "Video analizinden ve internet aramasından gelen tüm kesin rakamları (fiyat, beygir, 0-100 vb.) buraya listele. Metni yazarken SADECE bu rakamları kullan."},
                "oz_elestiri": {"type": "STRING", "description": "Kendi planını kurallar.txt'ye göre denetle: Kelime sayısı aralığında mı, Loop (sonsuz döngü) var mı, yasaklı kelimeler var mı? Hata bulursan asıl metni yazarken düzelt."},
                "seslendirme_metni": {"type": "STRING"},
                "reels_aciklamasi": {"type": "STRING"},
                "reels_hashtagleri": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Reels açıklaması için 5 adet ilgili hashtag. Başlarına # işareti ekle."},
                "kapak_basliklari": {
                    "type": "ARRAY",
                    "items": {"type": "OBJECT", "properties": {"ana": {"type": "STRING"}, "alt": {"type": "STRING"}}, "required": ["ana", "alt"]},
                },
            },
            "required": ["beyin_firtinasi", "veri_kilitleme", "oz_elestiri", "seslendirme_metni", "reels_aciklamasi", "reels_hashtagleri", "kapak_basliklari"],
        }

        veri, kullanilan_metin_modeli = router.metin_uret(video_icerigi, system_prompt, response_schema, log_ekle, arama_kullan=False)

        # ADIM 3: Threads Üretimi
        ilerlemeyi_guncelle(3, 4, "🧵 Threads üretiliyor...")
        log_ekle("🧵 Threads üretiliyor...")
        threads_icerigi = f"INSTAGRAM AÇIKLAMASI:\n{veri.get('reels_aciklamasi', '')}\n\nGÖREV: Bu Instagram açıklamasını Threads ve X için daha sohbet havasında, kısa ve akıcı bir metne dönüştür."
        threads_system_prompt = prompt_dosyasini_oku("threads_promptu.txt")
        threads_schema = {"type": "OBJECT", "properties": {"threads_aciklamasi": {"type": "STRING"}}, "required": ["threads_aciklamasi"]}

        try:
            threads_veri, kullanilan_threads_modeli = router.metin_uret(threads_icerigi, threads_system_prompt, threads_schema, log_ekle, model_listesi=METIN_MODELLERI, arama_kullan=False)
            veri["threads_aciklamasi"] = str(threads_veri.get("threads_aciklamasi", "")).strip()
        except Exception as threads_hata:
            log_ekle(f"⚠️ Threads hatası, fallback kullanılıyor: {str(threads_hata)[:100]}")
            fallback = re.sub(r"\s+", " ", veri.get("reels_aciklamasi", "")).strip()
            veri["threads_aciklamasi"] = fallback[:500].rstrip()
            kullanilan_threads_modeli = "fallback"

        # ADIM 4: Ses Üretimi
        ilerlemeyi_guncelle(4, 4, "🎙️ Ses üretiliyor...")
        secilen_ses_ingilizce = ses_secimi.split(" ")[0]
        ses_dosyasi = os.path.join(tempfile.gettempdir(), f"ses_{uuid.uuid4().hex[:8]}.wav")
        ses_basarili, kullanilan_ses_modeli = router.ses_uret(
            veri["seslendirme_metni"],
            secilen_ses_ingilizce,
            ses_dosyasi,
            log_ekle,
            hiz_carpani=SES_HIZ_CARpanI
        )

        if ses_basarili and os.path.exists(ses_dosyasi):
            st.session_state.gecici_ses_dosyalari.append(ses_dosyasi)

        log_ekle("🏁 Tamamlandı.")
        ilerlemeyi_guncelle(4, 4, "✅ Tamamlandı!")

        kayit_ekle({
            "seslendirme_metni": veri.get("seslendirme_metni", ""),
            "reels_aciklamasi": veri.get("reels_aciklamasi", ""),
            "reels_hashtagleri": veri.get("reels_hashtagleri", []),
            "kapak_basliklari": veri.get("kapak_basliklari", []),
            "threads_aciklamasi": veri.get("threads_aciklamasi", ""),
            "ses_adi": secilen_ses_ingilizce,
            "sure_saniye": sure_saniye,
        })

        st.session_state.sonuc = {
            "veri": veri,
            "ses_basarili": ses_basarili,
            "ses_dosyasi": ses_dosyasi,
            "secilen_ses_ingilizce": secilen_ses_ingilizce,
            "kullanilan_metin_modeli": kullanilan_metin_modeli,
            "kullanilan_ses_modeli": kullanilan_ses_modeli,
            "kullanilan_threads_modeli": kullanilan_threads_modeli,
        }

    except Exception as e:
        if "StopException" in type(e).__name__ or "RerunException" in type(e).__name__ or "StopExecution" in str(type(e)):
            raise
        hata_detay = traceback.format_exc()
        for api_key in API_KEYS.values():
            hata_detay = hata_detay.replace(api_key, "***")
        log_ekle("❌ HATA:")
        log_ekle(hata_detay)
        st.session_state.sonuc = None
        ilerlemeyi_guncelle(0, 4, "❌ Hata!")
        st.error("Hata oluştu. Logu kopyalayın.")

# ============================================================
# SONUÇLARI GÖSTER
# ============================================================
if st.session_state.sonuc:
    sekmeyi_aktif_tut()
    sonuc = st.session_state.sonuc
    veri = sonuc["veri"]
    kullanilan_metin_modeli = sonuc.get("kullanilan_metin_modeli", "?")

    st.success(f"✅ Başarılı! ({kullanilan_metin_modeli})")

    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🗑️ Geçmiş Üretimleri Temizle", use_container_width=True):
            if sonuc.get("ses_dosyasi") and os.path.exists(sonuc["ses_dosyasi"]):
                temp_dosya_temizle(sonuc["ses_dosyasi"])
            for dosya in st.session_state.gecici_ses_dosyalari:
                temp_dosya_temizle(dosya)
            st.session_state.gecici_ses_dosyalari = []
            st.session_state.sonuc = None
            st.session_state.log_satirlari = []
            tum_kayitlari_sil()
            st.rerun()

    st.markdown("### 🎧 Medya")
    st.markdown(f"**🎙️ Seslendirme** (model: {sonuc.get('kullanilan_ses_modeli', '?')})")
    if sonuc["ses_basarili"] and os.path.exists(sonuc["ses_dosyasi"]):
        with open(sonuc["ses_dosyasi"], "rb") as f:
            ses_byte = f.read()
        st.audio(ses_byte, format="audio/wav")
        st.download_button(
            f"⬇️ {sonuc['secilen_ses_ingilizce']} Sesini İndir (.wav)",
            ses_byte,
            file_name="seslendirme.wav",
            mime="audio/wav"
        )
    else:
        if kullanilan_metin_modeli == "geçmiş":
            st.info("📝 Bu geçmiş bir kayıt. Ses dosyası artık mevcut değil.")
        else:
            st.warning("Ses dosyası bulunamadı.")

    st.divider()
    st.markdown("### 📝 Metin İçerikleri")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("1️⃣ Reels Açıklaması")
        st.caption("Katmanlı caption + 5 hashtag")
        aciklama_metni = markdown_temizle(veri.get("reels_aciklamasi", ""))
        hashtagler = veri.get("reels_hashtagleri", [])
        if hashtagler and isinstance(hashtagler, list):
            hashtag_str = " ".join([h if str(h).startswith("#") else f"#{h}" for h in hashtagler])
            tam_aciklama = f"{aciklama_metni}\n\n{hashtag_str}"
        else:
            tam_aciklama = aciklama_metni
        st.code(tam_aciklama, language=None)

    with col2:
        st.subheader("2️⃣ Kapak Başlıkları")
        st.caption("5 alternatif")
        st.code(kapak_basliklarini_formatla(veri.get("kapak_basliklari")), language=None)

    with col3:
        st.subheader("3️⃣ Threads Açıklaması")
        st.caption(f"Kısa, sohbet havasında, hashtagsiz (Model: {sonuc.get('kullanilan_threads_modeli', '?')})")
        st.code(markdown_temizle(veri.get("threads_aciklamasi", "")), language=None)

    st.divider()
    st.markdown("### 🧠 AI Düşünme Zinciri (Strateji)")
    with st.expander("Yapay Zekanın İç Monoloğunu Gör (Nasıl Karar Verdi?)"):
        st.markdown("**1. Beyin Fırtınası:**")
        st.info(veri.get("beyin_firtinasi", "Veri bulunamadı."))
        st.markdown("**2. Veri Kilitleme:**")
        st.warning(veri.get("veri_kilitleme", "Veri bulunamadı."))
        st.markdown("**3. Öz Eleştiri:**")
        st.error(veri.get("oz_elestiri", "Veri bulunamadı."))

    st.divider()
    st.markdown("### 🎙️ Seslendirme Metni")
    st.caption("TTS için üretilen metin. Düzenleyip yeniden ses üretebilirsiniz.")

    duzenlenmis_ses_metni = st.text_area(
        "Seslendirme Metni",
        value=veri.get("seslendirme_metni", ""),
        height=300,
        label_visibility="collapsed",
        key="duzenlenmis_ses_metni_widget",
    )

    if st.button("🔄 Bu Metinle Yeniden Ses Üret"):
        with st.spinner("Ses üretiliyor..."):
            yeni_ses_dosyasi = os.path.join(tempfile.gettempdir(), f"ses_{uuid.uuid4().hex[:8]}.wav")
            ses_basarili_yeni, kullanilan_ses_modeli_yeni = router.ses_uret(
                duzenlenmis_ses_metni,
                sonuc["secilen_ses_ingilizce"],
                yeni_ses_dosyasi,
                log_ekle,
                hiz_carpani=SES_HIZ_CARpanI,
            )

            if ses_basarili_yeni and os.path.exists(yeni_ses_dosyasi):
                # Eski ses dosyasını temizle
                eski_ses_dosyasi = sonuc.get("ses_dosyasi", "")
                if eski_ses_dosyasi and os.path.exists(eski_ses_dosyasi):
                    temp_dosya_temizle(eski_ses_dosyasi)
                    if eski_ses_dosyasi in st.session_state.gecici_ses_dosyalari:
                        st.session_state.gecici_ses_dosyalari.remove(eski_ses_dosyasi)

                st.session_state.sonuc["ses_dosyasi"] = yeni_ses_dosyasi
                st.session_state.sonuc["ses_basarili"] = True
                st.session_state.sonuc["veri"]["seslendirme_metni"] = duzenlenmis_ses_metni
                if kullanilan_ses_modeli_yeni:
                    st.session_state.sonuc["kullanilan_ses_modeli"] = kullanilan_ses_modeli_yeni
                st.session_state.gecici_ses_dosyalari.append(yeni_ses_dosyasi)

                log_ekle("✅ Yeni ses başarıyla üretildi, player güncellendi.")
                st.rerun()
            else:
                st.error("❌ Ses üretilemedi. Logları kontrol edin.")
                if os.path.exists(yeni_ses_dosyasi):
                    temp_dosya_temizle(yeni_ses_dosyasi)
