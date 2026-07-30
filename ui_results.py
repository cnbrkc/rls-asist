"""Sonuç gösterim bileşeni: Video, ses, metinler, AI düşünme zinciri, yeniden ses üretme."""
import os
import base64
import tempfile
import uuid

import streamlit as st
import streamlit.components.v1 as components

from config import API_KEYS, SES_HIZ_CARpanI
from utils import markdown_temizle, kapak_basliklarini_formatla
from storage import tum_kayitlari_sil
from media import temp_dosya_temizle, video_ve_sesi_birlestir


def render_results(log_ekle, router) -> None:
    """Üretim sonuçlarını ekrana çiz."""
    if not st.session_state.sonuc:
        return

    sonuc = st.session_state.sonuc
    veri = sonuc["veri"]
    kullanilan_metin_modeli = sonuc.get("kullanilan_metin_modeli", "?")

    st.success(f"✅ Başarılı! ({kullanilan_metin_modeli})")

    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button("🗑️ Geçmiş Üretimleri Temizle", use_container_width=True):
            if sonuc.get("ses_dosyasi") and os.path.exists(sonuc["ses_dosyasi"]):
                temp_dosya_temizle(sonuc["ses_dosyasi"])
            if sonuc.get("final_video") and os.path.exists(sonuc["final_video"]):
                temp_dosya_temizle(sonuc["final_video"])
            for dosya in st.session_state.gecici_ses_dosyalari:
                temp_dosya_temizle(dosya)
            st.session_state.gecici_ses_dosyalari = []
            st.session_state.sonuc = None
            st.session_state.log_satirlari = []
            st.session_state._sonuc_versiyon += 1
            tum_kayitlari_sil()
            st.rerun()

    st.markdown("### 🎬 Hazır Video (AI Sesli)")

    st.markdown("**📺 AI Ses Eklenmiş Video** (Orijinal video + AI seslendirme)")
    if sonuc.get("final_video") and os.path.exists(sonuc["final_video"]):
        with open(sonuc["final_video"], "rb") as f:
            vid_bytes = f.read()
        st.video(vid_bytes)

        c_dl, c_share = st.columns(2)
        with c_dl:
            st.download_button(
                "⬇️ İndir (.mp4)",
                vid_bytes,
                file_name="otoxtra_sesli.mp4",
                mime="video/mp4",
                use_container_width=True
            )
        with c_share:
            # Web Share API → iOS'ta "Videoyu Kaydet" = Fotoğraflara gider
            vid_b64 = base64.b64encode(vid_bytes).decode()
            components.html(f"""
            <button onclick="shareVideo()" style="
                width:100%;height:48px;font-size:16px;font-weight:600;
                background:linear-gradient(135deg,#ff4b4b,#ff6b6b);
                color:#fff;border:none;border-radius:8px;cursor:pointer;
            ">📤 Paylaş / Galer Kaydet</button>
            <script>
            async function shareVideo() {{
                try {{
                    const b64 = "{vid_b64}";
                    const bin = atob(b64);
                    const arr = new Uint8Array(bin.length);
                    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                    const file = new File([arr], 'otoxtra_sesli.mp4', {{ type: 'video/mp4' }});
                    if (navigator.share && navigator.canShare({{ files: [file] }})) {{
                        await navigator.share({{ files: [file], title: 'otoXtra Video' }});
                    }} else {{
                        const url = URL.createObjectURL(file);
                        const a = document.createElement('a');
                        a.href = url; a.download = 'otoxtra_sesli.mp4'; a.click();
                        URL.revokeObjectURL(url);
                    }}
                }} catch(e) {{
                    console.log('Share:', e);
                }}
            }}
            </script>
            """, height=55)
    else:
        st.warning("⚠️ Video dosyası oluşturulamadı (ffmpeg hatası). Sadece ses mevcut.")

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
            st.info("📝 Ayrıntılı geçmiş kayıt. Ses dosyası artık mevcut değil.")
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

    # Sonuç değiştiyse (yeni üretim veya geçmiş tıklama) widget key'i temizle
    if st.session_state._sonuc_versiyon != st.session_state._sonuc_versiyon_last:
        st.session_state._sonuc_versiyon_last = st.session_state._sonuc_versiyon
        if "duzenlenmis_ses_metni_widget" in st.session_state:
            del st.session_state["duzenlenmis_ses_metni_widget"]

    # value parametresi: key yoksa AI metnini, varsa session_state'teki kullanıcı düzenlemesini kullan
    duzenlenmis_ses_metni = st.text_area(
        "Seslendirme Metni",
        value=st.session_state.get("duzenlenmis_ses_metni_widget", veri.get("seslendirme_metni", "")),
        height=300,
        label_visibility="collapsed",
        key="duzenlenmis_ses_metni_widget",
    )

    if st.button("🔄 Bu Metinle Yeniden Ses ve Video Üret"):
        with st.spinner("Ses ve video yeniden üretiliyor..."):
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

                log_ekle("✅ Yeni ses başarıyla üretildi.")
                st.rerun()
            else:
                st.error("❌ Ses üretilemedi. Logları kontrol edin.")
                if os.path.exists(yeni_ses_dosyasi):
                    temp_dosya_temizle(yeni_ses_dosyasi)
