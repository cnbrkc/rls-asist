"""Ses ve video işleme fonksiyonları (ffmpeg, hızlandırma, birleştirme)."""
import os
import re
import wave
import math
import shutil
import subprocess
import tempfile
import uuid

import streamlit as st

from config import (
    SES_OMRU_SANIYE, VIDEO_CRF, VIDEO_PRESET,
    SES_ORNEK_HIZI, SES_KANAL, SES_GENISLIK,
)

# ===== AYARLAR =====
MAKS_VIDEO_HIZLANDIRMA = 1.5   # Video en fazla 1.5x hızlandırılabilir
MIN_VIDEO_YAVASLATMA = 0.5     # Video en fazla 0.5x yavaşlatılabilir
FFMPEG_TIMEOUT = 600

# ===== FFMPEG YOLU (Streamlit Cloud uyumlu) =====
def _ffmpeg_yolu_bul() -> str:
    """Streamlit Cloud'da ffmpeg yolunu bul (önce imageio-ffmpeg, sonra sistem PATH)"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass

    sistem_ffmpeg = shutil.which("ffmpeg")
    if sistem_ffmpeg:
        return sistem_ffmpeg

    return "ffmpeg"

FFMPEG_BIN = _ffmpeg_yolu_bul()

# ===== GEÇİCİ DOSYA YARDIMCILARI =====
def gecici_dosya_yolu(onek: str, uzanti: str) -> str:
    """Geçici dosya yolu oluştur."""
    return os.path.join(tempfile.gettempdir(), f"{onek}_{uuid.uuid4().hex[:8]}.{uzanti}")

def gecici_ses_yolu() -> str:
    """Geçici WAV dosya yolu oluştur."""
    return gecici_dosya_yolu("ses", "wav")

# ===== WAV YAZMA =====
def wav_yaz(dosya_yolu: str, audio_data: bytes, ornek_hizi: int = SES_ORNEK_HIZI,
            kanal: int = SES_KANAL, genislik: int = SES_GENISLIK) -> None:
    """Ham ses verisini WAV dosyasına yaz."""
    with wave.open(dosya_yolu, "wb") as wf:
        wf.setnchannels(kanal)
        wf.setsampwidth(genislik)
        wf.setframerate(ornek_hizi)
        wf.writeframes(audio_data)

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
    import time
    now = time.time()
    temizlenecekler = []

    for dosya_yolu in st.session_state.get("gecici_ses_dosyalari", []):
        if not os.path.exists(dosya_yolu):
            temizlenecekler.append(dosya_yolu)
            continue

        try:
            if now - os.path.getmtime(dosya_yolu) > SES_OMRU_SANIYE:
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
        "-ar", str(SES_ORNEK_HIZI), "-ac", str(SES_KANAL), "-sample_fmt", "s16",
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

# ===== VİDEO BİLGİ ALMA =====
def _video_bilgi_al(video_yolu: str) -> dict:
    """Video metadata: fps, frames, width, height, duration. Hata olursa varsayılan döner."""
    bilgi = {"fps": 0.0, "frames": 0, "width": 1920, "height": 1080, "duration": 0.0}

    # OpenCV ile temel bilgileri almaya çalış
    try:
        import cv2
        cap = cv2.VideoCapture(video_yolu)
        if cap.isOpened():
            bilgi["fps"] = float(cap.get(cv2.CAP_PROP_FPS))
            bilgi["frames"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            bilgi["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            bilgi["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
    except Exception:
        pass

    # FFMPEG ile kesin süre tespiti
    try:
        komut = [FFMPEG_BIN, "-i", video_yolu, "-hide_banner"]
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=30)

        sure_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", sonuc.stderr)
        if sure_match:
            h, m, s = map(float, sure_match.groups())
            bilgi["duration"] = h * 3600 + m * 60 + s

        if bilgi["fps"] <= 0:
            fps_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:fps|tbr)", sonuc.stderr)
            if fps_match:
                bilgi["fps"] = float(fps_match.group(1))

        if bilgi["width"] <= 0 or bilgi["height"] <= 0:
            coz_match = re.search(r"(\d{2,5})x(\d{2,5})", sonuc.stderr)
            if coz_match:
                bilgi["width"] = int(coz_match.group(1))
                bilgi["height"] = int(coz_match.group(2))

    except Exception:
        pass

    if bilgi["duration"] <= 0 and bilgi["fps"] > 0 and bilgi["frames"] > 0:
        bilgi["duration"] = bilgi["frames"] / bilgi["fps"]

    return bilgi

def video_suresini_al(video_yolu: str) -> float:
    bilgi = _video_bilgi_al(video_yolu)
    return bilgi["duration"] if bilgi["duration"] > 0 else 30.0

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

# ===== VİDEO + SES BİRLEŞTİRME (UPSCALE YOK) =====
def video_ve_sesi_birlestir(
    video_yolu: str,
    ses_yolu: str,
    cikti_v_yolu: str,
    log_ekle
) -> bool:
    """
    Videoya AI sesini ekle.
    Upscale yok.
    Sadece ses/video senkronu için video hızlandırma/yavaşlatma yapılır.
    """

    if not os.path.exists(video_yolu):
        log_ekle("⚠️ Video dosyası bulunamadı.")
        return False

    if not os.path.exists(ses_yolu):
        log_ekle("⚠️ Ses dosyası bulunamadı.")
        return False

    # Video bilgilerini al
    bilgi = _video_bilgi_al(video_yolu)
    video_sure = bilgi["duration"] if bilgi["duration"] > 0 else 30.0
    ses_sure = _ses_suresini_al(ses_yolu)

    # Hedef süre: ses süresini üst tam sayıya yuvarla
    if ses_sure > 0:
        hedef_sure = math.ceil(ses_sure - 0.001)
        if hedef_sure < 1:
            hedef_sure = 1
    else:
        hedef_sure = video_sure

    log_ekle(
        f"⏱️ Video: {video_sure:.2f}s | "
        f"Ses: {ses_sure:.2f}s | "
        f"Hedef süre: {hedef_sure:.2f}s"
    )

    # ============================================================
    # VİDEO HIZ AYARI
    # ============================================================
    video_hiz_carpani = 1.0

    if hedef_sure > video_sure:
        # Ses videodan uzun → videoyu yavaşlat
        video_hiz_carpani = video_sure / hedef_sure

        if video_hiz_carpani < MIN_VIDEO_YAVASLATMA:
            video_hiz_carpani = MIN_VIDEO_YAVASLATMA
            hedef_sure = video_sure / video_hiz_carpani
            log_ekle("⚠️ Video çok fazla yavaşlatılacak, sınır uygulandı.")

        log_ekle(
            f"🎬 Video yavaşlatılıyor: {video_hiz_carpani:.3f}x → "
            f"{video_sure:.2f}s → {hedef_sure:.2f}s"
        )

    elif hedef_sure < video_sure:
        # Ses videodan kısa → videoyu hızlandır
        video_hiz_carpani = video_sure / hedef_sure

        if video_hiz_carpani > MAKS_VIDEO_HIZLANDIRMA:
            video_hiz_carpani = MAKS_VIDEO_HIZLANDIRMA
            hedef_sure = video_sure / video_hiz_carpani
            log_ekle("⚠️ Video çok fazla hızlandırılacak, sınır uygulandı.")

        log_ekle(
            f"🎬 Video hızlandırılıyor: {video_hiz_carpani:.3f}x → "
            f"{video_sure:.2f}s → {hedef_sure:.2f}s"
        )

    else:
        log_ekle("🎬 Video hız ayarı gerekmedi.")

    # ============================================================
    # FFMPEG FİLTRESİ
    # ============================================================
    vf_parts = []

    if abs(video_hiz_carpani - 1.0) > 0.001:
        setpts_carpani = round(1.0 / video_hiz_carpani, 4)
        vf_parts.append(f"setpts=PTS*{setpts_carpani}")

    vf_filtre = ",".join(vf_parts)

    if vf_filtre:
        log_ekle(f"🎛️ Video filtresi: {vf_filtre}")
    else:
        log_ekle("🎛️ Video filtresi kullanılmayacak.")

    # ============================================================
    # FFMPEG ÇALIŞTIRMA
    # ============================================================
    def run_ffmpeg(vf_str: str, use_libx264: bool):
        komut = [
            FFMPEG_BIN, "-y",
            "-i", video_yolu,
            "-i", ses_yolu,
        ]

        if vf_str:
            komut += ["-vf", vf_str]

        if use_libx264:
            komut += [
                "-c:v", "libx264",
                "-preset", VIDEO_PRESET,
                "-crf", str(VIDEO_CRF),
                "-pix_fmt", "yuv420p",
            ]
        else:
            komut += ["-c:v", "copy"]

        komut += [
            "-af", "apad",
            "-t", f"{hedef_sure:.3f}",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            cikti_v_yolu
        ]

        return subprocess.run(komut, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)

    # ============================================================
    # RENDER
    # ============================================================
    try:
        sonuc = run_ffmpeg(vf_filtre, bool(vf_filtre))

        if sonuc.returncode == 0:
            log_ekle("✅ Video ve ses başarıyla birleştirildi!")
            return True

        log_ekle(f"⚠️ ffmpeg hata: {sonuc.stderr[-300:] if sonuc.stderr else 'bilinmeyen'}")

        # Fallback: hız ayarı olmadan dene
        if vf_filtre:
            log_ekle("🔄 Fallback: video hız ayarı olmadan deneniyor...")
            fallback_sonuc = run_ffmpeg("", False)

            if fallback_sonuc.returncode == 0:
                log_ekle("⚠️ Video hız ayarı yapılamadı, orijinal video ile birleştirildi.")
                return True

            log_ekle(f"⚠️ Fallback ffmpeg hata: {fallback_sonuc.stderr[-300:] if fallback_sonuc.stderr else 'bilinmeyen'}")

        return False

    except FileNotFoundError:
        log_ekle("⚠️ ffmpeg bulunamadı!")
        return False
    except subprocess.TimeoutExpired:
        log_ekle("⚠️ ffmpeg zaman aşımına uğradı.")
        return False
    except Exception as e:
        log_ekle(f"⚠️ Video-ses birleştirme hatası: {e}")
        return False
