import streamlit as st
import streamlit.components.v1 as components
import os
import traceback
import re

# Kendi modüllerimiz
from config import (
    API_KEYS, SES_HIZ_CARPANI, MAX_INPUT_KARAKTER, METIN_MODELLERI,
    VIDEO_FORMATLARI, MAX_VIDEO_BOYUT, MIN_SURE_SANIYE, MAX_SURE_SANIYE,
    TON_ETIKETLERI, TON_EGLENCE, TON_DENGELI, TON_BILGI, TON_TEKNIK,
    METIN_SCHEMA,
)
from storage import kayit_ekle
from media import (
    eski_ses_dosyalarini_temizle, temp_dosya_temizle, video_suresini_al,
    video_ve_sesi_birlestir, gecici_dosya_yolu, gecici_ses_yolu,
)
from prompts import prompt_dosyasini_oku, kurallari_oku, sistem_talimati_olustur
from router import SmartRouter
from ui_sidebar import render_sidebar
from ui_results import render_results

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
<link rel="manifest" href="/app/static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="otoXtra">
<meta name="theme-color" content="#ff4b4b">
""", unsafe_allow_html=True)

st.markdown("### 🏎️ otoXtra")
st.caption("Reels + Threads otomatik üretim & Ses/Video Birleştirme")

# ============================================================
# SESSION STATE BAŞLATMA
# ============================================================
if "sonuc" not in st.session_state:
    st.session_state.sonuc = None
if "log_satirlari" not in st.session_state:
    st.session_state.log_satirlari = []
if "gecici_ses_dosyalari" not in st.session_state:
    st.session_state.gecici_ses_dosyalari = []
if "_sonuc_versiyon" not in st.session_state:
    st.session_state._sonuc_versiyon = 0
if "_sonuc_versiyon_last" not in st.session_state:
    st.session_state._sonuc_versiyon_last = -1
if "blacklist" not in st.session_state:
    st.session_state.blacklist = {}

router = SmartRouter()
eski_ses_dosyalarini_temizle()

# ============================================================
# SIDEBAR
# ============================================================
render_sidebar()

# ============================================================
# ANA ARAYÜZ
# ============================================================
uploaded_video = st.file_uploader(
    "🎥 Referans Video (Süre otomatik algılanır)",
    type=VIDEO_FORMATLARI,
    help="Videoyu yüklersiniz; süre otomatik tespit edilir ve ses buna göre ayarlanır.",
    key="video_uploader"
)
video_buyuk = uploaded_video is not None and uploaded_video.size > MAX_VIDEO_BOYUT

sure_saniye = 30  # Varsayılan

if uploaded_video is not None:
    st.video(uploaded_video)
    if video_buyuk:
        st.warning("⚠️ Video 50 MB üstü! Sıkıştırmanız önerilir.")

    # Hızlı süre tespiti
    temp_check_path = gecici_dosya_yolu("check", "mp4")
    try:
        with open(temp_check_path, "wb") as f:
            f.write(uploaded_video.getvalue())
        detected = video_suresini_al(temp_check_path)
    except Exception:
        detected = 0.0
    finally:
        temp_dosya_temizle(temp_check_path)

    if detected >= 1.0:
        sure_saniye = int(round(detected))
        st.success(f"⏱️ Otomatik tespit edilen video süresi: {sure_saniye} saniye")
    else:
        st.warning("⚠️ Videonun süresi otomatik okunamadı! Lütfen videonun süresini saniye cinsinden belirtin:")
        sure_saniye = int(st.number_input("⏱️ Manuel Süre Girişi (sn)", min_value=MIN_SURE_SANIYE, max_value=MAX_SURE_SANIYE, value=30, step=1, key="manual_sure_input"))

c1, c2 = st.columns(2)
with c1:
    video_analiz_notlari = st.text_area(
        "🔍 Analiz Notları",
        height=90,
        placeholder="Örn: 'Araç hızlanma anını vurgula'",
        key="video_analiz_notlari"
    )
with c2:
    metin_uretim_notlari = st.text_area(
        "✍️ Üretim Notları",
        height=90,
        placeholder="Örn: 'Fiyat söyleme, performansa odaklan'",
        key="metin_uretim_notlari"
    )

# TON radio: Anahtar=TON_*, Etiket=emoji + açıklama
ton_anahtarlari = [TON_EGLENCE, TON_DENGELI, TON_BILGI, TON_TEKNIK]
icerik_tonu = st.radio(
    "🎯 İçerik Tonu",
    ton_anahtarlari,
    index=1,
    format_func=lambda k: TON_ETIKETLERI[k],
    horizontal=True,
    key="icerik_tonu"
)

buton_tiklandi = st.button("🚀 ÜRET!", disabled=uploaded_video is None, use_container_width=True)
if uploaded_video is None:
    st.info("💡 Devam etmek için lütfen yukarıdan bir video yükleyin.")

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

gunlugu_ciz()

# ============================================================
# ÜRETİM AKIŞI
# ============================================================
if buton_tiklandi and uploaded_video is not None:
    # Wake Lock + beforeunload: İşlem sırasında ekranı açık tut, sayfadan ayrılma uyarısı
    components.html("""
    <script>
    // Wake Lock API (ekranı açık tutar)
    window._otoxtra_wakeLock = null;
    async function requestWakeLock() {
        try {
            if ('wakeLock' in navigator) {
                window._otoxtra_wakeLock = await navigator.wakeLock.request('screen');
                console.log('otoXtra: Wake Lock aktif');
            }
        } catch(e) { console.log('otoXtra: Wake Lock hatası:', e); }
    }
    requestWakeLock();

    // beforeunload: Sayfadan ayrılmak isteyince uyarı
    window._otoxtra_beforeunload = function(e) {
        e.preventDefault();
        e.returnValue = 'otoXtra üretim devam ediyor! Çıkmak istediğinize emin misiniz?';
        return e.returnValue;
    };
    window.addEventListener('beforeunload', window._otoxtra_beforeunload);
    </script>
    """, height=0)

    st.warning("⚡ **Üretim devam ediyor — bu sayfadan ayrılmayın!** Ekran açık kalacak.", icon="⚠️")

    # Önceki üretimden kalan geçici video dosyasını temizle
    if st.session_state.sonuc and st.session_state.sonuc.get("temp_input_video"):
        eski_input = st.session_state.sonuc["temp_input_video"]
        if os.path.exists(eski_input):
            temp_dosya_temizle(eski_input)

    st.session_state.log_satirlari = []
    log_ekle("🚀 Üretim başladı...")
    ilerlemeyi_guncelle(0, 4, "Başlatılıyor...")

    temp_input_video = gecici_dosya_yolu("input", "mp4")
    with open(temp_input_video, "wb") as f:
        f.write(uploaded_video.getvalue())

    try:
        log_ekle(f"⏱️ İşlenen video süresi: {sure_saniye} saniye")

        # ADIM 1: Video Analiz
        ilerlemeyi_guncelle(1, 4, "🎥 Video analiz ediliyor...")
        log_ekle("🎥 Video analiz ediliyor...")

        analiz_metni, _ = router.video_analiz_et(
            uploaded_video.getvalue(),
            uploaded_video.type or "video/mp4",
            video_analiz_notlari,
            sure_saniye,
            log_ekle
        )

        video_icerigi = f"VİDEO ANALİZ SONUCU:\n{analiz_metni}\n\nMETİN ÜRETİM NOTLARI:\n{metin_uretim_notlari.strip() if metin_uretim_notlari.strip() else 'Ek not yok.'}"

        if len(video_icerigi) > MAX_INPUT_KARAKTER:
            kirpilmis = video_icerigi[:MAX_INPUT_KARAKTER]
            kesim_noktasi = max(kirpilmis.rfind(" "), kirpilmis.rfind("."))
            video_icerigi = kirpilmis[:kesim_noktasi if kesim_noktasi > int(MAX_INPUT_KARAKTER * 0.9) else MAX_INPUT_KARAKTER].strip()
            log_ekle("⚠️ İçerik kısaltıldı.")

        # ADIM 2: Metin Üretimi
        ilerlemeyi_guncelle(2, 4, "✍️ Metin üretiliyor...")
        system_prompt = kurallari_oku() + sistem_talimati_olustur(sure_saniye, icerik_tonu)

        veri, kullanilan_metin_modeli = router.metin_uret(video_icerigi, system_prompt, METIN_SCHEMA, log_ekle, arama_kullan=False)

        # ADIM 3: Threads Üretimi
        ilerlemeyi_guncelle(3, 4, "🧵 Threads üretiliyor...")
        log_ekle("🧵 Threads üretiliyor...")
        threads_icerigi = f"INSTAGRAM AÇIKLAMASI:\n{veri.get('reels_aciklamasi', '')}\n\nGÖREV: Bu Instagram açıklamasını Threads ve X için daha sohbet havasında, kısa ve akıcı bir metne dönüştür."
        threads_system_prompt = prompt_dosyasini_oku("threads_promptu.txt")
        threads_schema = {"type": "OBJECT", "properties": {"threads_aciklamasi": {"type": "STRING"}}, "required": ["threads_aciklamasi"]}

        try:
            threads_veri, kullanilan_threads_modeli = router.metin_uret(
                threads_icerigi,
                threads_system_prompt,
                threads_schema,
                log_ekle,
                model_listesi=METIN_MODELLERI,
                arama_kullan=False
            )
            veri["threads_aciklamasi"] = str(threads_veri.get("threads_aciklamasi", "")).strip()
        except Exception as threads_hata:
            log_ekle(f"⚠️ Threads hatası, fallback kullanılıyor: {str(threads_hata)[:100]}")
            fallback = re.sub(r"\s+", " ", veri.get("reels_aciklamasi", "")).strip()
            veri["threads_aciklamasi"] = fallback[:500].rstrip()
            kullanilan_threads_modeli = "fallback"

        # ADIM 4: Ses Üretimi
        ilerlemeyi_guncelle(4, 4, "🎙️ Ses üretiliyor...")
        secilen_ses_ingilizce = st.session_state.ses_secimi.split(" ")[0]
        ses_dosyasi = gecici_ses_yolu()
        ses_basarili, kullanilan_ses_modeli = router.ses_uret(
            veri["seslendirme_metni"],
            secilen_ses_ingilizce,
            ses_dosyasi,
            log_ekle,
            hiz_carpani=SES_HIZ_CARPANI
        )

        if ses_basarili and os.path.exists(ses_dosyasi):
            st.session_state.gecici_ses_dosyalari.append(ses_dosyasi)

        # VİDEO + SES BİRLEŞTİRME
        log_ekle("🎬 Videoya AI sesi ekleniyor...")
        output_video_path = gecici_dosya_yolu("output", "mp4")

        render_basarili = video_ve_sesi_birlestir(
            temp_input_video,
            ses_dosyasi,
            output_video_path,
            log_ekle
        )

        final_video_yolu = output_video_path if (render_basarili and os.path.exists(output_video_path)) else ""

        log_ekle("🏁 Tamamlandı.")
        ilerlemeyi_guncelle(4, 4, "✅ Tamamlandı!")

        # Wake Lock + beforeunload serbest bırak
        components.html("""
        <script>
        if (window._otoxtra_wakeLock) {
            window._otoxtra_wakeLock.release();
            window._otoxtra_wakeLock = null;
        }
        if (window._otoxtra_beforeunload) {
            window.removeEventListener('beforeunload', window._otoxtra_beforeunload);
            window._otoxtra_beforeunload = null;
        }
        </script>
        """, height=0)

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
            "final_video": final_video_yolu,
            "temp_input_video": temp_input_video,
        }
        st.session_state._sonuc_versiyon += 1

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
render_results(log_ekle, router)
