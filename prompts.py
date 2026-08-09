"""Prompt oluşturma fonksiyonları — Ultimate Content Engine (9 aşamalı pipeline)."""
import os
import json
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
    """kurallar.txt dosyasını oku (referans/legacy; her aşama artık kendi ilgili
    kural alt kümesini kendi prompt dosyasında taşıyor)."""
    return prompt_dosyasini_oku("kurallar.txt")


def guncellik_talimati_uret() -> str:
    """Güncel bilgi talimatı üret (Research aşamasında kullanılır)."""
    simdi = datetime.now()
    bugun = f"{simdi.day} {TURKCE_AYLAR.get(simdi.month, '')} {simdi.year}"
    sablon = prompt_dosyasini_oku("guncellik_talimati.txt")
    if sablon:
        try:
            return sablon.format(bugunun_tarihi=bugun)
        except (KeyError, IndexError):
            return sablon
    return f"Bugünün tarihi: {bugun}. Güncel bilgi gerekiyorsa arama yap."


def _bilgi_orani_metni(icerik_tonu: str) -> str:
    if icerik_tonu == TON_EGLENCE:
        return (
            "Her 4 cümleden 1'i TEKNİK BİLGİ, 3'ü SAMİMİ YORUM/EĞLENCE. "
            "Hikaye, espri, kişisel deneyim, 'düşünsene' anları ağırlıklı. "
            "Teknik bilgi sadece vurgu için kullanılmalı."
        )
    if icerik_tonu == TON_BILGI:
        return (
            "Her 4 cümleden 3'ü TEKNİK BİLGİ, 1'i SAMİMİ YORUM. "
            "Rakam, karşılaştırma, teknik detay, performans verisi ağırlıklı. "
            "Eğlence sadece nefes aldırmak için."
        )
    if icerik_tonu == TON_TEKNIK:
        return (
            "Her 10 cümleden 9'u TEKNİK BİLGİ, 1'i SAMİMİ YORUM. "
            "Neredeyse her cümle veri/rakam/karşılaştırma içermeli. "
            "Eğlence minimum, bilgi maksimum."
        )
    return (
        "Her 2 cümleden 1'i TEKNİK BİLGİ, 1'i SAMİMİ YORUM. "
        "Bilgi ve eğlence dengeli dağılım. Ne çok sıkıcı ne de çok boş."
    )


def _kelime_hedefleri(sure_saniye: int, kelime_hizi_orani: float = None):
    if kelime_hizi_orani is None:
        kelime_hizi_orani = KELIME_HIZI_ORANI
    hedef_kelime = round(sure_saniye * kelime_hizi_orani / KELIME_YUVARLAMA) * KELIME_YUVARLAMA
    tolerans = max(5, int(hedef_kelime * 0.10))
    min_kelime = max(5, hedef_kelime - tolerans)
    max_kelime = hedef_kelime + tolerans
    return hedef_kelime, min_kelime, max_kelime, kelime_hizi_orani


# ============================================================
# ROLE 1 — FORENSIC VIDEO ANALYSIS
# ============================================================
def forensic_analiz_promptunu_olustur(ek_notlar_bolumu: str, sure_saniye: int) -> str:
    sablon = prompt_dosyasini_oku("forensic_analysis_prompt.txt")
    return sablon.format(
        ek_notlar_bolumu=ek_notlar_bolumu,
        sure_saniye=sure_saniye,
    )


# ============================================================
# ROLE 2 — RESEARCH / FACT LOCK
# ============================================================
def research_promptunu_olustur() -> str:
    sablon = prompt_dosyasini_oku("research_prompt.txt")
    return sablon.format(guncellik_talimati=guncellik_talimati_uret())


# ============================================================
# ROLE 3 — EDITORIAL BRAIN
# ============================================================
def editorial_promptunu_olustur() -> str:
    return prompt_dosyasini_oku("editorial_prompt.txt")


# ============================================================
# ROLE 4 — REELS CREATIVE ENGINE
# ============================================================
def reels_creative_promptunu_olustur(
    sure_saniye: int,
    icerik_tonu: str,
    kelime_hizi_orani: float = None,
) -> str:
    """
    kelime_hizi_orani:
      - None ise varsayılan KELIME_HIZI_ORANI kullanılır.
      - Fallback (ses çok kısa kaldıysa) durumunda artırılabilir.
    """
    hedef_kelime, min_kelime, max_kelime, kelime_hizi_orani = _kelime_hedefleri(
        sure_saniye, kelime_hizi_orani
    )
    sablon = prompt_dosyasini_oku("reels_creative_prompt.txt")
    return sablon.format(
        sure_saniye=sure_saniye,
        kelime_sayisi=hedef_kelime,
        min_kelime=min_kelime,
        max_kelime=max_kelime,
        kelime_hizi_orani=kelime_hizi_orani,
        kelime_yuvarlama=KELIME_YUVARLAMA,
        bilgi_orani=_bilgi_orani_metni(icerik_tonu),
    )


# ============================================================
# ROLE 5 — CAPTION + HASHTAG ENGINE
# ============================================================
def caption_promptunu_olustur() -> str:
    return prompt_dosyasini_oku("caption_prompt.txt")


# ============================================================
# ROLE 6 — THREADS ENGINE
# ============================================================
def threads_promptunu_olustur() -> str:
    return prompt_dosyasini_oku("threads_promptu.txt")


# ============================================================
# ROLE 7 — FINAL QA ENGINE
# ============================================================
def qa_promptunu_olustur() -> str:
    return prompt_dosyasini_oku("qa_prompt.txt")


# ============================================================
# YARDIMCI: PIPELINE STATE'İ MODEL İÇİN OKUNABİLİR METNE ÇEVİR
# ============================================================
def durumu_metne_donustur(baslik: str, veri) -> str:
    """
    Bir pipeline state parçasını (dict/list) etiketli, okunabilir bir metne
    çevirir. Token optimizasyonu için her aşamaya SADECE ihtiyacı olan
    state parçaları bu fonksiyonla ayrı ayrı etiketlenip birleştirilir.
    """
    try:
        govde = json.dumps(veri, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        govde = str(veri)
    return f"--- {baslik} ---\n{govde}\n"


def girdi_birlestir(*parcalar: str) -> str:
    """Birden fazla 'durumu_metne_donustur' çıktısını (veya düz metni) tek bir
    model girdisi haline getirir."""
    return "\n".join(p for p in parcalar if p and p.strip())
