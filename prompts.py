"""Prompt .txt dosyalarını okuma ve dinamik talimat üretme."""
import os
from config import guncel_tarih_metni


def prompt_dosyasi_oku(dosya_adi: str) -> str:
    yol = os.path.join(os.path.dirname(__file__), dosya_adi)
    if not os.path.exists(yol):
        return ""
    with open(yol, "r", encoding="utf-8") as f:
        return f.read()


def guncellik_talimatini_hazirla() -> str:
    sablon = prompt_dosyasi_oku("guncellik_talimati.txt")
    if not sablon:
        return ""
    return sablon.replace("{bugunun_tarihi}", guncel_tarih_metni())


def sistem_talimatini_hazirla(sure_saniye: int, kelime_sayisi: int, bilgi_orani: str) -> str:
    sablon = prompt_dosyasi_oku("sistem_talimati.txt")
    if not sablon:
        return ""
    min_kelime = max(5, int(kelime_sayisi * 0.9))
    max_kelime = int(kelime_sayisi * 1.1)
    return (
        sablon
        .replace("{guncellik_talimati}", guncellik_talimatini_hazirla())
        .replace("{sure_saniye}", str(sure_saniye))
        .replace("{kelime_sayisi}", str(kelime_sayisi))
        .replace("{min_kelime}", str(min_kelime))
        .replace("{max_kelime}", str(max_kelime))
        .replace("{bilgi_orani}", bilgi_orani)
    )


def video_analiz_promptunu_hazirla(ek_notlar: str, sure_saniye: int) -> str:
    sablon = prompt_dosyasi_oku("video_analiz_promptu.txt")
    if not sablon:
        return ""
    if ek_notlar.strip():
        ek_bolum = f"\n\n## KULLANICININ EK NOTLARI (ÖNCELİKLİ)\n{ek_notlar.strip()}\n"
    else:
        ek_bolum = ""
    return (
        sablon
        .replace("{ek_notlar_bolumu}", ek_bolum)
        .replace("{guncellik_talimati}", guncellik_talimatini_hazirla())
        .replace("{sure_saniye}", str(sure_saniye))
    )
