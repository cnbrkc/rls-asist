import os
import math
import shutil
import traceback

import streamlit as st
import streamlit.components.v1 as components

from config import (
    API_KEYS,
    MAX_VIDEO_BOYUT,
    MIN_SURE_SANIYE,
    MAX_SURE_SANIYE,
    VIDEO_FORMATLARI,
    TON_EGLENCE,
    TON_DENGELI,
    TON_BILGI,
    TON_TEKNIK,
    PIPELINE_ADIMLARI,
)
from storage import kayit_ekle
from media import (
    eski_ses_dosyalarini_temizle,
    temp_dosya_temizle,
    video_suresini_al,
    gecici_dosya_yolu,
)
from router import SmartRouter
from pipeline import pipeline_calistir
from ui_sidebar import render_sidebar
from ui_results import render_results


# ============================================================
# SAYFA AYARLARI
# ============================================================

st.set_page_config(
    page_title="otoXtra",
    page_icon="🏎️",
    layout="wide",
)

st.markdown(
    """
<style>
.main .block-container {
    padding-top: 0.25rem;
    padding-bottom: 0.35rem;
    max-width: 900px;
}

.stTextArea textarea {
    font-size: 13px;
}

.stButton button {
    width: 100%;
    height: 44px;
    font-size: 15px;
    font-weight: 600;
}

[data-testid="stCaptionContainer"] {
    font-size: 12px;
    margin-bottom: 0.15rem;
}

[data-testid="stVideo"] video {
    max-height: 180px;
}

.streamlit-expanderHeader {
    font-size: 13px;
}
</style>

<link rel="manifest" href="/app/static/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="otoXtra">
<meta name="theme-color" content="#ff4b4b">
""",
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
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


# ============================================================
# ROUTER
# ============================================================

router = SmartRouter()

# Eski ses dosyalarını temizle.
eski_ses_dosyalarini_temizle()


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def upload_dosyasini_kaydet(upload_obj, hedef_yol: str) -> None:
    """
    Streamlit UploadedFile nesnesini geçici dosyaya kaydeder.
    """
    try:
        upload_obj.seek(0)

        with open(hedef_yol, "wb") as f:
            shutil.copyfileobj(upload_obj, f)

        upload_obj.seek(0)

    except Exception:
        with open(hedef_yol, "wb") as f:
            f.write(upload_obj.getvalue())

        try:
            upload_obj.seek(0)
        except Exception:
            pass


def wake_lock_baslat() -> None:
    """
    Üretim sırasında telefon/ekranın uykuya geçmesini mümkün olduğunca
    engeller ve sayfadan ayrılma konusunda uyarı verir.
    """
    components.html(
        """
<script>
window._otoxtra_wakeLock = null;

async function requestWakeLock() {
    try {
        if ("wakeLock" in navigator) {
            window._otoxtra_wakeLock =
                await navigator.wakeLock.request("screen");
        }
    } catch (e) {}
}

requestWakeLock();

window._otoxtra_beforeunload = function(e) {
    e.preventDefault();
    e.returnValue = "otoXtra üretim devam ediyor!";
    return e.returnValue;
};

window.addEventListener(
    "beforeunload",
    window._otoxtra_beforeunload
);
</script>
""",
        height=0,
    )


def wake_lock_durdur() -> None:
    """
    Üretim tamamlandığında Wake Lock ve beforeunload uyarısını kaldırır.
    """
    components.html(
        """
<script>
if (window._otoxtra_wakeLock) {
    try {
        window._otoxtra_wakeLock.release();
    } catch (e) {}

    window._otoxtra_wakeLock = null;
}

if (window._otoxtra_beforeunload) {
    window.removeEventListener(
        "beforeunload",
        window._otoxtra_beforeunload
    );

    window._otoxtra_beforeunload = null;
}
</script>
""",
        height=0,
    )


def hata_detayini_maskeli_hazirla(hata: Exception) -> str:
    """
    Hata traceback'inden Gemini API key'lerini çıkarır.
    """
    detay = traceback.format_exc()

    for api_key in API_KEYS.values():
        try:
            detay = detay.replace(api_key, "***")
        except Exception:
            pass

    return detay


def pipeline_sonucunu_ui_formatina_donustur(
    pipeline_sonuc: dict,
    secilen_ses_ingilizce: str,
    temp_input_video: str,
) -> dict:
    """
    Yeni pipeline.py sonucunu mevcut ui_results.py'nin beklediği
    eski/uyumlu sonuç yapısına dönüştürür.

    Pipeline'ın kendi state'lerini de kaybetmeden saklar.
    """

    pipeline_state = pipeline_sonuc.get("pipeline_state", {}) or {}

    video_state = pipeline_state.get("video_state", {}) or {}
    fact_state = pipeline_state.get("fact_state", {}) or {}
    editorial_state = pipeline_state.get("editorial_state", {}) or {}
    reels_state = pipeline_state.get("reels_state", {}) or {}
    caption_state = pipeline_state.get("caption_state", {}) or {}
    threads_state = pipeline_state.get("threads_state", {}) or {}

    qa_state = pipeline_sonuc.get("qa_result", {}) or {}

    # --------------------------------------------------------
    # ui_results.py'nin mevcut "veri" yapısı
    # --------------------------------------------------------

    veri = {
        # Ana içerikler
        "seslendirme_metni": pipeline_sonuc.get(
            "seslendirme_metni",
            reels_state.get("seslendirme_metni", ""),
        ),

        "reels_aciklamasi": pipeline_sonuc.get(
            "reels_aciklamasi",
            caption_state.get("reels_aciklamasi", ""),
        ),

        "reels_hashtagleri": pipeline_sonuc.get(
            "reels_hashtagleri",
            caption_state.get("reels_hashtagleri", []),
        ),

        "kapak_basliklari": pipeline_sonuc.get(
            "kapak_basliklari",
            reels_state.get("kapak_basliklari", []),
        ),

        "threads_aciklamasi": pipeline_sonuc.get(
            "threads_aciklamasi",
            threads_state.get("threads_aciklamasi", ""),
        ),

        # Mevcut eski UI'nin "AI düşünme zinciri" alanları.
        # Yeni sistemde bunlar Reels Creative aşamasından geliyor.
        "beyin_firtinasi": reels_state.get(
            "beyin_firtinasi",
            "Veri bulunamadı.",
        ),

        "veri_kilitleme": reels_state.get(
            "veri_kilitleme",
            "Veri bulunamadı.",
        ),

        "oz_elestiri": reels_state.get(
            "oz_elestiri",
            "Veri bulunamadı.",
        ),
    }

    # --------------------------------------------------------
    # Yeni pipeline verileri
    # --------------------------------------------------------

    sonuc = {
        # ui_results.py ile uyumlu
        "veri": veri,

        "ses_basarili": pipeline_sonuc.get(
            "ses_basarili",
            False,
        ),

        "ses_dosyasi": pipeline_sonuc.get(
            "ses_dosyasi",
            "",
        ),

        "secilen_ses_ingilizce": pipeline_sonuc.get(
            "secilen_ses_ingilizce",
            secilen_ses_ingilizce,
        ),

        "kullanilan_metin_modeli": pipeline_sonuc.get(
            "kullanilan_metin_modeli",
            "?",
        ),

        "kullanilan_ses_modeli": pipeline_sonuc.get(
            "kullanilan_ses_modeli",
            "?",
        ),

        "kullanilan_threads_modeli": pipeline_sonuc.get(
            "kullanilan_threads_modeli",
            "?",
        ),

        "final_video": pipeline_sonuc.get(
            "final_video",
            "",
        ),

        "temp_input_video": pipeline_sonuc.get(
            "temp_input_video",
            temp_input_video,
        ),

        # ----------------------------------------------------
        # YENİ PIPELINE VERİLERİ
        # ----------------------------------------------------

        "fact_lock": fact_state,

        "editorial_brief": editorial_state,

        "selected_hook": pipeline_sonuc.get(
            "selected_hook",
            {},
        ),

        "qa_result": qa_state,

        "pipeline_state": pipeline_state,

        # Ayrı state'leri doğrudan da sakla.
        # ui_results.py'nin sonraki sürümünde kolay erişim sağlar.
        "video_state": video_state,

        "fact_state": fact_state,

        "editorial_state": editorial_state,

        "reels_state": reels_state,

        "caption_state": caption_state,

        "threads_state": threads_state,

        "qa_state_ilk": pipeline_state.get(
            "qa_state_ilk",
            {},
        ),

        "qa_state_final": pipeline_state.get(
            "qa_state_final",
            qa_state,
        ),
    }

    return sonuc


def gunlugu_ciz(log_kutusu) -> None:
    """
    Session state'teki logları Streamlit ekranına basar.
    """
    if st.session_state.log_satirlari:
        log_kutusu.code(
            "\n".join(st.session_state.log_satirlari),
            language=None,
        )
    else:
        log_kutusu.empty()


# ============================================================
# SIDEBAR
# ============================================================

render_sidebar()


# ============================================================
# ANA ARAYÜZ — VIDEO UPLOAD
# ============================================================

uploaded_video = st.file_uploader(
    "🎥 Referans Video",
    type=VIDEO_FORMATLARI,
    help=(
        "Videoyu yükleyin; süre otomatik tespit edilir ve "
        "AI hedef süresi buna göre belirlenir."
    ),
    key="video_uploader",
)


video_buyuk = (
    uploaded_video is not None
    and uploaded_video.size > MAX_VIDEO_BOYUT
)

# Varsayılan süre.
sure_saniye = 30


# ============================================================
# VIDEO VARSA AYARLAR
# ============================================================

if uploaded_video is not None:

    # --------------------------------------------------------
    # Video önizleme
    # --------------------------------------------------------

    show_uploaded = st.toggle(
        "👁️ Yüklenen Videoyu Göster",
        value=False,
        key="show_uploaded_video",
    )

    if show_uploaded:
        st.video(uploaded_video)

    if video_buyuk:
        st.warning(
            "⚠️ Video 50 MB üstü! Sıkıştırmanız önerilir."
        )

    # --------------------------------------------------------
    # Upload cache anahtarı
    # --------------------------------------------------------

    upload_id = getattr(
        uploaded_video,
        "file_id",
        None,
    )

    if not upload_id:
        upload_id = (
            f"{uploaded_video.name}_"
            f"{uploaded_video.type}"
        )

    upload_key = (
        f"{upload_id}_{uploaded_video.size}"
    )

    # --------------------------------------------------------
    # Video süresini sadece upload değiştiğinde hesapla
    # --------------------------------------------------------

    if st.session_state.get("upload_key") != upload_key:

        temp_check_path = gecici_dosya_yolu(
            "check",
            "mp4",
        )

        detected = 0.0

        try:
            upload_dosyasini_kaydet(
                uploaded_video,
                temp_check_path,
            )

            detected = video_suresini_al(
                temp_check_path
            )

        except Exception:
            detected = 0.0

        finally:
            temp_dosya_temizle(
                temp_check_path
            )

        st.session_state.upload_key = upload_key
        st.session_state.upload_duration = detected

    else:
        detected = st.session_state.get(
            "upload_duration",
            0.0,
        )

    # --------------------------------------------------------
    # Süre
    # --------------------------------------------------------

    if detected >= 1.0:

        # AI hedef süresi:
        # Videonun gerçek süresini aşağı yuvarlıyoruz.
        sure_saniye = max(
            MIN_SURE_SANIYE,
            int(math.floor(detected + 0.0001)),
        )

        st.success(
            f"⏱️ Tespit edilen süre: "
            f"{detected:.2f} sn | "
            f"AI hedef süre: "
            f"{sure_saniye} sn "
            f"(aşağı yuvarlandı)"
        )

    else:

        st.warning(
            "⚠️ Videonun süresi otomatik okunamadı! "
            "Lütfen videonun süresini saniye cinsinden belirtin:"
        )

        sure_saniye = int(
            st.number_input(
                "⏱️ Manuel Süre Girişi (sn)",
                min_value=MIN_SURE_SANIYE,
                max_value=MAX_SURE_SANIYE,
                value=30,
                step=1,
                key="manual_sure_input",
            )
        )

    # --------------------------------------------------------
    # Notlar
    # --------------------------------------------------------

    c1, c2 = st.columns(2)

    with c1:
        video_analiz_notlari = st.text_area(
            "🔍 Analiz Notları",
            height=70,
            placeholder=(
                "Örn: 'Araç hızlanma anını vurgula'"
            ),
            key="video_analiz_notlari",
        )

    with c2:
        metin_uretim_notlari = st.text_area(
            "✍️ Üretim Notları",
            height=70,
            placeholder=(
                "Örn: 'Fiyat söyleme, "
                "performansa odaklan'"
            ),
            key="metin_uretim_notlari",
        )

    # --------------------------------------------------------
    # Ton
    # --------------------------------------------------------

    ton_anahtarlari = [
        TON_EGLENCE,
        TON_DENGELI,
        TON_BILGI,
        TON_TEKNIK,
    ]

    ton_kisa = {
        TON_EGLENCE: "🎭 Eğlence",
        TON_DENGELI: "⚖️ Dengeli",
        TON_BILGI: "🧠 Bilgi",
        TON_TEKNIK: "📊 Teknik",
    }

    icerik_tonu = st.radio(
        "🎯 Ton",
        ton_anahtarlari,
        index=1,
        format_func=lambda k: ton_kisa[k],
        horizontal=True,
        key="icerik_tonu",
    )

else:

    # Video kaldırıldığında eski upload state'lerini temizle.
    st.session_state.pop(
        "upload_key",
        None,
    )

    st.session_state.pop(
        "upload_duration",
        None,
    )

    video_analiz_notlari = ""
    metin_uretim_notlari = ""
    icerik_tonu = TON_DENGELI


# ============================================================
# ÜRET BUTONU
# ============================================================

buton_tiklandi = st.button(
    "🚀 ÜRET!",
    disabled=uploaded_video is None,
    use_container_width=True,
)


if uploaded_video is None:
    st.info(
        "💡 Devam etmek için lütfen yukarıdan "
        "bir video yükleyin."
    )


# ============================================================
# PROGRESS + LOG ALANLARI
# ============================================================

progress_bar = st.empty()
log_kutusu = st.empty()


def log_ekle(satir: str) -> None:
    """
    Pipeline tarafından çağrılan log callback.
    """
    st.session_state.log_satirlari.append(
        str(satir)
    )

    gunlugu_ciz(log_kutusu)


def ilerlemeyi_guncelle(
    adim: int,
    toplam: int,
    mesaj: str,
) -> None:
    """
    Pipeline tarafından çağrılan progress callback.
    """
    if toplam <= 0:
        toplam = len(PIPELINE_ADIMLARI)

    oran = max(
        0.0,
        min(
            1.0,
            adim / toplam,
        ),
    )

    progress_bar.progress(
        oran,
        text=mesaj,
    )

    gunlugu_ciz(log_kutusu)


# ============================================================
# ÜRETİM
# ============================================================

if buton_tiklandi and uploaded_video is not None:

    # --------------------------------------------------------
    # Wake Lock
    # --------------------------------------------------------

    wake_lock_baslat()

    st.warning(
        "⚡ **Üretim devam ediyor — "
        "bu sayfadan ayrılmayın!**",
        icon="⚠️",
    )

    # --------------------------------------------------------
    # Önceki input videosunu temizle
    # --------------------------------------------------------

    eski_sonuc = st.session_state.get(
        "sonuc"
    )

    if eski_sonuc:
        eski_input = eski_sonuc.get(
            "temp_input_video",
            "",
        )

        if eski_input and os.path.exists(
            eski_input
        ):
            temp_dosya_temizle(
                eski_input
            )

    # --------------------------------------------------------
    # Logları temizle
    # --------------------------------------------------------

    st.session_state.log_satirlari = []

    log_ekle("🚀 Ultimate Pipeline başladı...")
    log_ekle(
        f"⏱️ AI hedef video süresi: "
        f"{sure_saniye} saniye"
    )

    ilerlemeyi_guncelle(
        0,
        len(PIPELINE_ADIMLARI),
        "Başlatılıyor...",
    )

    # --------------------------------------------------------
    # Input videosunu geçici dosyaya kaydet
    # --------------------------------------------------------

    temp_input_video = gecici_dosya_yolu(
        "input",
        "mp4",
    )

    upload_dosyasini_kaydet(
        uploaded_video,
        temp_input_video,
    )

    try:

        # ----------------------------------------------------
        # Upload bytes
        # ----------------------------------------------------

        uploaded_video.seek(0)

        video_bytes = uploaded_video.getvalue()

        mime_type = (
            uploaded_video.type
            or "video/mp4"
        )

        # ----------------------------------------------------
        # Ses seçimi
        # ----------------------------------------------------

        ses_secimi = st.session_state.get(
            "ses_secimi",
            "",
        )

        if ses_secimi:
            secilen_ses_ingilizce = (
                ses_secimi.split(" ")[0]
            )
        else:
            # Sidebar normalde her zaman seçim sağlar.
            # Fakat geçmiş / state kaynaklı bir durumda
            # boş kalırsa güvenli fallback.
            secilen_ses_ingilizce = "Autonoe"

            log_ekle(
                "⚠️ Ses seçimi bulunamadı; "
                "Autonoe kullanılacak."
            )

        log_ekle(
            f"🎙️ Seçilen ses: "
            f"{secilen_ses_ingilizce}"
        )

        # ----------------------------------------------------
        # 9 AŞAMALI PIPELINE
        # ----------------------------------------------------

        pipeline_sonuc = pipeline_calistir(
            router=router,
            video_bytes=video_bytes,
            mime_type=mime_type,
            temp_input_video=temp_input_video,
            video_analiz_notlari=video_analiz_notlari,
            metin_uretim_notlari=metin_uretim_notlari,
            sure_saniye=sure_saniye,
            icerik_tonu=icerik_tonu,
            secilen_ses_ingilizce=secilen_ses_ingilizce,
            log_ekle=log_ekle,
            ilerlemeyi_guncelle=ilerlemeyi_guncelle,
        )

        # ----------------------------------------------------
        # Pipeline sonucunu UI sonucuna dönüştür
        # ----------------------------------------------------

        sonuc = pipeline_sonucunu_ui_formatina_donustur(
            pipeline_sonuc=pipeline_sonuc,
            secilen_ses_ingilizce=secilen_ses_ingilizce,
            temp_input_video=temp_input_video,
        )

        # ----------------------------------------------------
        # Ses dosyasını session geçici listesine ekle
        # ----------------------------------------------------

        ses_dosyasi = sonuc.get(
            "ses_dosyasi",
            "",
        )

        if (
            sonuc.get("ses_basarili")
            and ses_dosyasi
            and os.path.exists(ses_dosyasi)
        ):
            if (
                ses_dosyasi
                not in st.session_state.gecici_ses_dosyalari
            ):
                st.session_state.gecici_ses_dosyalari.append(
                    ses_dosyasi
                )

        # ----------------------------------------------------
        # QA özetini logla
        # ----------------------------------------------------

        qa_result = sonuc.get(
            "qa_result",
            {},
        ) or {}

        qa_overall = qa_result.get(
            "overall",
            "BILINMIYOR",
        )

        log_ekle(
            f"🧪 Final QA sonucu: {qa_overall}"
        )

        # ----------------------------------------------------
        # Fact Lock özeti
        # ----------------------------------------------------

        fact_lock = sonuc.get(
            "fact_lock",
            {},
        ) or {}

        if fact_lock:
            log_ekle(
                "🔒 Fact Lock: tamamlandı."
            )

        # ----------------------------------------------------
        # Kalıcı geçmiş kaydı
        # ----------------------------------------------------

        kayit_ekle(
            {
                "seslendirme_metni": sonuc[
                    "veri"
                ].get(
                    "seslendirme_metni",
                    "",
                ),

                "reels_aciklamasi": sonuc[
                    "veri"
                ].get(
                    "reels_aciklamasi",
                    "",
                ),

                "reels_hashtagleri": sonuc[
                    "veri"
                ].get(
                    "reels_hashtagleri",
                    [],
                ),

                "kapak_basliklari": sonuc[
                    "veri"
                ].get(
                    "kapak_basliklari",
                    [],
                ),

                "threads_aciklamasi": sonuc[
                    "veri"
                ].get(
                    "threads_aciklamasi",
                    "",
                ),

                "ses_adi": secilen_ses_ingilizce,

                "sure_saniye": sure_saniye,
            }
        )

        # ----------------------------------------------------
        # Session state'e kaydet
        # ----------------------------------------------------

        st.session_state.sonuc = sonuc

        st.session_state._sonuc_versiyon += 1

        # ----------------------------------------------------
        # Pipeline tamamlandı
        # ----------------------------------------------------

        ilerlemeyi_guncelle(
            len(PIPELINE_ADIMLARI),
            len(PIPELINE_ADIMLARI),
            "✅ Pipeline tamamlandı!",
        )

        log_ekle(
            "🏁 Tüm üretim aşamaları tamamlandı."
        )

        wake_lock_durdur()

    except Exception as e:

        # Streamlit'in özel kontrol exception'larını
        # gereksiz yere yakalamayalım.
        exception_name = type(e).__name__
        exception_text = str(type(e))

        if (
            "StopException" in exception_name
            or "RerunException" in exception_name
            or "StopExecution" in exception_text
        ):
            raise

        # ----------------------------------------------------
        # Hata detayını maskeli oluştur
        # ----------------------------------------------------

        hata_detay = hata_detayini_maskeli_hazirla(e)

        log_ekle("❌ PIPELINE HATASI:")
        log_ekle(hata_detay)

        # ----------------------------------------------------
        # Başarısız üretimin input videosunu temizle
        # ----------------------------------------------------

        if os.path.exists(temp_input_video):
            temp_dosya_temizle(
                temp_input_video
            )

        st.session_state.sonuc = None

        ilerlemeyi_guncelle(
            0,
            len(PIPELINE_ADIMLARI),
            "❌ Hata!",
        )

        wake_lock_durdur()

        st.error(
            "❌ Üretim sırasında hata oluştu. "
            "Aşağıdaki logları kontrol edin."
        )


# ============================================================
# SONUÇLARI GÖSTER
# ============================================================

render_results(
    log_ekle,
    router,
)
