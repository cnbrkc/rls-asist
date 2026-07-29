import time
import re
import base64
import wave
import os
import shutil
import tempfile
import uuid
from typing import List, Tuple, Any
import streamlit as st
from google import genai
from google.genai import types

from config import (
    API_KEYS, METIN_MODELLERI, SES_MODELLERI, VIDEO_ANALIZ_MODELLERI,
    COOLDOWN_SUNUCU, COOLDOWN_BULUNAMADI, COOLDOWN_DIGER,
    COOLDOWN_FREE_TIER_YOK, IP_BAN_KORUMA, QUOTA_RETRY_DEFAULT,
    model_arama_destekliyor_mu
)
from utils import (
    guvenli_json_yukle, sesi_hizlandir, temp_dosya_temizle,
    video_analiz_promptunu_olustur
)

class SmartRouter:
    def __init__(self) -> None:
        if "blacklist" not in st.session_state:
            st.session_state.blacklist = {}

    def _is_banned(self, mail: str, model: str) -> bool:
        now = time.time()
        bl = st.session_state.blacklist
        for key in [f"*+{model}", f"{mail}+*", f"{mail}+{model}"]:
            if key in bl:
                if now < bl[key]:
                    return True
                else:
                    del bl[key]
        return False

    def _ban(self, mail: str, model: str, cooldown: int, scope: str) -> None:
        key = f"*+{model}" if scope == "model" else (f"{mail}+*" if scope == "key" else f"{mail}+{model}")
        st.session_state.blacklist[key] = time.time() + cooldown

    def _retry_delay_cikar(self, hata_metni: str) -> int:
        match = re.search(r"retryDelay[\"':\s]+(\d+)", hata_metni)
        if match:
            try:
                return int(match.group(1)) + 1
            except ValueError:
                pass
        match2 = re.search(r"retry in (\d+(?:\.\d+)?)s", hata_metni, re.IGNORECASE)
        if match2:
            try:
                return int(float(match2.group(1))) + 1
            except ValueError:
                pass
        return 0

    def _parse_hata(self, hata_metni: str) -> Tuple[str, int]:
        if "limit: 0" in hata_metni or "limit\": 0" in hata_metni:
            return "free_tier_yok", COOLDOWN_FREE_TIER_YOK
        if "429" in hata_metni or "resource_exhausted" in hata_metni or "quota" in hata_metni:
            return "quota", 0
        if "503" in hata_metni or "unavailable" in hata_metni:
            return "combo", COOLDOWN_SUNUCU
        if "404" in hata_metni or "not_found" in hata_metni:
            return "model", COOLDOWN_BULUNAMADI
        return "combo", COOLDOWN_DIGER

    def _handle_hata(self, mail: str, model: str, hata_metni: str, log_ekle) -> str:
        scope, cooldown = self._parse_hata(hata_metni)
        if scope == "free_tier_yok":
            log_ekle(f" 🚫 {model} free tier'da YOK (limit: 0) → 7 gün banlandı")
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"
        if scope == "quota":
            delay = self._retry_delay_cikar(hata_metni)
            ban_sure = delay if delay > 0 else QUOTA_RETRY_DEFAULT
            self._ban(mail, model, ban_sure, "combo")
            log_ekle(f" ⏳ {mail} kota aştı → {ban_sure}sn banlandı, diğer key deneniyor")
            time.sleep(IP_BAN_KORUMA)
            return "devam"

        ban_sure = f"{cooldown // 60} dk" if cooldown < 3600 else f"{cooldown // 3600} saat"
        if scope == "model":
            log_ekle(f" ❌ {model} MODEL bazlı hata → TÜM key'ler için {ban_sure} banlandı")
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"
        else:
            log_ekle(f" ⚠️ {mail} hatası → {model} ile {ban_sure} banlandı, diğer key deneniyor")
            self._ban(mail, model, cooldown, scope)
            time.sleep(IP_BAN_KORUMA)
            return "devam"

    def _make_request(self, model_listesi: List[str], contents: Any, config: types.GenerateContentConfig, log_ekle) -> Tuple[Any, str]:
        son_hata = None
        for model_adi in model_listesi:
            log_ekle(f"🧠 Model deneniyor: {model_adi}")
            model_denendi = False
            for mail, api_key in API_KEYS.items():
                if self._is_banned(mail, model_adi):
                    log_ekle(f" ⏸️ {mail} + {model_adi} banlı, atlanıyor")
                    continue
                model_denendi = True
                log_ekle(f" 🚀 {mail} ile {model_adi} deneniyor...")
                try:
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model=model_adi,
                        contents=contents,
                        config=config
                    )
                    log_ekle(f" ✅ Başarılı → {mail} + {model_adi}")
                    time.sleep(IP_BAN_KORUMA)
                    return response, f"{mail}+{model_adi}"
                except Exception as e:
                    son_hata = e
                    aksiyon = self._handle_hata(mail, model_adi, str(e), log_ekle)
                    if aksiyon == "break_model":
                        break
            if not model_denendi:
                log_ekle(f" ⏸️ {model_adi} tüm key'ler için banlı, atlanıyor")
        raise son_hata if son_hata else Exception("Tüm model+key kombinasyonları başarısız.")

    def metin_uret(self, video_icerigi: str, system_prompt: str, response_schema: dict, log_ekle, model_listesi=None, arama_kullan: bool = True) -> Tuple[dict, str]:
        if model_listesi is None:
            model_listesi = METIN_MODELLERI
        config_parametreleri = dict(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        if arama_kullan and model_arama_destekliyor_mu(model_listesi[0]):
            config_parametreleri["tools"] = [types.Tool(google_search=types.GoogleSearch())]
            log_ekle(f" 🔎 {model_listesi[0]} için güncel bilgi araması aktif")
        config = types.GenerateContentConfig(**config_parametreleri)
        response, info = self._make_request(model_listesi, video_icerigi, config, log_ekle)
        return guvenli_json_yukle(getattr(response, "text", "")), info

    def ses_uret(self, metin: str, ses_adi: str, cikti_dosyasi: str, log_ekle, hiz_carpani: float = 1.0) -> Tuple[bool, str]:
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=ses_adi)
                )
            ),
        )
        try:
            tts_response, info = self._make_request(SES_MODELLERI, metin, config, log_ekle)
        except Exception:
            log_ekle("❌ Hiçbir ses modeli başarılı olamadı.")
            return False, None

        try:
            candidates = getattr(tts_response, "candidates", None)
            if not candidates:
                raise ValueError("TTS candidates bulunamadı")
            content = getattr(candidates[0], "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                raise ValueError("TTS parts bulunamadı")
            inline_data = getattr(parts[0], "inline_data", None)
            audio_data = getattr(inline_data, "data", None) if inline_data else None
            if not audio_data:
                raise ValueError("TTS audio verisi boş")
            if isinstance(audio_data, str):
                audio_data = base64.b64decode(audio_data)

            if abs(hiz_carpani - 1.0) < 0.001:
                with wave.open(cikti_dosyasi, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(audio_data)
                return True, info

            gecici_ham_dosya = os.path.join(tempfile.gettempdir(), f"ses_ham_{uuid.uuid4().hex[:8]}.wav")
            try:
                with wave.open(gecici_ham_dosya, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(audio_data)
                log_ekle(f"🎚️ Ses {hiz_carpani}x hızlandırılıyor (ffmpeg atempo, pitch korunur)...")
                basarili = sesi_hizlandir(gecici_ham_dosya, cikti_dosyasi, hiz_carpani, log_ekle)
                if not basarili:
                    log_ekle("⚠️ Hızlandırma başarısız, ham ses kullanılıyor.")
                    shutil.copy2(gecici_ham_dosya, cikti_dosyasi)
                else:
                    log_ekle(f"✅ Ses {hiz_carpani}x ile hızlandırıldı.")
                return True, info
            finally:
                temp_dosya_temizle(gecici_ham_dosya)
        except Exception as e:
            log_ekle(f"❌ Ses verisi işlenirken hata: {e}")
            return False, None

    def video_analiz_et(self, video_bytes: bytes, mime_type: str, analiz_notlari: str, sure_saniye: int, log_ekle) -> Tuple[str, str]:
        video_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        ek_notlar_bolumu = ""
        if analiz_notlari.strip():
            ek_notlar_bolumu = f"""
 ÖNEMLİ: Kullanıcı videoyu analiz ettirirken sana şu VİDEO ANALİZ NOTLARINI iletti.
 --- VİDEO ANALİZ NOTLARI ---
 {analiz_notlari}
 -------------------------------
 """
        analiz_promptu = video_analiz_promptunu_olustur(ek_notlar_bolumu, sure_saniye)
        config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        response, info = self._make_request(VIDEO_ANALIZ_MODELLERI, [video_part, analiz_promptu], config, log_ekle)
        return getattr(response, "text", ""), info
