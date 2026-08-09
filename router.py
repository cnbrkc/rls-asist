import time
import re
import base64
import os
import shutil
from typing import List, Tuple, Any, Optional
import streamlit as st
from google import genai
from google.genai import types

from config import (
    API_KEYS, METIN_MODELLERI, ARAMA_MODELLERI, SES_MODELLERI, VIDEO_ANALIZ_MODELLERI,
    COOLDOWN_SUNUCU, COOLDOWN_BULUNAMADI, COOLDOWN_DIGER,
    COOLDOWN_FREE_TIER_YOK, IP_BAN_KORUMA, QUOTA_RETRY_DEFAULT,
    model_arama_destekliyor_mu
)
from utils import guvenli_json_yukle
from media import sesi_hizlandir, temp_dosya_temizle, wav_yaz, gecici_dosya_yolu

class SmartRouter:
    def __init__(self) -> None:
        if "blacklist" not in st.session_state:
            st.session_state.blacklist = {}
        # Son isteğin kota/rate-limit yüzünden tamamen başarısız olup olmadığını
        # takip eder. Bu bilgi özellikle Google Search grounding başarısızlığında
        # aynı Fact Lock isteğini Search'süz güvenli fallback ile sürdürebilmek için
        # kullanılır.
        self._last_request_had_quota = False

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

    def _clear_cooldowns(self, model_listesi=None) -> None:
        """Geçici router cooldown'larını temizler.

        Research sırasında Google Search grounding 429 verip, aynı Fact Lock
        isteği Search'süz başarıyla tamamlanırsa, Search denemesinin bıraktığı
        cooldown'ların sonraki Editorial/Reels aşamalarını gereksiz yere
        kilitlemesini önler.
        """
        bl = st.session_state.blacklist
        if not model_listesi:
            bl.clear()
            return

        modeller = set(model_listesi)
        silinecek = []
        for key in list(bl.keys()):
            # *+MODEL veya KEY+MODEL biçimindeki kayıtlar
            if "+" not in key:
                continue
            sol, sag = key.split("+", 1)
            if sag in modeller:
                silinecek.append(key)

        for key in silinecek:
            bl.pop(key, None)

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
        metin = (hata_metni or "").lower()

        if (
            "404" in metin
            or "not_found" in metin
            or "model not found" in metin
            or "is not found for api version" in metin
        ):
            return "model", COOLDOWN_BULUNAMADI

        if "limit: 0" in metin or 'limit": 0' in metin:
            return "free_tier_yok", COOLDOWN_FREE_TIER_YOK

        if (
            "429" in metin
            or "resource_exhausted" in metin
            or "quota" in metin
            or "rate limit" in metin
        ):
            return "quota", 0

        if (
            "400" in metin
            or "invalid_argument" in metin
            or "bad request" in metin
            or "unsupported" in metin
        ):
            return "model_config", COOLDOWN_BULUNAMADI

        if "503" in metin or "unavailable" in metin:
            return "combo", COOLDOWN_SUNUCU

        return "combo", COOLDOWN_DIGER

    def _handle_hata(self, mail: str, model: str, hata_metni: str, log_ekle) -> str:
        scope, cooldown = self._parse_hata(hata_metni)

        if scope == "free_tier_yok":
            log_ekle(
                f" 🚫 {model} free tier'da YOK (limit: 0) → "
                f"model geçici olarak devre dışı."
            )
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"

        if scope == "quota":
            self._last_request_had_quota = True
            delay = self._retry_delay_cikar(hata_metni)

            # retryDelay varsa bu gerçek kısa süreli rate-limit olabilir.
            # Yoksa "current quota / exceeded quota" gibi plan kotasıdır.
            if delay > 0:
                ban_sure = delay
                log_ekle(
                    f" ⏳ {mail} + {model}: kısa süreli rate-limit → "
                    f"{ban_sure}sn cooldown."
                )
            else:
                ban_sure = QUOTA_RETRY_DEFAULT
                log_ekle(
                    f" ⛔ {mail} + {model}: model/proje kotası aşıldı → "
                    f"{ban_sure}sn cooldown. Aynı kota için diğer key'ler "
                    f"gereksiz yere denenmeyecek."
                )

            # Quota'yı key yerine MODEL kapsamında işaretlemek,
            # aynı projedeki 3 key'i art arda vurup logu şişirmeyi önler.
            self._ban(mail, model, ban_sure, "model")
            time.sleep(IP_BAN_KORUMA)
            return "quota"

        if scope == "model_config":
            log_ekle(
                f" ❌ {mail} + {model}: istek/model-konfigürasyonu uyumsuz "
                f"→ model devre dışı bırakılıyor. Hata: {hata_metni[:220]}"
            )
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"

        ban_sure = f"{cooldown // 60} dk" if cooldown < 3600 else f"{cooldown // 3600} saat"
        if scope == "model":
            log_ekle(
                f" ❌ {model} MODEL bazlı hata → tüm key'ler için {ban_sure} devre dışı."
            )
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"

        log_ekle(
            f" ⚠️ {mail} + {model} geçici hata → {ban_sure} cooldown. "
            f"Detay: {hata_metni[:180]}"
        )
        self._ban(mail, model, cooldown, scope)
        time.sleep(IP_BAN_KORUMA)
        return "devam"

    def _make_request(
        self,
        model_listesi: List[str],
        contents: Any,
        config: types.GenerateContentConfig,
        log_ekle,
        stop_on_quota: bool = False,
    ) -> Tuple[Any, str]:
        son_hata = None
        self._last_request_had_quota = False

        for model_adi in model_listesi:
            log_ekle(f"🧠 Model deneniyor: {model_adi}")
            model_denendi = False

            for mail, api_key in API_KEYS.items():
                if self._is_banned(mail, model_adi):
                    log_ekle(f" ⏸️ {mail} + {model_adi} cooldown'da, atlanıyor")
                    continue

                model_denendi = True
                log_ekle(f" 🚀 {mail} ile {model_adi} deneniyor...")

                try:
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model=model_adi,
                        contents=contents,
                        config=config,
                    )
                    log_ekle(f" ✅ Başarılı → {mail} + {model_adi}")
                    time.sleep(IP_BAN_KORUMA)
                    return response, f"{mail}+{model_adi}"

                except Exception as e:
                    son_hata = e
                    aksiyon = self._handle_hata(mail, model_adi, str(e), log_ekle)

                    # Search Grounding quota'sı aynı anda onlarca key/model
                    # kombinasyonunu denemeye değmez. metin_uret() hemen
                    # Search'süz Fact Lock fallback'ine geçsin.
                    if stop_on_quota and aksiyon == "quota":
                        raise

                    if aksiyon in ("break_model", "quota"):
                        break

            if not model_denendi:
                log_ekle(f" ⏸️ {model_adi} tüm key'ler için cooldown'da, atlanıyor")

        raise son_hata if son_hata else Exception("Tüm model+key kombinasyonları başarısız.")

    def metin_uret(self, icerik: Any, system_prompt: str, response_schema: dict, log_ekle, model_listesi=None, arama_kullan: bool = True) -> Tuple[dict, str]:
        """
        Genel metin/JSON üretim motoru. Pipeline'daki TÜM metin aşamaları
        (Research, Editorial, Reels Creative, Caption, Threads, QA) bu tek
        metodu farklı system_prompt + response_schema + icerik ile çağırır.

        icerik: string ya da (video_part gerekmeyen) parça listesi olabilir.
        """
        if model_listesi is None:
            model_listesi = ARAMA_MODELLERI if arama_kullan else METIN_MODELLERI
        config_parametreleri = dict(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        if arama_kullan and model_listesi and model_arama_destekliyor_mu(model_listesi[0]):
            config_parametreleri["tools"] = [types.Tool(google_search=types.GoogleSearch())]
            log_ekle(f" 🔎 {model_listesi[0]} için güncel bilgi araması aktif")
        config = types.GenerateContentConfig(**config_parametreleri)

        try:
            response, info = self._make_request(model_listesi, icerik, config, log_ekle, stop_on_quota=arama_kullan)
        except Exception:
            # Google Search grounding quota/rate-limit yüzünden başarısız olduysa
            # bütün model+key kombinasyonlarını 30 dk kilitleyip pipeline'ı
            # düşürmek yerine aynı Fact Lock isteğini Search'süz bir kez dene.
            # Başarılı Search'süz çağrıdan sonra Search denemesinin geçici
            # cooldown'larını temizle ki Editorial/Reels aşamaları çalışabilsin.
            if arama_kullan and self._last_request_had_quota:
                log_ekle(
                    " 🔁 Google Search çağrısı kota/rate-limit nedeniyle başarısız oldu. "
                    "Search 30 dk geçici kapatılıyor; aynı Fact Lock isteği Search'süz bir kez deneniyor."
                )
                self._clear_cooldowns(model_listesi)

                fallback_config_parametreleri = dict(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                )
                fallback_config = types.GenerateContentConfig(**fallback_config_parametreleri)

                response, info = self._make_request(
                    model_listesi,
                    icerik,
                    fallback_config,
                    log_ekle,
                    stop_on_quota=False,
                )
                log_ekle(
                    " ⚠️ Fact Lock Search'süz fallback ile tamamlandı. "
                    "Güncel doğrulama yapılamayan alanlar işaretlendi."
                )
                return guvenli_json_yukle(getattr(response, "text", "")), info
            raise

        return guvenli_json_yukle(getattr(response, "text", "")), info

    def _tts_performans_promptu_olustur(self, metin: str, ses_adi: str) -> str:
        """Gemini TTS için insanî konuşma performansı yönlendirmesi.

        Google'ın güncel TTS rehberindeki Audio Profile + Scene + Director's
        Notes + açık Transcript sınırı yaklaşımını kullanır. Türkçe metinde
        audio tag'leri İngilizce bırakılır; Google bunu özellikle öneriyor.
        """
        ses_profilleri = {
            "Autonoe": "bright, confident, friendly, youthful-adult female presenter",
            "Puck": "upbeat, charismatic, energetic male presenter",
            "Aoede": "breezy, warm, relaxed female presenter",
            "Callirrhoe": "easy-going, natural, conversational female presenter",
            "Kore": "firm, clear, confident female presenter",
            "Leda": "youthful, lively, friendly female presenter",
            "Zephyr": "bright, clean, energetic female presenter",
            "Charon": "informative, calm, authoritative male presenter",
            "Orus": "firm, strong, confident male presenter",
            "Iapetus": "clear, fluid, conversational male presenter",
            "Umbriel": "easy-going, relaxed, natural male presenter",
            "Achird": "friendly, casual, conversational presenter",
            "Zubenelgenubi": "casual, approachable, natural presenter",
            "Sadaltager": "knowledgeable, calm, credible presenter",
            "Sulafat": "warm, reassuring, human presenter",
        }
        profil = ses_profilleri.get(ses_adi, "natural, friendly, conversational automotive presenter")

        satirlar = [s.strip() for s in (metin or "").splitlines() if s.strip()]
        if not satirlar:
            satirlar = [metin.strip()]

        # Aşırı tag kullanmıyoruz; birkaç stratejik tag doğal prosodiyi destekler.
        # Kullanıcının metninde zaten tag varsa onları koru.
        if satirlar and not satirlar[0].startswith("["):
            satirlar[0] = "[curious] " + satirlar[0]

        for i, satir in enumerate(satirlar):
            if i == 0:
                continue
            if "!" in satir and not satir.startswith("["):
                satirlar[i] = "[excitedly] " + satir
            elif "?" in satir and not satir.startswith("["):
                satirlar[i] = "[curious] " + satir

        transcript = "\n".join(satirlar)

        return f"""SYNTHESIZE SPEECH ONLY. Do not read these instructions aloud.
This is a Turkish automotive Instagram Reels voiceover performed by one human presenter.

# AUDIO PROFILE
The presenter is {profil}.
They sound like a real Turkish automotive content creator speaking naturally to the camera, not a commercial announcer and not a robotic narrator.

# SCENE
A close, energetic social-media recording. The presenter is genuinely interested in the car and is talking directly to one person who likes cars.
The performance should feel spontaneous, confident and human.

# DIRECTOR'S NOTES
- Language: Turkish. Pronounce Turkish naturally and clearly.
- Use a conversational cadence with small, believable pauses.
- Vary sentence rhythm and emphasis; do not make every sentence sound equally energetic.
- Start with curiosity and pull the listener into the first sentence.
- Let important facts land with subtle emphasis instead of shouting.
- Keep energy medium-high but controlled; no radio-announcer voice.
- Sound engaged and slightly smiling when appropriate.
- Use natural breath/pause timing between meaning units.
- Technical car names and numbers must be articulated clearly.
- Do not add words, explanations, greetings, or commentary that are not in the transcript.
- Do not read section labels, brackets, or these instructions aloud.
- The transcript below is the ONLY text that should be spoken.
- English audio tags in the transcript are performance directions, not spoken words.

# TRANSCRIPT START
{transcript}
# TRANSCRIPT END
"""

    def _tts_response_audio_bytes(self, tts_response):
        """Gemini TTS response'undan ham PCM verisini çıkar."""
        candidates = getattr(tts_response, "candidates", None)
        if not candidates:
            pf = getattr(tts_response, "prompt_feedback", None)
            if pf:
                raise ValueError(
                    f"Giriş metni güvenlik filtresine takıldı "
                    f"(Block Reason: {getattr(pf, 'block_reason', 'Bilinmiyor')})"
                )
            raise ValueError("TTS candidates bulunamadı (boş response)")

        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason and str(finish_reason) not in [
            "STOP", "FinishReason.STOP", "1", "stop"
        ]:
            safety_ratings = getattr(candidate, "safety_ratings", [])
            raise ValueError(
                f"Model üretimi durdurdu (Finish Reason: {finish_reason}). "
                f"Safety: {safety_ratings}"
            )

        content = getattr(candidate, "content", None)
        if not content:
            raise ValueError(f"TTS content boş (Finish Reason: {finish_reason})")

        parts = getattr(content, "parts", None)
        if not parts:
            raise ValueError("TTS parts bulunamadı")

        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data:
                data = getattr(inline_data, "data", None)
                if data:
                    if isinstance(data, str):
                        return base64.b64decode(data)
                    return data

        raise ValueError("TTS audio verisi boş (inline_data bulunamadı)")

    def ses_uret(
        self,
        metin: str,
        ses_adi: str,
        cikti_dosyasi: str,
        log_ekle,
        hiz_carpani: float = 1.0,
    ) -> Tuple[bool, Optional[str]]:
        # TTS için güvenlik ayarları; mevcut davranış korunur.
        try:
            safety_settings = [
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.BLOCK_NONE,
                ),
            ]
        except Exception:
            safety_settings = None

        config_kwargs = dict(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=ses_adi
                    )
                )
            ),
        )
        if safety_settings:
            config_kwargs["safety_settings"] = safety_settings

        config = types.GenerateContentConfig(**config_kwargs)
        tts_girdisi = self._tts_performans_promptu_olustur(metin, ses_adi)

        try:
            tts_response, info = self._make_request(
                SES_MODELLERI,
                tts_girdisi,
                config,
                log_ekle,
                stop_on_quota=False,
            )
        except Exception as e:
            log_ekle(f"❌ Hiçbir ses modeli başarılı olamadı: {str(e)[:180]}")
            return False, None

        # 3.1 Flash TTS çok nadiren audio yerine text token döndürebiliyor.
        # Böyle bir durumda 2.5 TTS'ye tek seferlik kontrollü fallback yap.
        try:
            audio_data = self._tts_response_audio_bytes(tts_response)
        except Exception as ilk_tts_hata:
            log_ekle(
                f"⚠️ TTS ilk modelinden geçerli audio alınamadı: "
                f"{str(ilk_tts_hata)[:180]}"
            )

            if len(SES_MODELLERI) < 2:
                return False, None

            try:
                fallback_model = SES_MODELLERI[1]
                log_ekle(
                    f"🔁 TTS fallback: {fallback_model} ile aynı performans "
                    f"promptu bir kez yeniden üretiliyor..."
                )
                fallback_response, fallback_info = self._make_request(
                    [fallback_model],
                    tts_girdisi,
                    config,
                    log_ekle,
                    stop_on_quota=False,
                )
                audio_data = self._tts_response_audio_bytes(fallback_response)
                info = fallback_info
            except Exception as ikinci_tts_hata:
                log_ekle(
                    f"❌ TTS fallback da başarısız: "
                    f"{str(ikinci_tts_hata)[:180]}"
                )
                return False, None

        try:
            if abs(hiz_carpani - 1.0) < 0.001:
                wav_yaz(cikti_dosyasi, audio_data)
                return True, info

            gecici_ham_dosya = gecici_dosya_yolu("ses_ham", "wav")
            try:
                wav_yaz(gecici_ham_dosya, audio_data)
                log_ekle(
                    f"🎚️ Ses {hiz_carpani}x hızlandırılıyor "
                    f"(ffmpeg atempo, pitch korunur)..."
                )
                basarili = sesi_hizlandir(
                    gecici_ham_dosya, cikti_dosyasi, hiz_carpani, log_ekle
                )
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

    def video_analiz_et(
        self,
        video_bytes: bytes,
        mime_type: str,
        system_prompt: str,
        response_schema: dict,
        log_ekle,
        model_listesi=None,
        arama_kullan: bool = False,
    ) -> Tuple[dict, str]:
        """
        FORENSIC VIDEO ANALYSIS çağrısı.

        Eski davranıştan farkı: artık serbest metin değil, response_schema'ya
        uygun YAPILANDIRILMIŞ JSON döner (VIDEO_ANALYSIS_SCHEMA). Prompt ve
        şema dışarıdan (pipeline.py → prompts.py / schemas.py) verilir; bu
        metot sadece video + prompt + şemayı SmartRouter mekanizmasıyla
        (key rotasyonu, model rotasyonu, ban/cooldown) çalıştırır.

        Forensic aşaması varsayılan olarak arama YAPMAZ (arama_kullan=False);
        araştırma görevi Research/Fact Lock aşamasına aittir.
        """
        if model_listesi is None:
            model_listesi = VIDEO_ANALIZ_MODELLERI

        video_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)

        config_parametreleri = dict(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        if arama_kullan and model_listesi and model_arama_destekliyor_mu(model_listesi[0]):
            config_parametreleri["tools"] = [types.Tool(google_search=types.GoogleSearch())]
            log_ekle(f" 🔎 {model_listesi[0]} için video analizinde arama aktif")
        config = types.GenerateContentConfig(**config_parametreleri)

        response, info = self._make_request(model_listesi, [video_part], config, log_ekle)
        return guvenli_json_yukle(getattr(response, "text", "")), info
