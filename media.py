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

# ===== AYARLAR =====
# Düşük çözünürlüklü videoları çok fazla büyütmeyi engeller
MAKS_UPSCALE_CARPANI = 2.0

# Video hızlandırma / yavaşlatma limitleri
MAKS_VIDEO_HIZLANDIRMA = 1.5   # Video en fazla 1.5x hızlandırılabilir
MIN_VIDEO_YAVASLATMA = 0.5     # Video en fazla 0.5x yavaşlatılabilir

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

# ===== VİDEO + SES BİRLEŞTİRME (UPSCALE + KESKİNLEŞTİRME + HIZ AYARI) =====
def video_ve_sesi_birlestir(
    video_yolu: str,
    ses_yolu: str,
    cikti_v_yolu: str,
    log_ekle,
    hedef_y: int = HEDEF_2K_Y
) -> bool:
    """
    Videoya AI sesini ekle + seçilen upscale + sese uyum için video hız ayarı.

    Yeni mantık:
      - Ses her zaman 1.2x hızda kalır.
      - Ses videodan uzunsa video yavaşlatılır.
      - Ses videodan kısaysa video hızlandırılır.
      - Çok aşırı fark varsa limit uygulanır ve kalan boşluk sessizlikle doldurulur.
    """

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
    # 1) VİDEO HIZ AYARI
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
    # 2) UPSCALE HEDEFİ VE KAYNAK KALİTE KORUMASI
    # ============================================================
    secilen_hedef_kenar = int(hedef_y) if hedef_y else HEDEF_2K_Y
    if secilen_hedef_kenar <= 0:
        secilen_hedef_kenar = HEDEF_2K_Y

    def apply_upscale_cap(target_short_edge):
        """
        Düşük çözünürlüklü kaynakları çok fazla büyütmeyi engeller.
        """
        if target_short_edge is None:
            return None

        try:
            target_short_edge = int(target_short_edge)
        except Exception:
            target_short_edge = HEDEF_2K_Y

        if target_short_edge <= 0:
            return target_short_edge

        orijinal_kisa_kenar = min(genislik, yukseklik)
        max_allowed = int(orijinal_kisa_kenar * MAKS_UPSCALE_CARPANI)
        max_allowed = max(2, max_allowed)

        if target_short_edge > max_allowed:
            return max_allowed

        return target_short_edge

    hedef_kenar = apply_upscale_cap(secilen_hedef_kenar)

    if hedef_kenar is None or hedef_kenar <= 0:
        hedef_kenar = HEDEF_2K_Y

    if hedef_kenar != secilen_hedef_kenar:
        log_ekle(
            f"⚠️ Kaynak çözünürlük düşük: kısa kenar {min(genislik, yukseklik)}px. "
            f"Upscale hedefi {secilen_hedef_kenar}px → {hedef_kenar}px olarak sınırlandı "
            f"({MAKS_UPSCALE_CARPANI:.1f}x limit)."
        )

    # ============================================================
    # YARDIMCI: HEDEF ÇÖZÜNÜRLÜK HESAPLA
    # ============================================================
    def calculate_target_resolution(target_short_edge):
        target_short_edge = apply_upscale_cap(target_short_edge)

        if target_short_edge is None or target_short_edge <= 0:
            return genislik, yukseklik, False

        orijinal_kisa_kenar = min(genislik, yukseklik)

        if orijinal_kisa_kenar >= target_short_edge:
            return genislik, yukseklik, False

        # Yatay video: hedef kısa kenar yükseklik olur
        if genislik >= yukseklik:
            out_h = target_short_edge
            out_w = int(round(genislik * out_h / yukseklik)) if yukseklik > 0 else genislik
        # Dikey video: hedef kısa kenar genişlik olur
        else:
            out_w = target_short_edge
            out_h = int(round(yukseklik * out_w / genislik)) if genislik > 0 else yukseklik

        out_w = max(2, out_w)
        out_h = max(2, out_h)

        out_w += out_w % 2
        out_h += out_h % 2

        return out_w, out_h, True

    # ============================================================
    # YARDIMCI: VIDEO FİLTRESİ OLUŞTUR
    # ============================================================
    def build_vf(target_short_edge, unsharp=True):
        """
        Filtre sırası:
          1) setpts  -> hızlandırma/yavaşlatma
          2) scale   -> upscale
          3) unsharp -> keskinleştirme
          4) format  -> uyumluluk
        """
        vf_parts = []

        # 1) Video hız ayarı
        if abs(video_hiz_carpani - 1.0) > 0.001:
            setpts_carpani = round(1.0 / video_hiz_carpani, 4)
            vf_parts.append(f"setpts=PTS*{setpts_carpani}")

        # 2) Upscale
        out_w, out_h, upscaled = calculate_target_resolution(target_short_edge)
        if upscaled:
            vf_parts.append(f"scale={out_w}:{out_h}:flags=lanczos")

        # 3) Keskinleştirme
        if unsharp:
            orijinal_kisa = min(genislik, yukseklik)
            hedef_kisa = min(out_w, out_h)
            factor = hedef_kisa / orijinal_kisa if orijinal_kisa > 0 else 1.0

            if orijinal_kisa < 720 or factor > 1.8:
                vf_parts.append("unsharp=3:3:0.5:3:3:0.0")
            else:
                vf_parts.append("unsharp=5:5:1.0:3:3:0.0")

        # 4) Format
        if vf_parts:
            vf_parts.append("format=yuv420p")

        return ",".join(vf_parts), out_w, out_h, upscaled

    # ============================================================
    # 3) ANA VİDEO FİLTRESİNİ OLUŞTUR
    # ============================================================
    vf_filtre, out_w, out_h, upscaled = build_vf(hedef_kenar, unsharp=True)

    if upscaled:
        if hedef_kenar >= 2160:
            log_ekle(f"🎬 4K Upscale: {genislik}x{yukseklik} → {out_w}x{out_h}")
        elif hedef_kenar >= 1440:
            log_ekle(f"🎬 2K Upscale: {genislik}x{yukseklik} → {out_w}x{out_h}")
        else:
            log_ekle(f"🎬 Upscale: {genislik}x{yukseklik} → {out_w}x{out_h}")
    else:
        log_ekle(
            f"🎬 Upscale gerekmedi: {genislik}x{yukseklik} | "
            f"hedef kısa kenar {hedef_kenar}px"
        )

    log_ekle(f"📐 Çıkış hedefi: {out_w}x{out_h}")
    log_ekle(f"🎛️ Video filtresi: {vf_filtre}")

    # 4K için daha hızlı preset ve daha uzun timeout
    encode_preset = "veryfast" if secilen_hedef_kenar >= 2160 else VIDEO_PRESET
    ffmpeg_timeout = 900 if secilen_hedef_kenar >= 2160 else 300

    if secilen_hedef_kenar >= 2160 and video_sure > 120:
        log_ekle("⚠️ 4K + uzun video: işlem normalden uzun sürebilir.")

    # ============================================================
    # FFMPEG ÇALIŞTIRMA YARDIMCISI
    # ============================================================
    def run_ffmpeg(vf_str: str, use_libx264: bool = True):
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
                "-preset", encode_preset,
                "-crf", str(VIDEO_CRF),
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

        return subprocess.run(komut, capture_output=True, text=True, timeout=ffmpeg_timeout)

    # ============================================================
    # RENDER
    # ============================================================
    try:
        sonuc = run_ffmpeg(vf_filtre, True)

        if sonuc.returncode == 0:
            log_ekle("✅ Video ve ses başarıyla birleştirildi!")
            return True

        log_ekle(f"⚠️ ffmpeg hata: {sonuc.stderr[-300:] if sonuc.stderr else 'bilinmeyen'}")

        # ============================================================
        # FALLBACK 1: 4K seçildiyse 2K'ya düş
        # ============================================================
        fallback_hedef = 1440 if secilen_hedef_kenar >= 2160 else None

        if fallback_hedef is not None:
            log_ekle(f"🔄 Fallback: {fallback_hedef}px upscale deneniyor...")
        else:
            log_ekle("🔄 Fallback: orijinal çözünürlük deneniyor...")

        fallback_vf, fb_w, fb_h, fb_upscaled = build_vf(fallback_hedef, unsharp=False)

        if fallback_vf:
            fallback_sonuc = run_ffmpeg(fallback_vf, True)
        else:
            fallback_sonuc = run_ffmpeg("", False)

        if fallback_sonuc.returncode == 0:
            if fb_upscaled:
                log_ekle(f"✅ Video + ses birleştirildi (fallback upscale: {fb_w}x{fb_h})")
            else:
                log_ekle("✅ Video + ses birleştirildi (fallback: orijinal çözünürlük)")
            return True

        log_ekle(f"⚠️ Fallback ffmpeg hata: {fallback_sonuc.stderr[-300:] if fallback_sonuc.stderr else 'bilinmeyen'}")

        # ============================================================
        # FALLBACK 2: Gerekirse tamamen orijinal çözünürlüğe düş
        # ============================================================
        if fallback_hedef is not None:
            log_ekle("🔄 Son fallback: orijinal çözünürlük deneniyor...")
            final_vf, _, _, _ = build_vf(None, unsharp=False)

            if final_vf:
                final_sonuc = run_ffmpeg(final_vf, True)
            else:
                final_sonuc = run_ffmpeg("", False)

            if final_sonuc.returncode == 0:
                log_ekle("✅ Video + ses birleştirildi (son fallback: orijinal çözünürlük)")
                return True

            log_ekle(f"⚠️ Son fallback ffmpeg hata: {final_sonuc.stderr[-300:] if final_sonuc.stderr else 'bilinmeyen'}")

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
