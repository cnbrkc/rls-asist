import os
import re
import json
import time
import wave
import uuid
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import List, Tuple
import streamlit as st

from config import (
    KAYIT_DOSYASI, MAX_KAYIT, SES_OMRU_SANIYE,
    TURKCE_AYLAR, SES_HIZ_CARpanI,  # hız çarpanı burada da kullanılabilir
)

# ===== TARİH =====
def guncel_tarih_metni() -> str:
    simdi = datetime.now()
    return f"{simdi.day} {TURKCE_AYLAR[simdi.month]} {simdi.year}"

# ===== PROMPT DOSYASI OKUMA =====
def prompt_dosyasini_oku(dosya_adi: str) -> str:
    try:
        with open(dosya_adi, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        st.error(f"⚠️ Prompt dosyası bulunamadı: '{dosya_adi}'!")
        st.stop()

# ===== METİN TEMİZLEME =====
def markdown_temizle(metin: str) -> str:
    if not isinstance(metin, str):
        return ""
    return re.sub(r"[\*\_\`\[\]]+", "", metin).strip()

def kapak_basliklarini_formatla(liste: List) -> str:
    if not isinstance(liste, list) or not liste:
        return markdown_temizle(str(liste)) if liste else "(Kapak başlığı üretilemedi.)"
    satirlar = []
    for i, secenek in enumerate(liste, start=1):
        if isinstance(secenek, dict):
            ana = markdown_temizle(str(secenek.get("ana", "")))
            alt = markdown_temizle(str(secenek.get("alt", "")))
        else:
            ana, alt = markdown_temizle(str(secenek)), ""
        satirlar.append(f"{i}) {ana}\n  {alt}" if alt else f"{i}) {ana}")
    return "\n\n".join(satirlar)

# ===== JSON GÜVENLİ YÜKLEME =====
def guvenli_json_yukle(response_text: str) -> dict:
    if not response_text:
        raise ValueError("Model boş yanıt döndürdü.")
    temiz = response_text.strip()
    try:
        return json.loads(temiz)
    except json.JSONDecodeError:
        temiz_md = re.sub(r"^\`\`\`json\s*|^\`\`\`\s*|\`\`\`\s*$", "", temiz, flags=re.IGNORECASE | re.MULTILINE).strip()
        try:
            return json.loads(temiz_md)
        except json.JSONDecodeError:
            pass
        start = temiz.find('{')
        end = temiz.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(temiz[start:end+1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"JSON parse edilemedi. Ham yanıt: {temiz[:200]}...")

# ===== SES DOSYASI YÖNETİMİ =====
def temp_dosya_temizle(dosya_yolu: str) -> bool:
    try:
        if dosya_yolu and os.path.exists(dosya_yolu):
            os.remove(dosya_yolu)
            return True
    except Exception:
        pass
    return False

def eski_ses_dosyalarini_temizle() -> None:
    simdi = time.time()
    temizlenecekler = []
    for dosya_yolu in st.session_state.get("gecici_ses_dosyalari", []):
        if not os.path.exists(dosya_yolu):
            temizlenecekler.append(dosya_yolu)
            continue
        try:
            if simdi - os.path.getmtime(dosya_yolu) > SES_OMRU_SANIYE:
                if temp_dosya_temizle(dosya_yolu):
                    temizlenecekler.append(dosya_yolu)
        except Exception:
            temizlenecekler.append(dosya_yolu)
    for dosya in temizlenecekler:
        if dosya in st.session_state.gecici_ses_dosyalari:
            st.session_state.gecici_ses_dosyalari.remove(dosya)

# ===== SES HIZLANDIRMA =====
def sesi_hizlandir(giris_dosyasi: str, cikti_dosyasi: str, hiz_carpani: float, log_ekle) -> bool:
    if abs(hiz_carpani - 1.0) < 0.001:
        try:
            shutil.copy2(giris_dosyasi, cikti_dosyasi)
            return True
        except Exception as e:
            log_ekle(f"⚠️ Ses kopyalanamadı: {e}")
            return False
    komut = [
        "ffmpeg", "-y", "-i", giris_dosyasi,
        "-filter:a", f"atempo={hiz_carpani}",
        "-ar", "24000", "-ac", "1", "-sample_fmt", "s16",
        cikti_dosyasi
    ]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=120)
        if sonuc.returncode != 0:
            log_ekle(f"⚠️ ffmpeg hata: {sonuc.stderr[-300:] if sonuc.stderr else 'bilinmeyen'}")
            return False
        return True
    except FileNotFoundError:
        log_ekle("⚠️ ffmpeg bulunamadı! Sunucuda kurulu olması gerekir.")
        return False
    except subprocess.TimeoutExpired:
        log_ekle("⚠️ ffmpeg zaman aşımına uğradı.")
        return False
    except Exception as e:
        log_ekle(f"⚠️ ffmpeg beklenmeyen hata: {e}")
        return False

# ===== KAYIT YÖNETİMİ =====
def kayitlari_yukle() -> List[dict]:
    try:
        if os.path.exists(KAYIT_DOSYASI):
            with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []

def kayitlari_kaydet(kayitlar: List[dict]) -> None:
    try:
        with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(kayitlar, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def kayit_ekle(uretim_verisi: dict) -> None:
    kayitlar = kayitlari_yukle()
    kayit = {
        "tarih": datetime.now().strftime("%d %B %Y %H:%M"),
        "seslendirme_metni": uretim_verisi.get("seslendirme_metni", ""),
        "reels_aciklamasi": uretim_verisi.get("reels_aciklamasi", ""),
        "reels_hashtagleri": uretim_verisi.get("reels_hashtagleri", []),
        "kapak_basliklari": uretim_verisi.get("kapak_basliklari", []),
        "threads_aciklamasi": uretim_verisi.get("threads_aciklamasi", ""),
        "ses_adi": uretim_verisi.get("ses_adi", ""),
        "sure_saniye": uretim_verisi.get("sure_saniye", 30),
    }
    kayitlar.append(kayit)
    if len(kayitlar) > MAX_KAYIT:
        kayitlar = kayitlar[-MAX_KAYIT:]
    kayitlari_kaydet(kayitlar)

def tum_kayitlari_sil() -> None:
    try:
        if os.path.exists(KAYIT_DOSYASI):
            os.remove(KAYIT_DOSYASI)
    except Exception:
        pass

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
    hedef_kelime = round(sure_saniye * 2.7 / 5) * 5
    min_kelime = max(5, int(hedef_kelime * 0.9))
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
        bilgi_orani=bilgi_orani,
        guncellik_talimati=guncellik_talimati_uret()
    )
