import streamlit as st
import streamlit.components.v1 as components
import time
import os
import uuid
import traceback
import re
import tempfile

# Kendi modüllerimiz
from config import API_KEYS, SES_HIZ_CARpanI, MAX_INPUT_KARAKTER, METIN_MODELLERI
from utils import (
    kayitlari_yukle, tum_kayitlari_sil, kayit_ekle,
    eski_ses_dosyalarini_temizle, prompt_dosyasini_oku,
    sistem_talimati_olustur, markdown_temizle, kapak_basliklarini_formatla,
    temp_dosya_temizle, video_suresini_al, video_ve_sesi_birlestir_4k_ve_senkronize
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
st.caption("Reels + Threads otomatik üretim & 4K Ses/Görsel Optimizasyonu")

# ============================================================
# SESSION STATE BAŞLATMA
# ============================================================
if "sonuc" not in st.session_state:
    st.session_state.sonuc = None
if "log_satirlari" not in st.session_state:
    st.session_state.log_satirlari = []
if "gecici_ses_dosyalari" not in st.session_state:
    st.session_state.gecici_ses_dosyalari = []

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
        key="ses_secimi"
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
                    "kapak_saniyesi": 1.0,
                    "kapak_resmi_yolu": "",
                    "final_4k_video": ""
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
    "🎥 Referans Video (Süre ve kapak otomatik algılanır)",
    type=['mp4', 'mov', 'webm'],
    help="Videoyu yüklersiniz; süre otomatik tespit edilir ve ses/4K render buna göre ayarlanır.",
    key="video_uploader"
)
video_buyuk = uploaded_video is not None and uploaded_video.size > 50 * 1024 * 1024

if uploaded_video is not None:
    st.video(uploaded_video)
    if video_buyuk:
        st.warning("⚠️ Video 50 MB üstü! Sıkıştırmanız önerilir.")

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

icerik_tonu = st.radio(
    "🎯 İçerik Tonu",
    ["🎭 Eğlence Ağırlıklı (%25 bilgi)", "⚖️ Dengeli (%50 bilgi)", "🧠 Bilgi Ağırlıklı (%75 bilgi)", "📊 Teknik Odaklı (%90 bilgi)"],
    index=1,
    horizontal=True,
    key="icerik_tonu"
)

buton_tiklandi = st.button("🚀 ÜRET VE 4K HAZIRLA!", disabled=uploaded_video is None, use_container_width=True)
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

def sekmeyi_aktif_tut() -> None:
    pass

gunlugu_ciz()

# ============================================================
# ÜRETİM AKIŞI
# ============================================================
if buton_tiklandi and uploaded_video is not None:
    sekmeyi_aktif_tut()
    st.session_state.log_satirlari = []
    log_ekle("🚀 Üretim başladı...")
    ilerlemeyi_guncelle(0, 4, "Başlatılıyor...")

    temp_input_video = os.path.join(tempfile.gettempdir(), f"input_{uuid.uuid4().hex[:8]}.mp4")
    with open(temp_input_video, "wb") as f:
        f.write(uploaded_video.getvalue())

    try:
        # OTOMATİK SÜRE TESPİTİ
        sure_saniye = int(round(video_suresini_al(temp_input_video)))
        if sure_saniye < 1:
            st.warning("⚠️ Videonun süresi otomatik okunamadı! Lütfen videonun süresini (saniye cinsinden) aşağıya girin:")
            manual_sure = st.number_input("⏱️ Manuel Süre Girişi (sn)", min_value=1, max_value=300, value=30, step=1, key="manual_sure_input")
            if st.button("Devam Et", key="manual_sure_btn"):
                sure_saniye = int(manual_sure)
            else:
                st.stop()
        log_ekle(f"⏱️ Video süresi: {sure_saniye} saniye")

        # ADIM 1: Video Analiz
        ilerlemeyi_guncelle(1, 4, "🎥 Video analiz ediliyor (Kapak anı tespit ediliyor)...")
        log_ekle("🎥 Video analiz ediliyor...")
        
        analiz_metni, _ = router.video_analiz_et(
            uploaded_video.getvalue(),
            uploaded_video.type or "video/mp4",
            video_analiz_notlari,
            sure_saniye,
            log_ekle
        )

        # Kapak anı saniye tespiti
        kapak_saniyesi = 1.0
        match_kapak = re.search(r"KAPAK_ANI_SANİYE[:\s]+([\d\.]+)", analiz_metni, re.IGNORECASE)
        if match_kapak:
            try:
                kapak_saniyesi = float(match_kapak.group(1))
            except ValueError:
                pass
        log_ekle(f"📸 Tespit edilen kapak anı saniyesi: {kapak_saniyesi}sn")

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
                "beyin_firtinasi": {"type": "STRING", "description": "Seslendirme metnini yazmadan ÖNCE buraya stratejini yaz. Videodaki görsel akışa göre 4 vuruşu nasıl eşleştireceğini planla."},
                "veri_kilitleme": {"type": "STRING", "description": "Video analizinden ve internet aramasından gelen kesin rakamları buraya listele."},
                "oz_elestiri": {"type": "STRING", "description": "Kendi planını kurallar.txt'ye göre denetle."},
                "seslendirme_metni": {"type": "STRING"},
                "reels_aciklamasi": {"type": "STRING"},
                "reels_hashtagleri": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Reels açıklaması için 5 adet ilgili hashtag."},
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

        # OTOMATİK 4K RENDER VE SENKRONİZASYON (Süre karşılaştırma ve kapak ekleme dahil)
        log_ekle("🎬 Otomatik 4K upscale, ses senkronizasyonu ve kapak yerleşimi başlatılıyor...")
        output_4k_path = os.path.join(tempfile.gettempdir(), f"output_4k_{uuid.uuid4().hex[:8]}.mp4")
        output_kapak_path = os.path.join(tempfile.gettempdir(), f"kapak_{uuid.uuid4().hex[:8]}.jpg")

        render_basarili = video_ve_sesi_birlestir_4k_ve_senkronize(
            temp_input_video,
            ses_dosyasi,
            kapak_saniyesi,
            output_4k_path,
            output_kapak_path,
            log_ekle
        )

        final_video_yolu = output_4k_path if (render_basarili and os.path.exists(output_4k_path)) else ""
        final_kapak_yolu = output_kapak_path if (os.path.exists(output_kapak_path)) else ""

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
            "kapak_saniyesi": kapak_saniyesi,
            "kapak_resmi_yolu": final_kapak_yolu,
            "final_4k_video": final_video_yolu,
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
    finally:
        temp_dosya_temizle(temp_input_video)

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
            if sonuc.get("final_4k_video") and os.path.exists(sonuc["final_4k_video"]):
                temp_dosya_temizle(sonuc["final_4k_video"])
            if sonuc.get("kapak_resmi_yolu") and os.path.exists(sonuc["kapak_resmi_yolu"]):
                temp_dosya_temizle(sonuc["kapak_resmi_yolu"])
            for dosya in st.session_state.gecici_ses_dosyalari:
                temp_dosya_temizle(dosya)
            st.session_state.gecici_ses_dosyalari = []
            st.session_state.sonuc = None
            st.session_state.log_satirlari = []
            tum_kayitlari_sil()
            st.rerun()

    st.markdown("### 🎬 Hazır 4K Video & Kapak Fotoğrafı")
    
    col_v, col_img = st.columns([2, 1])
    with col_v:
        st.markdown("**📺 4K Optimize Edilmiş & Senkronize Video** (Orijinal ses kapatıldı, AI ses eklendi, boşluksuz 4K upscale yapıldı)")
        if sonuc.get("final_4k_video") and os.path.exists(sonuc["final_4k_video"]):
            with open(sonuc["final_4k_video"], "rb") as f:
                vid_bytes = f.read()
            st.video(vid_bytes)
            st.download_button(
                "⬇️ 4K Optimize Videoyu İndir (.mp4)",
                vid_bytes,
                file_name="otoxtra_4k_final.mp4",
                mime="video/mp4"
            )
        else:
            st.warning("4K video dosyası bulunamadı.")

    with col_img:
        st.markdown(f"**📸 AI Seçilen Kapak Fotoğrafı** ({sonuc.get('kapak_saniyesi', 1.0)}n)")
        if sonuc.get("kapak_resmi_yolu") and os.path.exists(sonuc["kapak_resmi_yolu"]):
            with open(sonuc["kapak_resmi_yolu"], "rb") as f:
                img_bytes = f.read()
            st.image(img_bytes, caption="En çarpıcı an (Kapak)", use_column_width=True)
            st.download_button(
                "⬇️ Kapak Fotoğrafını İndir (.jpg)",
                img_bytes,
                file_name="kapak_fotografi.jpg",
                mime="image/jpeg"
            )
        else:
            st.info("Kapak fotoğrafı oluşturulamadı.")

    st.divider()
    st.markdown("### 🎧 Medya (Ayrı Ses)")
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

    if st.button("🔄 Bu Metinle Yeniden Ses ve 4K Video Üret"):
        with st.spinner("Ses ve 4K video yeniden üretiliyor..."):
            yeni_ses_dosyasi = os.path.join(tempfile.gettempdir(), f"ses_{uuid.uuid4().hex[:8]}.wav")
            ses_basarili_yeni, kullanilan_ses_modeli_yeni = router.ses_uret(
                duzenlenmis_ses_metni,
                sonuc["secilen_ses_ingilizce"],
                yeni_ses_dosyasi,
                log_ekle,
                hiz_carpani=SES_HIZ_CARpanI,
            )

            if ses_basarili_yeni and os.path.exists(yeni_ses_dosyasi):
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

                log_ekle("✅ Yeni ses ve 4K video başarıyla güncellendi.")
                st.rerun()
            else:
                st.error("❌ Ses üretilemedi. Logları kontrol edin.")
                if os.path.exists(yeni_ses_dosyasi):
                    temp_dosya_temizle(yeni_ses_dosyasi)
