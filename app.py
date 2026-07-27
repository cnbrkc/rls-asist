"""otoXtra — Streamlit arayüzü."""
import os
import json
from datetime import datetime
import streamlit as st

from config import (
    GEMINI_KEYS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    METIN_MODELLERI,
)
from storage import kayitlari_yukle, kayit_ekle
from prompts import (
    prompt_dosyasi_oku,
    sistem_talimatini_hazirla,
    video_analiz_promptunu_hazirla,
)
from utils import json_parse, sekmeyi_aktif_tut
from telegram import telegram_toplu_gonder
from router import SmartRouter

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
        "required": [
            "beyin_firtinasi", "veri_kilitleme", "oz_elestiri",
            "seslendirme_metni", "reels_aciklamasi", "reels_hashtagleri",
            "kapak_basliklari",
        ],
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
        "properties": {"threads_aciklamasi": {"type": "STRING"}},
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
    st.success(
        f"✅ Üretim tamamlandı — {sonuc.get('tarih', '')} | "
        f"{sonuc.get('sure', '?')}sn | ~{sonuc.get('kelime', '?')} kelime"
    )

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
        yeni_metin = st.text_area(
            "Metni düzenle",
            value=veri.get("seslendirme_metni", ""),
            height=120,
            key="yeniden_ses_metin",
        )
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
