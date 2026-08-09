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
    API_KEYS, METIN_MODELLERI, SES_MODELLERI, VIDEO_ANALIZ_MODELLERI,
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
        """Gemini hatasını mümkün olduğunca doğru sınıflandırır.

        429 tek başına "60 saniye bekle" anlamına gelmez. Google'ın güncel
        dokümantasyonunda 429; RPM/TPM/RPD veya harcamaya dayalı limitler
        nedeniyle oluşabilir. Özellikle "You exceeded your current quota"
        ifadesi günlük/plan kotası gibi daha kalıcı bir kotaya işaret edebilir.
        """
        text = (hata_metni or "").lower()

        if "limit: 0" in text or 'limit": 0' in text:
            return "free_tier_yok", COOLDOWN_FREE_TIER_YOK

        # Kalıcı/plan kotası: retryDelay olsa bile bunu sıradan 60 sn rate-limit
        # gibi ele alma. Key rotasyonu da proje bazlı limitleri aşmaz.
        quota_markers = (
            "quota_exceeded",
            "you exceeded your current quota",
            "exceeded your current quota",
            "daily quota",
            "quota limit",
        )
        if any(marker in text for marker in quota_markers):
            return "quota_exceeded", 0

        # Geçici 429 / rate-limit. retryDelay varsa onu kullanacağız.
        if "rate_limit_exceeded" in text or "too many requests" in text:
            return "rate_limit", 0
        if "429" in text or "resource_exhausted" in text:
            return "quota", 0

        if "503" in text or "unavailable" in text:
            return "combo", COOLDOWN_SUNUCU
        if "404" in text or "not_found" in text or "model_not_found" in text:
            return "model", COOLDOWN_BULUNAMADI
        if "403" in text or "permission_denied" in text:
            return "key", COOLDOWN_DIGER
        return "combo", COOLDOWN_DIGER

    def _handle_hata(self, mail: str, model: str, hata_metni: str, log_ekle) -> str:
        scope, cooldown = self._parse_hata(hata_metni)

        if scope == "free_tier_yok":
            log_ekle(f" 🚫 {model} free tier'da YOK (limit: 0) → model 7 gün devre dışı")
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"

        if scope == "quota_exceeded":
            # Bu, basit RPM limitinden farklıdır. Key'ler aynı projeye bağlıysa
            # üç ayrı key kullanmak aynı proje kotasını üçe katlamaz.
            # Yine de mevcut router mantığını koruyarak combo'yu uzun cooldown'a
            # alıyor ve sonraki model/key kombinasyonlarına geçiyoruz.
            long_cooldown = max(QUOTA_RETRY_DEFAULT, 30 * 60)
            self._ban(mail, model, long_cooldown, "combo")
            log_ekle(
                f" ⛔ {mail} + {model}: kalıcı/plan kotası aşıldı → "
                f"{long_cooldown // 60} dk cooldown. Key rotasyonu kotayı artırmaz."
            )
            time.sleep(IP_BAN_KORUMA)
            return "devam"

        if scope == "rate_limit":
            delay = self._retry_delay_cikar(hata_metni)
            ban_sure = delay if delay > 0 else QUOTA_RETRY_DEFAULT
            self._ban(mail, model, ban_sure, "combo")
            log_ekle(f" ⏳ {mail} + {model}: geçici rate-limit → {ban_sure}sn cooldown")
            time.sleep(IP_BAN_KORUMA)
            return "devam"

        if scope == "quota":
            delay = self._retry_delay_cikar(hata_metni)
            ban_sure = delay if delay > 0 else QUOTA_RETRY_DEFAULT
            self._ban(mail, model, ban_sure, "combo")
            log_ekle(f" ⏳ {mail} + {model}: geçici kota/rate-limit → {ban_sure}sn cooldown")
            time.sleep(IP_BAN_KORUMA)
            return "devam"

        ban_sure = f"{cooldown // 60} dk" if cooldown < 3600 else f"{cooldown // 3600} saat"
        if scope == "model":
            log_ekle(f" ❌ {model} MODEL bazlı hata → TÜM key'ler için {ban_sure} devre dışı")
            self._ban(mail, model, cooldown, "model")
            time.sleep(IP_BAN_KORUMA)
            return "break_model"
        else:
            log_ekle(f" ⚠️ {mail} hatası → {model} ile {ban_sure} cooldown, diğer key deneniyor")
            self._ban(mail, model, cooldown, scope)
            time.sleep(IP_BAN_KORUMA)
            return "devam"

    def _make_request(
        self,
        model_listesi: List[str],
        contents: Any,
        config: types.GenerateContentConfig,
        log_ekle,
        ignore_bans: bool = False,
    ) -> Tuple[Any, str]:
        """Model + key rotasyonu.

        ignore_bans yalnızca kontrollü fallback için kullanılır. Örneğin
        Google Search grounding kotası bittiğinde aynı model, Search kapalı
        olarak bir kez daha denenebilir; aksi halde Search denemesinde oluşan
        combo cooldown'u gerçek fallback çağrısını da engeller.
        """
        son_hata = None
        herhangi_bir_kombinasyon = False

        for model_adi in model_listesi:
            log_ekle(f"🧠 Model deneniyor: {model_adi}")
            model_denendi = False

            for mail, api_key in API_KEYS.items():
                if not ignore_bans and self._is_banned(mail, model_adi):
                    log_ekle(f" ⏸️ {mail} + {model_adi} cooldown'da, atlanıyor")
                    continue

                model_denendi = True
                herhangi_bir_kombinasyon = True
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
                    if aksiyon == "break_model":
                        break

            if not model_denendi:
                log_ekle(f" ⏸️ {model_adi} tüm key'ler için cooldown'da, atlanıyor")

        if son_hata:
            raise son_hata
        if not herhangi_bir_kombinasyon:
            raise Exception("Tüm model+key kombinasyonları cooldown'da.")
        raise Exception("Tüm model+key kombinasyonları başarısız.")

    def _arama_cooldown_aktif_mi(self) -> bool:
        """Session seviyesinde Search grounding cooldown kontrolü."""
        until = st.session_state.get("gemini_search_disabled_until", 0.0)
        if time.time() < until:
            return True
        if until:
            st.session_state.pop("gemini_search_disabled_until", None)
        return False

    def _arama_cooldown_ayarla(self, saniye: int = 30 * 60) -> None:
        st.session_state.gemini_search_disabled_until = time.time() + saniye

    def metin_uret(
        self,
        icerik: Any,
        system_prompt: str,
        response_schema: dict,
        log_ekle,
        model_listesi=None,
        arama_kullan: bool = True,
    ) -> Tuple[dict, str]:
        """Genel metin/JSON üretim motoru.

        Research/Fact Lock için Google Search grounding önceliklidir. Search
        kotası/rate-limit yüzünden çağrı başarısız olursa pipeline'ın tamamını
        çökertmek yerine Search'süz kontrollü bir fallback denenir. Böylece
        normal metin üretimi çalışmaya devam eder; log da bu fallback'in
        gerçekleştiğini açıkça bildirir.
        """
        if model_listesi is None:
            model_listesi = METIN_MODELLERI
        if not model_listesi:
            raise ValueError("Metin model listesi boş.")

        search_aktif = bool(arama_kullan and model_arama_destekliyor_mu(model_listesi[0]))
        if search_aktif and self._arama_cooldown_aktif_mi():
            search_aktif = False
            log_ekle(" ⚠️ Google Search grounding geçici olarak cooldown'da → Search'süz kontrollü fallback kullanılıyor")

        def _config_olustur(search_kullan: bool):
            kwargs = dict(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
            )
            if search_kullan:
                kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
            return types.GenerateContentConfig(**kwargs)

        if search_aktif:
            log_ekle(f" 🔎 {model_listesi[0]} için güncel bilgi araması aktif")

        config = _config_olustur(search_aktif)
        try:
            response, info = self._make_request(model_listesi, icerik, config, log_ekle)
            return guvenli_json_yukle(getattr(response, "text", "")), info
        except Exception as ilk_hata:
            if not search_aktif:
                raise

            hata_metni = str(ilk_hata)
            # Search grounding kotası / 429 kaynaklı olma ihtimali varsa
            # Search'ü geçici kapatıp aynı üretimi bir kez Search'süz deniyoruz.
            parse_scope, _ = self._parse_hata(hata_metni)
            search_fallback_gerekli = parse_scope in {"quota_exceeded", "quota", "rate_limit"}

            if not search_fallback_gerekli:
                raise

            self._arama_cooldown_ayarla(30 * 60)
            log_ekle(
                " 🔁 Google Search çağrısı kota/rate-limit nedeniyle başarısız oldu. "
                "Search 30 dk geçici kapatılıyor; aynı Fact Lock isteği Search'süz bir kez deneniyor."
            )

            fallback_system_prompt = (
                system_prompt
                + "\n\n[SEARCH FALLBACK]\n"
                "Google Search bu çağrıda kullanılamıyor. YALNIZCA modelin güvenilir biçimde bildiği bilgileri kullan. "
                "Güncel olduğu doğrulanamayan ayrıntıları kesin gerçek gibi yazma. Emin olmadığın alanları BILINMIYOR/UNKNOWN olarak işaretle. "
                "Kullanıcıdan gelen görsel gözlemlerini gerçek kaynak bilgisi gibi genişletme."
            )
            fallback_config = _config_olustur(False)
            fallback_config = types.GenerateContentConfig(
                system_instruction=fallback_system_prompt,
                response_mime_type="application/json",
                response_schema=response_schema,
            )

            try:
                response, info = self._make_request(
                    model_listesi,
                    icerik,
                    fallback_config,
                    log_ekle,
                    ignore_bans=True,
                )
                log_ekle(" ⚠️ Fact Lock Search'süz fallback ile tamamlandı. Güncel doğrulama yapılamayan alanlar işaretlendi.")
                return guvenli_json_yukle(getattr(response, "text", "")), info
            except Exception as fallback_hata:
                # İlk hatayı kaybetme; asıl kök neden çoğu zaman daha açıklayıcıdır.
                raise RuntimeError(
                    "Google Search grounding ve Search'süz Gemini fallback'i başarısız oldu. "
                    f"İlk hata: {hata_metni[:500]} | Fallback: {str(fallback_hata)[:500]}"
                ) from fallback_hata

    def ses_uret(self, metin: str, ses_adi: str, cikti_dosyasi: str, log_ekle, hiz_carpani: float = 1.0) -> Tuple[bool, Optional[str]]:
        # 🔥 GÜVENLİK FİLTRELERİNİ KAPAT (TTS metinleri yanlışlıkla bloklanmasın diye)
        try:
            safety_settings = [
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
                types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
            ]
        except Exception:
            safety_settings = None # Eski SDK versiyonları için fallback

        config_kwargs = dict(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=ses_adi)
                )
            ),
        )
        if safety_settings:
            config_kwargs["safety_settings"] = safety_settings

        config = types.GenerateContentConfig(**config_kwargs)
        
        try:
            tts_response, info = self._make_request(SES_MODELLERI, metin, config, log_ekle)
        except Exception as e:
            log_ekle(f"❌ Hiçbir ses modeli başarılı olamadı: {str(e)[:100]}")
            return False, None

        try:
            candidates = getattr(tts_response, "candidates", None)
            
            # 1. Prompt Feedback Kontrolü (Giriş metni bloklanmış mı?)
            if not candidates:
                pf = getattr(tts_response, "prompt_feedback", None)
                if pf:
                    block_reason = getattr(pf, "block_reason", "Bilinmiyor")
                    raise ValueError(f"Giriş metni güvenlik filtresine takıldı (Block Reason: {block_reason})")
                raise ValueError("TTS candidates bulunamadı (Boş response)")

            candidate = candidates[0]
            
            # 2. Finish Reason Kontrolü (Çıkış bloklanmış mı?)
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason and str(finish_reason) not in ["STOP", "FinishReason.STOP", "1", "stop"]:
                safety_ratings = getattr(candidate, "safety_ratings", [])
                raise ValueError(f"Model üretimi durdurdu (Finish Reason: {finish_reason}). Safety: {safety_ratings}")

            # 3. Content ve Parts Kontrolü
            content = getattr(candidate, "content", None)
            if not content:
                raise ValueError(f"TTS content boş (Finish Reason: {finish_reason})")

            parts = getattr(content, "parts", None)
            if not parts:
                raise ValueError("TTS parts bulunamadı (Content var ama parts boş)")

            # 4. Audio Data Çıkarma
            audio_data = None
            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data:
                    data = getattr(inline_data, "data", None)
                    if data:
                        audio_data = data
                        break
            
            if not audio_data:
                raise ValueError("TTS audio verisi boş (parts içinde inline_data yok)")
                
            if isinstance(audio_data, str):
                audio_data = base64.b64decode(audio_data)

            if abs(hiz_carpani - 1.0) < 0.001:
                wav_yaz(cikti_dosyasi, audio_data)
                return True, info

            gecici_ham_dosya = gecici_dosya_yolu("ses_ham", "wav")
            try:
                wav_yaz(gecici_ham_dosya, audio_data)
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
        if arama_kullan and model_arama_destekliyor_mu(model_listesi[0]):
            config_parametreleri["tools"] = [types.Tool(google_search=types.GoogleSearch())]
            log_ekle(f" 🔎 {model_listesi[0]} için video analizinde arama aktif")
        config = types.GenerateContentConfig(**config_parametreleri)

        response, info = self._make_request(model_listesi, [video_part], config, log_ekle)
        return guvenli_json_yukle(getattr(response, "text", "")), info
