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
    TURKCE_AYLAR, SES_HIZ_CARpanI,
)

# ===== FFMPEG YOLU (Streamlit Cloud uyumlu) =====
def _ffmpeg_yolu_bul() -> str:
    """Streamlit Cloud'da ffmpeg yolunu bul (önce imageio-ffmpeg, sonra sistem PATH)"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, Exception):
        pass
    sistem_ffmpeg = shutil.which("ffmpeg")
    if sistem_ffmpeg:
        return sistem_ffmpeg
    return "ffmpeg"

FFMPEG_BIN = _ffmpeg_yolu_bul()

# ===== TARİH =====
def guncel_tarih_metni() -> str:
    simdi = datetime.now()
    return f"{simdi.day} {TURKCE_AYLAR[simdi.month]} {simdi.year}"

# ===== PROMPT DOSYASI OKUMA =====
def prompt_dosyasini_oku(dosya_adi: str) -> str:
    try:
        tam_yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), dosya_adi)
        with open(tam_yol, "r", encoding="utf-8") as f:
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
    # ffmpeg atempo filtresi sadece 0.5–2.0 arası değerleri kabul eder
    if hiz_carpani < 0.5 or hiz_carpani > 2.0:
        carpanlar = []
        kalan = hiz_carpani
        while kalan > 2.0:
            carpanlar.append(2.0)
            kalan /= 2.0
        while kalan < 0.5:
            carpanlar.append(0.5)
            kalan /= 0.5
        carpanlar.append(round(kalan, 4))
        atempo_str = ",".join(f"atempo={c}" for c in carpanlar)
    else:
        atempo_str = f"atempo={hiz_carpani}"

    komut = [
        FFMPEG_BIN, "-y", "-i", giris_dosyasi,
        "-filter:a", atempo_str,
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

# ===== VİDEO SÜRE TESPİTİ =====
def video_suresini_al(video_yolu: str) -> float:
    try:
        import cv2
        cap = cv2.VideoCapture(video_yolu)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if fps > 0 and frame_count > 0:
                sure = frame_count / fps
                if sure > 0:
                    return sure
    except Exception:
        pass
    return 30.0

# ===== SES SÜRE TESPİTİ =====
def _ses_suresini_al(ses_yolu: str) -> float:
    """WAV dosyasının süresini saniye cinsinden döndür"""
    try:
        with wave.open(ses_yolu, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return frames / rate
    except Exception:
        pass
    return 0.0

# ===== VİDEO + SES BİRLEŞTİRME (2K UPSCALE + KESKİNLEŞTİRME + YAVAŞLATMA) =====
def video_ve_sesi_birlestir(video_yolu: str, ses_yolu: str, cikti_v_yolu: str, log_ekle) -> bool:
    """Videoya AI sesini ekle + 2K upscale + sese uyum için video yavaşlatma (KESME YOK)"""

    # Video çözünürlüğünü tespit et
    genislik, yukseklik = 1920, 1080
    try:
        import cv2
        cap = cv2.VideoCapture(video_yolu)
        if cap.isOpened():
            genislik = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            yukseklik = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
    except Exception:
        pass

    # Süreleri al
    video_sure = video_suresini_al(video_yolu)
    ses_sure = _ses_suresini_al(ses_yolu)
    log_ekle(f"⏱️ Video: {video_sure:.1f}s | Ses: {ses_sure:.1f}s")

    # Hedef: 2K upscale (1440p) — zaten 2K+ ise sadece keskinleştir
    # 2K = 1440p → 4K'dan 2.25x hızlı, 2.30 dk videolar için güvenli
    HEDEF_2K_Y = 1440
    if yukseklik >= HEDEF_2K_Y:
        hedef_y = yukseklik  # Zaten 2K+, sadece keskinleştir
    else:
        hedef_y = HEDEF_2K_Y

    hedef_x = int(genislik * hedef_y / yukseklik)
    hedef_x += hedef_x % 2   # ffmpeg çift sayı ister
    hedef_y += hedef_y % 2

    # Video filtresi parçalarını oluştur
    vf_parcalari = []

    # Upscale
    if hedef_y != yukseklik:
        vf_parcalari.append(f"scale={hedef_x}:{hedef_y}:flags=lanczos")
        log_ekle(f"🎬 2K Upscale: {genislik}x{yukseklik} → {hedef_x}x{hedef_y}")

    # Keskinleştirme (4K upscale sonrası detayları netleştir)
    vf_parcalari.append("unsharp=5:5:1.0:3:3:0.0")

    # Video yavaşlatma: ses video'dan uzunsa videoyu yavaşlat (max 0.9x)
    video_yavaslatma = 1.0  # 1.0 = yavaşlatma yok
    if ses_sure > 0 and video_sure > 0 and ses_sure > video_sure:
        # Örn: video 16s, ses 19.3s → 16/19.3 = 0.829 → 0.9 ile sınırla
        video_yavaslatma = max(0.9, video_sure / ses_sure)
        setpts_carpani = round(1.0 / video_yavaslatma, 4)
        vf_parcalari.append(f"setpts=PTS*{setpts_carpani}")
        yavas_video_sure = video_sure / video_yavaslatma
        log_ekle(f"🎬 Video yavaşlatılıyor: {video_yavaslatma:.2f}x → {video_sure:.1f}s → {yavas_video_sure:.1f}s (sese uyum)")
    else:
        log_ekle("🎬 Video yavaşlatma gereksiz (ses video'dan kısa veya eşit)")

    vf_filtre = ",".join(vf_parcalari)

    komut = [
        FFMPEG_BIN, "-y",
        "-i", video_yolu,
        "-i", ses_yolu,
        "-vf", vf_filtre,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        cikti_v_yolu
    ]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=300)
        if sonuc.returncode != 0:
            log_ekle(f"⚠️ ffmpeg hata: {sonuc.stderr[-300:] if sonuc.stderr else 'bilinmeyen'}")
            # Fallback: upscale olmadan tekrar dene (yavaşlatma korunur)
            log_ekle("🔄 Fallback: upscale olmadan tekrar deneniyor...")
            fallback_vf = f"setpts=PTS*{round(1.0/video_yavaslatma,4)}" if video_yavaslatma < 1.0 else None
            fallback_komut = [
                FFMPEG_BIN, "-y",
                "-i", video_yolu,
                "-i", ses_yolu,
            ]
            if fallback_vf:
                fallback_komut += ["-vf", fallback_vf]
            fallback_komut += [
                "-c:v", "libx264" if fallback_vf else "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                cikti_v_yolu
            ]
            if fallback_vf:
                fallback_komut.insert(fallback_komut.index("-c:v") + 1, "fast")
                fallback_komut.insert(fallback_komut.index("-c:v") + 2, "-crf")
                fallback_komut.insert(fallback_komut.index("-c:v") + 3, "23")
            fallback_sonuc = subprocess.run(fallback_komut, capture_output=True, text=True, timeout=300)
            if fallback_sonuc.returncode != 0:
                log_ekle(f"⚠️ Fallback ffmpeg hata: {fallback_sonuc.stderr[-300:] if fallback_sonuc.stderr else 'bilinmeyen'}")
                return False
            log_ekle("✅ Video + ses birleştirildi (fallback: orijinal çözünürlük)")
            return True
        log_ekle("✅ Video ve ses başarıyla birleştirildi (2K upscale + keskinleştirme)!")
        return True
    except FileNotFoundError:
        log_ekle("⚠️ ffmpeg bulunamadı!")
        return False
    except subprocess.TimeoutExpired:
        log_ekle("⚠️ ffmpeg zaman aşımına uğradı.")
        return False
    except Exception as e:
        log_ekle(f"⚠️ Video-ses birleştirme hatası: {e}")
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
    # Kelime hedefi: TTS modeli Türkçe'de ~1.7 kelime/saniye üretiyor
    # 2.0 k/s hedefle → AI biraz fazlaysa bile video süresine yakın kalır
    hedef_kelime = round(sure_saniye * 2.4 / 5) * 5
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
        bilgi_orani=bilgi_orani,
        guncellik_talimati=guncellik_talimati_uret()
    )
