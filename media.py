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
    SES_OMRU_SANIYE, HEDEF_2K_Y, VIDEO_CRF, VIDEO_PRESET,
    SES_ORNEK_HIZI, SES_KANAL, SES_GENISLIK,
)

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
    bilgi = {"fps": 0.0, "frames": 0, "width": 1920, "height": 1080, "duration": 0.0}

    # 1. Önce OpenCV ile temel bilgileri (genişlik, yükseklik) almaya çalış
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

    # 2. Kesin süre tespiti için FFMPEG kullan
    try:
        komut = [FFMPEG_BIN, "-i", video_yolu, "-hide_banner"]
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=30)

        # Süreyi bul (Format: HH:MM:SS.ms)
        sure_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", sonuc.stderr)
        if sure_match:
            h, m, s = map(float, sure_match.groups())
            bilgi["duration"] = h * 3600 + m * 60 + s

        # Eğer OpenCV fps'i bulamadıysa, ffmpeg çıktısından fps'i bulmaya çalış
        if bilgi["fps"] <= 0:
            fps_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:fps|tbr)", sonuc.stderr)
            if fps_match:
                bilgi["fps"] = float(fps_match.group(1))

        # Eğer OpenCV genişlik/yükseklik bulamadıysa, ffmpeg'den al
        if bilgi["width"] <= 0 or bilgi["height"] <= 0:
            coz_match = re.search(r"(\d{2,5})x(\d{2,5})", sonuc.stderr)
            if coz_match:
                bilgi["width"] = int(coz_match.group(1))
                bilgi["height"] = int(coz_match.group(2))

    except Exception:
        pass

    # Eğer OpenCV frame sayısını doğru bulduysa ama süre hala 0 ise hesapla (Fallback)
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

# ===== VİDEO + SES BİRLEŞTİRME (UPSCALE + KESKİNLEŞTİRME + YAVAŞLATMA) =====
def video_ve_sesi_birlestir(
    video_yolu: str,
    ses_yolu: str,
    cikti_v_yolu: str,
    log_ekle,
    hedef_y: int = HEDEF_2K_Y
) -> bool:
    """Videoya AI sesini ekle + seçilen upscale + sese uyum için video yavaşlatma (KESME YOK)"""

    if not os.path.exists(video_yolu):
        log_ekle("⚠️ Video dosyası bulunamadı.")
        return False

    if not os.path.exists(ses_yolu):
        log_ekle("⚠️ Ses dosyası bulunamadı.")
        return False

    # Video bilgilerini al
    bilgi = _video_bilgi_al(video_yolu)
    genislik, yukseklik = bilgi["width"], bilgi["height"]

    if yukseklik <= 0 or genislik <= 0:
        genislik, yukseklik = 1920, 1080

    # Süreleri al
    video_sure = bilgi["duration"] if bilgi["duration"] > 0 else 30.0
    ses_sure = _ses_suresini_al(ses_yolu)

    # ✅ Ses süresini güvenlik için ÜST tam sayıya yuvarla
    # Örnek: 15.7 -> 16
    hedef_ses_suresi = 0
    if ses_sure > 0:
        hedef_ses_suresi = math.ceil(ses_sure - 0.001)
        if hedef_ses_suresi < 1:
            hedef_ses_suresi = 1

    # Final hedef süre: video süresi ve üst yuvarlanmış ses süresinden büyük olanı seç
    hedef_sure = max(video_sure, float(hedef_ses_suresi), ses_sure)

    log_ekle(
        f"⏱️ Video: {video_sure:.2f}s | "
        f"Ses: {ses_sure:.2f}s | "
        f"Ses üst hedef: {float(hedef_ses_suresi):.2f}s | "
        f"Final hedef: {hedef_sure:.2f}s"
    )

    # Upscale hedefi
    hedef_cozunurluk = int(hedef_y) if hedef_y else HEDEF_2K_Y
    if hedef_cozunurluk <= 0:
        hedef_cozunurluk = HEDEF_2K_Y

    # Zaten hedef çözünürlük veya üstündeyse upscale yapma
    if yukseklik >= hedef_cozunurluk:
        hedef_cozunurluk = yukseklik

    hedef_x = int(genislik * hedef_cozunurluk / yukseklik)
    hedef_x += hedef_x % 2   # ffmpeg çift sayı ister
    hedef_cozunurluk += hedef_cozunurluk % 2

    # Video filtresi parçalarını oluştur
    vf_parcalari = []

    # Upscale
    if hedef_cozunurluk != yukseklik:
        vf_parcalari.append(f"scale={hedef_x}:{hedef_cozunurluk}:flags=lanczos")

        if hedef_cozunurluk >= 2160:
            log_ekle(f"🎬 4K Upscale: {genislik}x{yukseklik} → {hedef_x}x{hedef_cozunurluk}")
        elif hedef_cozunurluk >= 1440:
            log_ekle(f"🎬 2K Upscale: {genislik}x{yukseklik} → {hedef_x}x{hedef_cozunurluk}")
        else:
            log_ekle(f"🎬 Upscale: {genislik}x{yukseklik} → {hedef_x}x{hedef_cozunurluk}")

    # Keskinleştirme
    vf_parcalari.append("unsharp=5:5:1.0:3:3:0.0")

    # Video yavaşlatma: final hedef süre video'dan uzunsa videoyu hedefe uydur
    video_yavaslatma = 1.0
    if hedef_sure > video_sure + 0.0001:
        if hedef_sure > video_sure * 3:
            log_ekle("⚠️ Dikkat: Hedef süre videonun 3 katından fazla. Video çok yavaşlayacak.")

        video_yavaslatma = video_sure / hedef_sure
        setpts_carpani = round(1.0 / video_yavaslatma, 4)
        vf_parcalari.append(f"setpts=PTS*{setpts_carpani}")

        yavas_video_sure = video_sure / video_yavaslatma
        log_ekle(
            f"🎬 Video hedefe uyduruluyor: {video_yavaslatma:.3f}x → "
            f"{video_sure:.2f}s → {yavas_video_sure:.2f}s"
        )
    else:
        hedef_sure = video_sure
        log_ekle("🎬 Video yavaşlatma gerekmedi (hedef süre videoya yakın veya kısa).")

    vf_filtre = ",".join(vf_parcalari)

    # 4K için daha hızlı preset ve daha uzun timeout
    encode_preset = "veryfast" if hedef_cozunurluk >= 2160 else VIDEO_PRESET
    ffmpeg_timeout = 900 if hedef_cozunurluk >= 2160 else 300

    if hedef_cozunurluk >= 2160 and video_sure > 120:
        log_ekle("⚠️ 4K + uzun video: işlem normalden uzun sürebilir.")

    komut = [
        FFMPEG_BIN, "-y",
        "-i", video_yolu,
        "-i", ses_yolu,
        "-vf", vf_filtre,
        "-af", "apad",
        "-t", f"{hedef_sure:.3f}",
        "-c:v", "libx264", "-preset", encode_preset, "-crf", str(VIDEO_CRF),
        "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        cikti_v_yolu
    ]

    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=ffmpeg_timeout)

        if sonuc.returncode != 0:
            log_ekle(f"⚠️ ffmpeg hata: {sonuc.stderr[-300:] if sonuc.stderr else 'bilinmeyen'}")

            # Fallback: upscale olmadan tekrar dene (yavaşlatma korunur)
            log_ekle("🔄 Fallback: upscale olmadan tekrar deneniyor...")

            fallback_vf = None
            if video_yavaslatma < 0.999:
                fallback_vf = f"setpts=PTS*{round(1.0 / video_yavaslatma, 4)}"

            fallback_komut = [
                FFMPEG_BIN, "-y",
                "-i", video_yolu,
                "-i", ses_yolu,
            ]

            if fallback_vf:
                fallback_komut += ["-vf", fallback_vf]
                fallback_komut += ["-c:v", "libx264", "-preset", encode_preset, "-crf", str(VIDEO_CRF)]
            else:
                fallback_komut += ["-c:v", "copy"]

            fallback_komut += [
                "-af", "apad",
                "-t", f"{hedef_sure:.3f}",
                "-c:a", "aac", "-b:a", "192k",
                "-map", "0:v:0",
                "-map", "1:a:0",
                cikti_v_yolu
            ]

            fallback_sonuc = subprocess.run(fallback_komut, capture_output=True, text=True, timeout=ffmpeg_timeout)

            if fallback_sonuc.returncode != 0:
                log_ekle(f"⚠️ Fallback ffmpeg hata: {fallback_sonuc.stderr[-300:] if fallback_sonuc.stderr else 'bilinmeyen'}")
                return False

            log_ekle("✅ Video + ses birleştirildi (fallback: orijinal çözünürlük)")
            return True

        log_ekle("✅ Video ve ses başarıyla birleştirildi!")
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

