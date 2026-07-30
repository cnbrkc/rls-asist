"""Prompt dosyalarını okuma ve oluşturma fonksiyonları."""
import os
import streamlit as st

from config import (
    guncel_tarih_metni,
    KELIME_HIZI_ORANI, KELIME_YUVARLAMA,
)

# ===== PROMPT DOSYASI OKUMA =====
def prompt_dosyasini_oku(dosya_adi: str) -> str:
    try:
        kok_dizin = os.path.dirname(os.path.abspath(__file__))
        tam_yol = os.path.join(kok_dizin, "prompts", dosya_adi)
        with open(tam_yol, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        st.error(f"⚠️ Prompt dosyası bulunamadı: 'prompts/{dosya_adi}'!")
        st.stop()

def kurallari_oku() -> str:
    """kurallar.txt'yi okur ve config'deki kelime sabitleriyle formatlar."""
    sablon = prompt_dosyasini_oku("kurallar.txt")
    return sablon.format(
        kelime_hizi_orani=KELIME_HIZI_ORANI,
        kelime_yuvarlama=KELIME_YUVARLAMA,
    )

# ===== PROMPT OLUŞTURUCULAR =====
def guncellik_talimati_uret() -> str:
    sablon = prompt_dosyasini_oku("guncellik_talimati.txt")
    return sablon.format(bugunun_tarihi=guncel_tarih_metni())

def video_analiz_promptunu_olustur(ek_notlar_bolumu: str, sure_saniye: int) -> str:
    sablon = prompt_dosyasini_oku("video_analiz_promptu.txt")
    return sablon.format(
        ek_notlar_bolumu=ek_notlar_bolumu,
        guncellik_talimati=guncellik_talimati_uret(),
        sure_saniye=sure_saniye
    )

def sistem_talimati_olustur(sure_saniye: int, icerik_tonu: str) -> str:
    # Kelime hedefi: TTS modeli Türkçe'de ~1.7 kelime/saniye üretiyor
    # 2.0 k/s hedefle → AI biraz fazlaysa bile video süresine yakın kalır
    hedef_kelime = round(sure_saniye * KELIME_HIZI_ORANI / KELIME_YUVARLAMA) * KELIME_YUVARLAMA
    min_kelime = max(5, int(hedef_kelime * 0.85))
    max_kelime = int(hedef_kelime * 1.1)

    if "Eğlence Ağırlıklı" in icerik_tonu:
        bilgi_orani = "Her 4 cümleden 1'i TEKNİK BİLGİ, 3'ü SAMİMİ YORUM/EĞLENCE. Hikaye, espri, kişisel deneyim, 'düşünsene' anları ağırlıklı. Teknik bilgi sadece vurgu için kullanılmalı."
    elif "Bilgi Ağırlıklı" in icerik_tonu:
        bilgi_orani = "Her 4 cümleden 3'ü TEKNİK BİLGİ, 1'i SAMİMİ YORUM. Rakam, karşılaştırma, teknik detay, performans verisi ağırlıklı. Eğlence sadece nefes aldırmak için."
    elif "Teknik Odaklı" in icerik_tonu:
        bilgi_orani = "Her 10 cümleden 9'u TEKNİK BİLGİ, 1'i SAMİMİ YORUM. Neredeyse her cümle veri/rakam/karşılaştırma içermeli. Eğlence minimum, bilgi maksimum."
    else:
        bilgi_orani = "Her 2 cümleden 1'i TEKNİK BİLGİ, 1'i SAMİMİ YORUM. Bilgi ve eğlence dengeli dağılım. Ne çok sıkıcı ne de çok boş."

    sablon = prompt_dosyasini_oku("sistem_talimati.txt")
    return sablon.format(
        sure_saniye=sure_saniye,
        kelime_sayisi=hedef_kelime,
        min_kelime=min_kelime,
        max_kelime=max_kelime,
        kelime_hizi_orani=KELIME_HIZI_ORANI,
        kelime_yuvarlama=KELIME_YUVARLAMA,
        bilgi_orani=bilgi_orani,
        guncellik_talimati=guncellik_talimati_uret()
    )
