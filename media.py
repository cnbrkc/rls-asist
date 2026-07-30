"""Ses ve video işleme fonksiyonları (ffmpeg, hızlandırma, birleştirme)."""
import os
import wave
import shutil
import subprocess
import tempfile
import uuid

import streamlit as st

from config import (
    SES_OMRU_SANIYE, HEDEF_2K_Y, VIDEO_CRF, VIDEO_PRESET,
    SES_ORNEK_HIZI, SES_KANAL, SES_GENISLIK,
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

# ===== GEÇİCİ DOSYA YARDIMCILARI =====
def gecici_dosya_yolu(onek: str, uzanti: str) -> str:
    """Geçici dosya yolu oluştur (oto-temizlik için session_state'e eklenebilir)."""
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
    bilgi = {"fps": 0, "frames": 0, "width": 1920, "height": 1080, "duration": 0.0}
    try:
        import cv2
        cap = cv2.VideoCapture(video_yolu)
        if cap.isOpened():
            bilgi["fps"] = cap.get(cv2.CAP_PROP_FPS)
            bilgi["frames"] = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            bilgi["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            bilgi["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if bilgi["fps"] > 0 and bilgi["frames"] > 0:
                bilgi["duration"] = bilgi["frames"] / bilgi["fps"]
    except Exception:
        pass
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

# ===== VİDEO + SES BİRLEŞTİRME (2K UPSCALE + KESKİNLEŞTİRME + YAVAŞLATMA) =====
def video_ve_sesi_birlestir(video_yolu: str, ses_yolu: str, cikti_v_yolu: str, log_ekle) -> bool:
    """Videoya AI sesini ekle + 2K upscale + sese uyum için video yavaşlatma (KESME YOK)"""

    # Video bilgilerini al
    bilgi = _video_bilgi_al(video_yolu)
    genislik, yukseklik = bilgi["width"], bilgi["height"]

    # Süreleri al
    video_sure = bilgi["duration"] if bilgi["duration"] > 0 else 30.0
    ses_sure = _ses_suresini_al(ses_yolu)
    log_ekle(f"⏱️ Video: {video_sure:.1f}s | Ses: {ses_sure:.1f}s")

    # Hedef: 2K upscale (1440p) — zaten 2K+ ise sadece keskinleştir
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
        "-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
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
                fallback_komut += ["-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF)]
            else:
                fallback_komut += ["-c:v", "copy"]
            fallback_komut += [
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                cikti_v_yolu
            ]
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
