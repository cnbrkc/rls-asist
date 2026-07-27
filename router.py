"""SmartRouter — API key rotasyonu, ban yönetimi, model fallback."""
import re
import time

from google import genai
from google.genai import types
import streamlit as st

from config import (
    GEMINI_KEYS,
    COOLDOWN_QUOTA,
    COOLDOWN_UNAVAILABLE,
    COOLDOWN_GENERIC,
    COOLDOWN_NOT_FOUND,
    COOLDOWN_FREE_TIER_YOK,
    VIDEO_ANALIZ_MODELLERI,
    METIN_MODELLERI,
    SES_MODELI,
)
from utils import gecici_dosya_olustur


class SmartRouter:
    def __init__(self):
        if "blacklist" not in st.session_state:
            st.session_state.blacklist = {}

    def _is_banned(self, mail: str, model: str) -> bool:
        bl = st.session_state.blacklist
        simdi = time.time()
        for anahtar in [f"{mail}:{model}", model]:
            if anahtar in bl:
                if simdi < bl[anahtar]:
                    return True
                else:
                    del bl[anahtar]
        return False

    def _ban(self, mail: str, model: str, sure: int, scope: str = "combo"):
        simdi = time.time()
        bl = st.session_state.blacklist
        if scope == "model":
            bl[model] = simdi + sure
        elif scope == "key":
            for m in METIN_MODELLERI + VIDEO_ANALIZ_MODELLERI + [SES_MODELI]:
                bl[f"{mail}:{m}"] = simdi + sure
        else:
            bl[f"{mail}:{model}"] = simdi + sure

    def _retry_delay_cikar(self, hata_metni: str) -> int:
        eslesme = re.search(r'retryDelay["\s:]+(\d+)', hata_metni)
        if eslesme:
            return int(eslesme.group(1))
        eslesme = re.search(r"(\d+)s", hata_metni)
        if eslesme:
            return int(eslesme.group(1))
        return 0

    def _parse_hata(self, hata: Exception) -> dict:
        hata_str = str(hata).lower()
        sonuc = {
            "tip": "generic",
            "cooldown": COOLDOWN_GENERIC,
            "scope": "combo",
            "aksiyon": "devam",
        }

        if "free tier" in hata_str and ("limit: 0" in hata_str or 'limit": 0' in hata_str):
            sonuc.update({
                "tip": "free_tier_yok",
                "cooldown": COOLDOWN_FREE_TIER_YOK,
                "scope": "model",
                "aksiyon": "break_model",
            })
        elif "429" in hata_str or "quota" in hata_str or "resource_exhausted" in hata_str:
            delay = self._retry_delay_cikar(str(hata))
            sonuc.update({"tip": "quota", "cooldown": max(delay, COOLDOWN_QUOTA)})
        elif "503" in hata_str or "unavailable" in hata_str:
            sonuc.update({"tip": "unavailable", "cooldown": COOLDOWN_UNAVAILABLE})
        elif "404" in hata_str or "not found" in hata_str:
            sonuc.update({
                "tip": "not_found",
                "cooldown": COOLDOWN_NOT_FOUND,
                "scope": "model",
                "aksiyon": "break_model",
            })

        return sonuc

    def _handle_hata(self, mail: str, model: str, hata: Exception, log_ekle=None):
        bilgi = self._parse_hata(hata)
        self._ban(mail, model, bilgi["cooldown"], bilgi["scope"])
        if log_ekle:
            log_ekle(f"⚠️ {mail[:3]}*** / {model}: {bilgi['tip']} ({bilgi['cooldown']}sn ban)")
        return bilgi["aksiyon"]

    def _make_request(self, modeller: list, istek_fn, log_ekle=None):
        for model in modeller:
            for mail, key in GEMINI_KEYS.items():
                if self._is_banned(mail, model):
                    continue
                try:
                    client = genai.Client(api_key=key)
                    sonuc = istek_fn(client, model)
                    if log_ekle:
                        log_ekle(f"✅ {mail[:3]}*** / {model}")
                    return sonuc
                except Exception as e:
                    aksiyon = self._handle_hata(mail, model, e, log_ekle)
                    if aksiyon == "break_model":
                        break
        return None

    def metin_uret(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict,
        modeller: list = None,
        arama: bool = False,
        log_ekle=None,
    ):
        if modeller is None:
            modeller = METIN_MODELLERI

        tools = []
        if arama:
            tools.append(types.Tool(google_search=types.GoogleSearch()))

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=0.9,
            top_p=0.95,
        )
        if tools:
            config.tools = tools

        def istek(client, model):
            return client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=config,
            )

        yanit = self._make_request(modeller, istek, log_ekle)
        if yanit is None:
            return None
        return yanit.text

    def ses_uret(self, metin: str, ses_adi: str, log_ekle=None):
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=ses_adi)
                )
            ),
        )

        def istek(client, model):
            return client.models.generate_content(
                model=model,
                contents=metin,
                config=config,
            )

        yanit = self._make_request([SES_MODELI], istek, log_ekle)
        if yanit is None:
            return None

        try:
            audio_data = yanit.candidates[0].content.parts[0].inline_data.data
            dosya_yolu = gecici_dosya_olustur(audio_data, ".wav")
            return dosya_yolu
        except (IndexError, AttributeError):
            return None

    def video_analiz_et(self, video_bytes: bytes, prompt: str, log_ekle=None):
        config = types.GenerateContentConfig(
            temperature=0.7,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        video_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")

        def istek(client, model):
            return client.models.generate_content(
                model=model,
                contents=[video_part, prompt],
                config=config,
            )

        yanit = self._make_request(VIDEO_ANALIZ_MODELLERI, istek, log_ekle)
        if yanit is None:
            return None
        return yanit.text
