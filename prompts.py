"""Prompt oluşturma fonksiyonları."""
import os
import random
from datetime import datetime

from config import (
    KELIME_HIZI_ORANI,
    KELIME_YUVARLAMA,
    TON_EGLENCE,
    TON_DENGELI,
    TON_BILGI,
    TON_TEKNIK,
    TURKCE_AYLAR,
)

def prompt_dosyasini_oku(dosya_adi: str) -> str:
    """prompts/ klasöründeki prompt dosyasını oku."""
    yol = os.path.join("prompts", dosya_adi)
    try:
        with open(yol, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

def kurallari_oku() -> str:
    """kurallar.txt dosyasını oku."""
    return prompt_dosyasini_oku("kurallar.txt")

def guncellik_talimati_uret() -> str:
    """Güncel bilgi talimatı üret."""
    simdi = datetime.now()
    return f"Bugünün tarihi: {simdi.day} {TURKCE_AYLAR.get(simdi.month, '')} {simdi.year}. Güncel bilgi gerekiyorsa arama yap."

def video_analiz_promptunu_olustur(ek_notlar_bolumu: str, sure_saniye: int) -> str:
    sablon = prompt_dosyasini_oku("video_analiz_promptu.txt")
    return sablon.format(
        ek_notlar_bolumu=ek_notlar_bolumu,
        guncellik_talimati=guncellik_talimati_uret(),
        sure_saniye=sure_saniye
    )

def sistem_talimati_olustur(
    sure_saniye: int,
    icerik_tonu: str,
    kelime_hizi_orani: float = None
) -> str:
    """
    Sistem talimatı oluştur.

    kelime_hizi_orani:
      - None ise varsayılan KELIME_HIZI_ORANI kullanılır.
      - Fallback durumunda artırılabilir.
    """
    if kelime_hizi_orani is None:
        kelime_hizi_orani = KELIME_HIZI_ORANI

    hedef_kelime = round(sure_saniye * kelime_hizi_orani / KELIME_YUVARLAMA) * KELIME_YUVARLAMA
    min_kelime = max(5, int(hedef_kelime * 0.85))
    max_kelime = int(hedef_kelime * 1.15)

    if icerik_tonu == TON_EGLENCE:
        bilgi_orani = (
            "Her 4 cümleden 1'i TEKNİK BİLGİ, 3'ü SAMİMİ YORUM/EĞLENCE. "
            "Hikaye, espri, kişisel deneyim, 'düşünsene' anları ağırlıklı. "
            "Teknik bilgi sadece vurgu için kullanılmalı."
        )
    elif icerik_tonu == TON_BILGI:
        bilgi_orani = (
            "Her 4 cümleden 3'ü TEKNİK BİLGİ, 1'i SAMİMİ YORUM. "
            "Rakam, karşılaştırma, teknik detay, performans verisi ağırlıklı. "
            "Eğlence sadece nefes aldırmak için."
        )
    elif icerik_tonu == TON_TEKNIK:
        bilgi_orani = (
            "Her 10 cümleden 9'u TEKNİK BİLGİ, 1'i SAMİMİ YORUM. "
            "Neredeyse her cümle veri/rakam/karşılaştırma içermeli. "
            "Eğlence minimum, bilgi maksimum."
        )
    else:
        bilgi_orani = (
            "Her 2 cümleden 1'i TEKNİK BİLGİ, 1'i SAMİMİ YORUM. "
            "Bilgi ve eğlence dengeli dağılım. Ne çok sıkıcı ne de çok boş."
        )

    sablon = prompt_dosyasini_oku("sistem_talimati.txt")
    return sablon.format(
        sure_saniye=sure_saniye,
        kelime_sayisi=hedef_kelime,
        min_kelime=min_kelime,
        max_kelime=max_kelime,
        kelime_hizi_orani=kelime_hizi_orani,
        kelime_yuvarlama=KELIME_YUVARLAMA,
        bilgi_orani=bilgi_orani,
        guncellik_talimati=guncellik_talimati_uret()
    )
