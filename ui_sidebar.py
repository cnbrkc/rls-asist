"""Sidebar bileşeni: Ses seçimi, API key'ler, banlar, geçmiş üretimler."""
import time
import streamlit as st

from config import API_KEYS
from storage import kayitlari_yukle, tum_kayitlari_sil


def render_sidebar() -> None:
    """Sol sidebar'ı çiz: ses seçimi, key'ler, banlar, geçmiş."""
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

        if st.session_state.get("blacklist"):
            st.markdown("**🚫 Banlar**")
            now = time.time()
            aktif_ban = {k: v for k, v in st.session_state.blacklist.items() if v > now}
            if aktif_ban:
                for ban_key, bitis in aktif_ban.items():
                    kalan = int(bitis - now)
                    kalan_str = f"{kalan // 3600}sa" if kalan > 3600 else f"{kalan // 60}dk"
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
                        "final_video": ""
                    }
                    st.session_state._sonuc_versiyon += 1
                    st.rerun()
        else:
            st.caption("Henüz kayıt yok")

        if kayitlar and st.button("🗑️ Tüm Geçmişi Sil", use_container_width=True):
            tum_kayitlari_sil()
            st.rerun()
