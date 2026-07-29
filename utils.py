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

# ===== TARİH =====
def guncel_tarih_metni() -> str:
    simdi = datetime.now()
    return f"{simdi.day} {TURKCE_AYLAR[simdi.month]} {simdi.year}"

# ===== PROMPT DOSYASI OKUMA =====
def prompt_dosyasini_oku(dosya_adi: str) -> str:
    try:
        # Dosya yolunu projenin kendi dizinine göre çöz (Streamlit Cloud uyumlu)
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
    # Sınırların dışındaki değerler için zincirleme atempo uygula
    if hiz_carpani < 0.5 or hiz_carpani > 2.0:
        log_ekle(f"⚠️ atempo={hiz_carpani} ffmpeg sınırı dışında (0.5-2.0), zincirleme filtre uygulanıyor...")
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
        "ffmpeg", "-y", "-i", giris_dosyasi,
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

# ===== VİDEO SÜRE TESPİTİ VE İŞLEME =====
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

    komut = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_yolu
    ]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=5)
        if sonuc.returncode == 0 and sonuc.stdout.strip():
            val = float(sonuc.stdout.strip())
            if val > 0:
                return val
    except Exception:
        pass

    return 30.0

def kapak_fotografi_cikar(video_yolu: str, saniye: float, cikti_resim_yolu: str, log_ekle) -> bool:
    komut = [
        "ffmpeg", "-y",
        "-ss", str(saniye),
        "-i", video_yolu,
        "-vframes", "1",
        "-q:v", "2",
        cikti_resim_yolu
    ]
    try:
        sonuc = subprocess.run(komut, capture_output=True, text=True, timeout=30)
        return sonuc.returncode == 0 and os.path.exists(cikti_resim_yolu)
    except Exception as e:
        log_ekle(f"⚠️ Kapak fotoğrafı çıkarılamadı: {e}")
        return False

def video_ve_sesi_birlestir_4k_ve_senkronize(
    video_yolu: str,
    ses_yolu: str,
    kapak_saniyesi: float,
    cikti_v_yolu: str,
    cikti_kapak_yolu: str,
    log_ekle
) -> bool:
    try:
        log_ekle(f"📸 En çarpıcı kapak anı ({kapak_saniyesi}n) fotoğrafa dönüştürülüyor...")
        kapak_fotografi_cikar(video_yolu, kapak_saniyesi, cikti_kapak_yolu, log_ekle)

        video_sure = video_suresini_al(video_yolu)
        with wave.open(ses_yolu, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            audio_sure = frames / rate

        log_ekle(f"⏱️ Video süresi: {video_sure:.2f}sn | Ses süresi: {audio_sure:.2f}sn")

        hiz_orani = audio_sure / video_sure if video_sure > 0 else 1.0

        intro_yolu = os.path.join(tempfile.gettempdir(), f"intro_{uuid.uuid4().hex[:8]}.mp4")
        vars_kapak = cikti_kapak_yolu if os.path.exists(cikti_kapak_yolu) else None
        
        has_intro = False
        if vars_kapak:
            intro_komut = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", vars_kapak,
                "-t", "0.5",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                intro_yolu
            ]
            res_intro = subprocess.run(intro_komut, capture_output=True, text=True, timeout=30)
            if res_intro.returncode == 0 and os.path.exists(intro_yolu):
                has_intro = True

        if has_intro:
            filter_str = f"[0:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,setsar=1[v0];" \
                         f"[1:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,setsar=1[v1];" \
                         f"[v0][v1]concat=n=2:v=1:a=0[vcat];" \
                         f"[vcat]setpts=PTS*{hiz_orani}[vfin]"
            komut = [
                "ffmpeg", "-y",
                "-i", intro_yolu,
                "-i", video_yolu,
                "-i", ses_yolu,
                "-filter_complex", filter_str,
                "-map", "[vfin]",
                "-map", "2:a:0",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                cikti_v_yolu
            ]
        else:
            filter_str = f"[0:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,setsar=1,setpts=PTS*{hiz_orani}[vfin]"
            komut = [
                "ffmpeg", "-y",
                "-i", video_yolu,
                "-i", ses_yolu,
                "-filter_complex", filter_str,
                "-map", "[vfin]",
                "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                cikti_v_yolu
            ]

        log_ekle("🎬 4K Upscale (boşluksuz, kırpmalı), süre senkronizasyonu ve ses birleştirme yapılıyor...")
        proje = subprocess.run(komut, capture_output=True, text=True, timeout=600)
        
        temp_dosya_temizle(intro_yolu)

        if proje.returncode != 0:
            log_ekle(f"⚠️ FFmpeg 4K render hata: {proje.stderr[-400:] if proje.stderr else 'bilinmeyen'}")
            return False
        
        log_ekle("✅ 4K Video, kapak fotoğrafı ve ses senkronizasyonu başarıyla tamamlandı!")
        return True
    except Exception as e:
        log_ekle(f"⚠️ 4K render beklenmeyen hata: {e}")
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
    # Saniyeye birebir oranlanmış kelime hedefi (örn. 16 saniye -> ~40-45 kelime)
    hedef_kelime = round(sure_saniye * 2.5 / 5) * 5
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
