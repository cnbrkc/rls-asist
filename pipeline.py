"""
pipeline.py — Ultimate Content Engine orkestratörü.

VIDEO
 → 1) FORENSIC VIDEO ANALYSIS   (sadece gözlem, yaratıcı karar yok)
 → 2) RESEARCH / FACT LOCK       (dinamik arama, tek doğruluk katmanı)
 → 3) EDITORIAL BRAIN            (hangi hikâye anlatılacak)
 → 4) REELS CREATIVE             (cover + hook + voiceover birlikte)
 → 5) CAPTION + HASHTAGS         (ekstra değer, transkript değil)
 → 6) THREADS                    (caption'dan bağımsız, community trigger)
 → 7) FINAL QA                   (hakem; gerekirse sadece ilgili aşamayı yeniden üretir)
 → 8) TTS
 → 9) VIDEO + AUDIO RENDER

ui.py bu dosyayı SADECE çağırır; üretim mantığının tamamı burada.
Mevcut UI (ui_results.py) ile geriye dönük uyumlu bir sonuç sözlüğü döner:
seslendirme_metni, reels_aciklamasi, reels_hashtagleri, kapak_basliklari,
threads_aciklamasi, ses_basarili, ses_dosyasi, final_video, temp_input_video.
"""
import os

from config import KELIME_HIZI_ORANI, SES_HIZ_CARPANI, PIPELINE_ADIMLARI
from schemas import (
    VIDEO_ANALYSIS_SCHEMA, FACT_LOCK_SCHEMA, EDITORIAL_SCHEMA,
    REELS_CREATIVE_SCHEMA, CAPTION_SCHEMA, THREADS_SCHEMA, QA_SCHEMA,
)
from prompts import (
    forensic_analiz_promptunu_olustur, research_promptunu_olustur,
    editorial_promptunu_olustur, reels_creative_promptunu_olustur,
    caption_promptunu_olustur, threads_promptunu_olustur, qa_promptunu_olustur,
    durumu_metne_donustur, girdi_birlestir,
)
from media import (
    gecici_ses_yolu, gecici_dosya_yolu, temp_dosya_temizle,
    video_ve_sesi_birlestir, _ses_suresini_al,
)

TOPLAM_ADIM = len(PIPELINE_ADIMLARI)  # 9


def _ilerleme(ilerlemeyi_guncelle, adim_no: int, ozel_mesaj: str = None):
    if ilerlemeyi_guncelle is None:
        return
    mesaj = ozel_mesaj or PIPELINE_ADIMLARI[adim_no - 1]
    ilerlemeyi_guncelle(adim_no, TOPLAM_ADIM, mesaj)


def _secilen_hook_getir(reels_state: dict) -> dict:
    hook_families = reels_state.get("hook_families") or []
    if not hook_families:
        return {}
    index = reels_state.get("secilen_aile_index", 0)
    if not isinstance(index, int) or not (0 <= index < len(hook_families)):
        index = 0
    return hook_families[index]


# ============================================================
# AŞAMA FONKSİYONLARI — her biri TEK bir editoryal role karşılık gelir.
# Her fonksiyon SADECE ihtiyacı olan state parçasını alır (token optimizasyonu).
# ============================================================

def _forensic_analiz_calistir(router, video_bytes, mime_type, analiz_notlari, sure_saniye, log_ekle):
    ek_notlar_bolumu = ""
    if analiz_notlari and analiz_notlari.strip():
        ek_notlar_bolumu = (
            "\nÖNEMLİ: Kullanıcı videoyu analiz ettirirken şu VİDEO ANALİZ NOTLARINI iletti.\n"
            "--- VİDEO ANALİZ NOTLARI ---\n"
            f"{analiz_notlari.strip()}\n"
            "-------------------------------\n"
        )
    system_prompt = forensic_analiz_promptunu_olustur(ek_notlar_bolumu, sure_saniye)
    return router.video_analiz_et(video_bytes, mime_type, system_prompt, VIDEO_ANALYSIS_SCHEMA, log_ekle)


def _research_calistir(router, video_state, log_ekle):
    system_prompt = research_promptunu_olustur()
    icerik = girdi_birlestir(
        durumu_metne_donustur("VIDEO IDENTITY", video_state.get("video_identity", {})),
        durumu_metne_donustur("OBSERVED FACTS", video_state.get("observed_facts", [])),
        durumu_metne_donustur("UNKNOWNS", video_state.get("unknowns", [])),
        durumu_metne_donustur("POSSIBLE INFERENCE", video_state.get("possible_inference", [])),
        durumu_metne_donustur("ARAŞTIRMA İHTİYAÇLARI", video_state.get("viral_arastirma_ihtiyaclari", [])),
    )
    return router.metin_uret(icerik, system_prompt, FACT_LOCK_SCHEMA, log_ekle, arama_kullan=True)


def _editorial_calistir(router, video_state, fact_state, metin_uretim_notlari, log_ekle):
    system_prompt = editorial_promptunu_olustur()
    notlar = metin_uretim_notlari.strip() if metin_uretim_notlari and metin_uretim_notlari.strip() else "Ek üretim notu yok."
    icerik = girdi_birlestir(
        durumu_metne_donustur("VIDEO IDENTITY", video_state.get("video_identity", {})),
        durumu_metne_donustur("OBSERVED FACTS", video_state.get("observed_facts", [])),
        durumu_metne_donustur("VISUAL OPPORTUNITIES", video_state.get("visual_opportunities", [])),
        durumu_metne_donustur("FACT LOCK", fact_state),
        durumu_metne_donustur("KULLANICI ÜRETİM NOTLARI", notlar),
    )
    return router.metin_uret(icerik, system_prompt, EDITORIAL_SCHEMA, log_ekle, arama_kullan=False)


def _reels_creative_calistir(
    router, editorial_state, fact_state, video_state, metin_uretim_notlari,
    sure_saniye, icerik_tonu, log_ekle, kelime_hizi_orani=None,
):
    system_prompt = reels_creative_promptunu_olustur(sure_saniye, icerik_tonu, kelime_hizi_orani)
    notlar = metin_uretim_notlari.strip() if metin_uretim_notlari and metin_uretim_notlari.strip() else "Ek üretim notu yok."
    icerik = girdi_birlestir(
        durumu_metne_donustur("EDITORIAL BRIEF", editorial_state),
        durumu_metne_donustur("FACT LOCK", fact_state),
        durumu_metne_donustur("GÖRSEL ZAMAN ÇİZELGESİ", video_state.get("timeline", [])),
        durumu_metne_donustur("KULLANICI ÜRETİM NOTLARI", notlar),
    )
    return router.metin_uret(icerik, system_prompt, REELS_CREATIVE_SCHEMA, log_ekle, arama_kullan=False)


def _caption_calistir(router, reels_state, fact_state, editorial_state, video_state, log_ekle):
    system_prompt = caption_promptunu_olustur()
    icerik = girdi_birlestir(
        durumu_metne_donustur("SEÇİLEN SESLENDİRME", reels_state.get("seslendirme_metni", "")),
        durumu_metne_donustur("SEÇİLEN HOOK/KAPAK", _secilen_hook_getir(reels_state)),
        durumu_metne_donustur("VIDEO IDENTITY", video_state.get("video_identity", {})),
        durumu_metne_donustur("FORENSIC TIMELINE", video_state.get("timeline", [])),
        durumu_metne_donustur("FACT LOCK", fact_state),
        durumu_metne_donustur("EDITORIAL BRIEF", editorial_state),
        durumu_metne_donustur("SEÇİLEN HOOK/KAPAK", _secilen_hook_getir(reels_state)),
    )
    return router.metin_uret(icerik, system_prompt, CAPTION_SCHEMA, log_ekle, arama_kullan=False)


def _threads_calistir(router, video_state, fact_state, editorial_state, log_ekle):
    system_prompt = threads_promptunu_olustur()
    icerik = girdi_birlestir(
        durumu_metne_donustur("VIDEO IDENTITY", video_state.get("video_identity", {})),
        durumu_metne_donustur("FACT LOCK", fact_state),
        durumu_metne_donustur("EDITORIAL BRIEF", editorial_state),
    )
    return router.metin_uret(icerik, system_prompt, THREADS_SCHEMA, log_ekle, arama_kullan=False)


def _qa_calistir(router, video_state, fact_state, editorial_state, reels_state, caption_state, threads_state, sure_saniye, log_ekle):
    system_prompt = qa_promptunu_olustur()
    icerik = girdi_birlestir(
        durumu_metne_donustur("VIDEO IDENTITY", video_state.get("video_identity", {})),
        durumu_metne_donustur("FORENSIC TIMELINE", video_state.get("timeline", [])),
        durumu_metne_donustur("FACT LOCK", fact_state),
        durumu_metne_donustur("EDITORIAL BRIEF", editorial_state),
        durumu_metne_donustur("SEÇİLEN HOOK/KAPAK", _secilen_hook_getir(reels_state)),
        durumu_metne_donustur("SESLENDİRME METNİ", reels_state.get("seslendirme_metni", "")),
        durumu_metne_donustur("KAPAK BAŞLIKLARI", reels_state.get("kapak_basliklari", [])),
        durumu_metne_donustur("REELS AÇIKLAMASI", caption_state.get("reels_aciklamasi", "")),
        durumu_metne_donustur("HASHTAGLER", caption_state.get("reels_hashtagleri", [])),
        durumu_metne_donustur("THREADS AÇIKLAMASI", threads_state.get("threads_aciklamasi", "")),
        durumu_metne_donustur("HEDEF SÜRE (sn)", sure_saniye),
    )
    try:
        return router.metin_uret(icerik, system_prompt, QA_SCHEMA, log_ekle, arama_kullan=False)
    except Exception as qa_hata:
        log_ekle(f"⚠️ QA çağrısı başarısız oldu, QA atlanıyor: {str(qa_hata)[:150]}")
        return {"overall": "ATLANDI", "regeneration_targets": []}, "atlandi"


# ============================================================
# ANA ORKESTRATÖR
# ============================================================

def pipeline_calistir(
    router,
    video_bytes: bytes,
    mime_type: str,
    temp_input_video: str,
    video_analiz_notlari: str,
    metin_uretim_notlari: str,
    sure_saniye: int,
    icerik_tonu: str,
    secilen_ses_ingilizce: str,
    log_ekle,
    ilerlemeyi_guncelle=None,
) -> dict:
    pipeline_state = {}

    # ---- 1) FORENSIC VIDEO ANALYSIS ----
    _ilerleme(ilerlemeyi_guncelle, 1)
    log_ekle("🎥 Video analiz ediliyor (Forensic)...")
    video_state, _ = _forensic_analiz_calistir(
        router, video_bytes, mime_type, video_analiz_notlari, sure_saniye, log_ekle
    )
    pipeline_state["video_state"] = video_state
    kimlik = video_state.get("video_identity", {}) or {}
    log_ekle(f"🔎 Tespit edilen: {kimlik.get('brand', '?')} {kimlik.get('exact_model', 'UNKNOWN')} (güven: {kimlik.get('confidence', '?')})")

    # ---- 2) RESEARCH / FACT LOCK ----
    _ilerleme(ilerlemeyi_guncelle, 2)
    log_ekle("🔎 Gerçekler doğrulanıyor (Research / Fact Lock)...")
    fact_state, _ = _research_calistir(router, video_state, log_ekle)
    pipeline_state["fact_state"] = fact_state
    log_ekle(f"🔒 Fact Lock tamam. Türkiye satış durumu: {fact_state.get('turkiye_satis_durumu', 'BILINMIYOR')}")

    # ---- 3) EDITORIAL BRAIN ----
    _ilerleme(ilerlemeyi_guncelle, 3)
    log_ekle("🧠 Hikâye seçiliyor (Editorial Brain)...")
    editorial_state, _ = _editorial_calistir(router, video_state, fact_state, metin_uretim_notlari, log_ekle)
    pipeline_state["editorial_state"] = editorial_state
    log_ekle(f"📖 Seçilen hikâye: {editorial_state.get('core_story', '?')}")

    # ---- 4) REELS CREATIVE (cover + hook + voiceover) ----
    _ilerleme(ilerlemeyi_guncelle, 4)
    log_ekle("🎙️ Reels hazırlanıyor (Cover + Hook + Voiceover)...")
    reels_state, model_reels = _reels_creative_calistir(
        router, editorial_state, fact_state, video_state, metin_uretim_notlari,
        sure_saniye, icerik_tonu, log_ekle,
    )
    pipeline_state["reels_state"] = reels_state

    # ---- 5) CAPTION + HASHTAGS ----
    _ilerleme(ilerlemeyi_guncelle, 5)
    log_ekle("📝 Caption + hashtag hazırlanıyor...")
    try:
        caption_state, model_caption = _caption_calistir(router, reels_state, fact_state, editorial_state, video_state, log_ekle)
    except Exception as caption_hata:
        log_ekle(f"⚠️ Caption üretilemedi: {str(caption_hata)[:150]}")
        caption_state, model_caption = {"reels_aciklamasi": "", "reels_hashtagleri": []}, "hata"
    pipeline_state["caption_state"] = caption_state

    # ---- 6) THREADS ----
    _ilerleme(ilerlemeyi_guncelle, 6)
    log_ekle("🧵 Threads hazırlanıyor...")
    try:
        threads_state, model_threads = _threads_calistir(router, video_state, fact_state, editorial_state, log_ekle)
    except Exception as threads_hata:
        log_ekle(f"⚠️ Threads üretilemedi, 'üretilemedi' olarak işaretleniyor: {str(threads_hata)[:150]}")
        threads_state, model_threads = {"threads_aciklamasi": ""}, "hata"
    pipeline_state["threads_state"] = threads_state

    # ---- 7) FINAL QA (+ gerekirse SADECE ilgili aşamanın kısmi yeniden üretimi) ----
    _ilerleme(ilerlemeyi_guncelle, 7)
    log_ekle("🔍 Son kalite kontrol (QA)...")
    qa_state, _ = _qa_calistir(router, video_state, fact_state, editorial_state, reels_state, caption_state, threads_state, sure_saniye, log_ekle)
    pipeline_state["qa_state_ilk"] = qa_state

    hedefler = set(qa_state.get("regeneration_targets", []) or [])
    if hedefler:
        log_ekle(f"⚠️ QA hataları bulundu: {', '.join(hedefler)} → sadece ilgili aşama(lar) yeniden üretiliyor.")

        if "FACT_FAIL" in hedefler:
            # Fact Lock omurga olduğu için ondan sonraki her şey (editorial → reels → caption → threads)
            # kademeli olarak yeniden üretilir. Forensic analiz TEKRARLANMAZ (video değişmedi).
            log_ekle("🔁 FACT_FAIL → Fact Lock'a dönülüyor, bağımlı aşamalar yeniden üretiliyor.")
            try:
                fact_state, _ = _research_calistir(router, video_state, log_ekle)
                pipeline_state["fact_state"] = fact_state
                editorial_state, _ = _editorial_calistir(router, video_state, fact_state, metin_uretim_notlari, log_ekle)
                pipeline_state["editorial_state"] = editorial_state
                reels_state, model_reels = _reels_creative_calistir(
                    router, editorial_state, fact_state, video_state, metin_uretim_notlari,
                    sure_saniye, icerik_tonu, log_ekle,
                )
                pipeline_state["reels_state"] = reels_state
                caption_state, model_caption = _caption_calistir(router, reels_state, fact_state, editorial_state, video_state, log_ekle)
                pipeline_state["caption_state"] = caption_state
                threads_state, model_threads = _threads_calistir(router, video_state, fact_state, editorial_state, log_ekle)
                pipeline_state["threads_state"] = threads_state
            except Exception as fact_fail_hata:
                log_ekle(f"⚠️ FACT_FAIL sonrası yeniden üretim başarısız: {str(fact_fail_hata)[:150]}")
        else:
            if "VOICEOVER_FAIL" in hedefler or "COVER_FAIL" in hedefler:
                # Cover + hook + voiceover AYNI çağrıda üretildiği için ikisi de bu aşamayı tetikler.
                log_ekle("🔁 Reels Creative (cover + hook + voiceover) yeniden üretiliyor.")
                try:
                    reels_state, model_reels = _reels_creative_calistir(
                        router, editorial_state, fact_state, video_state, metin_uretim_notlari,
                        sure_saniye, icerik_tonu, log_ekle,
                    )
                    pipeline_state["reels_state"] = reels_state
                    # Caption, seçilen hook ve voiceover'a bağlıdır; Reels değiştiyse senkronize et.
                    try:
                        caption_state, model_caption = _caption_calistir(
                            router, reels_state, fact_state, editorial_state, video_state, log_ekle
                        )
                        pipeline_state["caption_state"] = caption_state
                        log_ekle("🔁 Reels değişti → Caption + hashtag senkronize edildi.")
                    except Exception as caption_hata:
                        log_ekle(f"⚠️ Reels sonrası caption yenilenemedi: {str(caption_hata)[:150]}")
                except Exception as reels_hata:
                    log_ekle(f"⚠️ Reels Creative yeniden üretimi başarısız: {str(reels_hata)[:150]}")

            if "CAPTION_FAIL" in hedefler:
                log_ekle("🔁 Caption + hashtag yeniden üretiliyor.")
                try:
                    caption_state, model_caption = _caption_calistir(router, reels_state, fact_state, editorial_state, video_state, log_ekle)
                    pipeline_state["caption_state"] = caption_state
                except Exception as caption_hata:
                    log_ekle(f"⚠️ Caption yeniden üretimi başarısız: {str(caption_hata)[:150]}")

            if "THREADS_FAIL" in hedefler:
                log_ekle("🔁 Threads yeniden üretiliyor.")
                try:
                    threads_state, model_threads = _threads_calistir(router, video_state, fact_state, editorial_state, log_ekle)
                    pipeline_state["threads_state"] = threads_state
                except Exception as threads_hata:
                    log_ekle(f"⚠️ Threads yeniden üretimi başarısız: {str(threads_hata)[:150]}")

        # Maliyeti kontrol altında tutmak için TEK bir doğrulama turu daha yapılır (sınırsız döngü yok).
        qa_state, _ = _qa_calistir(router, video_state, fact_state, editorial_state, reels_state, caption_state, threads_state, sure_saniye, log_ekle)
        kalan_hedefler = set(qa_state.get("regeneration_targets", []) or [])
        if kalan_hedefler:
            log_ekle(f"⚠️ Yeniden üretimden sonra hâlâ QA uyarısı var: {', '.join(kalan_hedefler)} (içerik yine de kullanılabilir, gözden geçirmen önerilir).")
        else:
            log_ekle("✅ Yeniden üretim sonrası QA temiz.")
    else:
        log_ekle("✅ QA ilk turda PASS.")

    pipeline_state["qa_state_final"] = qa_state

    # ---- 8) TTS ----
    tts_sonrasi_qa_gerekli = False
    _ilerleme(ilerlemeyi_guncelle, 8)
    log_ekle("🎧 Ses üretiliyor...")
    seslendirme_metni = reels_state.get("seslendirme_metni", "")
    ses_dosyasi = gecici_ses_yolu()
    ses_basarili, kullanilan_ses_modeli = router.ses_uret(
        seslendirme_metni, secilen_ses_ingilizce, ses_dosyasi, log_ekle, hiz_carpani=SES_HIZ_CARPANI
    )
    # İlk başarılı ses dosyasını fallback başarısız olursa koru.
    ilk_ses_dosyasi = ses_dosyasi if (ses_basarili and os.path.exists(ses_dosyasi)) else None
    ilk_ses_modeli = kullanilan_ses_modeli

    # ---- SES SÜRESİ KONTROLÜ + FALLBACK ----
    # Fallback SADECE Reels Creative (voiceover) aşamasını tekrar çalıştırır;
    # eski tek-büyük-prompt üretimine ASLA dönülmez.
    if ses_basarili and os.path.exists(ses_dosyasi):
        uretilen_ses_sure = _ses_suresini_al(ses_dosyasi)
        log_ekle(f"🎧 Üretilen ses süresi: {uretilen_ses_sure:.2f}s | Video hedef: {sure_saniye}s")

        if uretilen_ses_sure < (sure_saniye * 0.80):
            log_ekle("⚠️ Ses çok kısa kaldı. Reels Creative kelime hedefi artırılıp SADECE voiceover yeniden üretiliyor...")
            fallback_kelime_orani = KELIME_HIZI_ORANI * 1.35
            try:
                eski_reels_state = reels_state
                yeni_reels_state = _reels_creative_calistir(
                    router, editorial_state, fact_state, video_state, metin_uretim_notlari,
                    sure_saniye, icerik_tonu, log_ekle, kelime_hizi_orani=fallback_kelime_orani,
                )[0]
                yeni_seslendirme_metni = yeni_reels_state.get(
                    "seslendirme_metni", seslendirme_metni
                )

                eski_ses = ses_dosyasi
                ses_dosyasi = gecici_ses_yolu()
                fallback_basarili, fallback_modeli = router.ses_uret(
                    yeni_seslendirme_metni, secilen_ses_ingilizce, ses_dosyasi,
                    log_ekle, hiz_carpani=SES_HIZ_CARPANI
                )

                if fallback_basarili and os.path.exists(ses_dosyasi):
                    tts_sonrasi_qa_gerekli = True
                    reels_state = yeni_reels_state
                    pipeline_state["reels_state"] = reels_state
                    seslendirme_metni = yeni_seslendirme_metni

                    # Voiceover/hook değiştiği için caption da yeni Reels'e bağlanmalı.
                    try:
                        caption_state, model_caption = _caption_calistir(
                            router, reels_state, fact_state, editorial_state, video_state, log_ekle
                        )
                        pipeline_state["caption_state"] = caption_state
                    except Exception as caption_hata:
                        log_ekle(f"⚠️ Fallback sonrası caption yenilenemedi: {str(caption_hata)[:150]}")

                    ses_basarili = True
                    kullanilan_ses_modeli = fallback_modeli
                    if eski_ses != ses_dosyasi and os.path.exists(eski_ses):
                        temp_dosya_temizle(eski_ses)
                    yeni_ses_sure = _ses_suresini_al(ses_dosyasi)
                    log_ekle(f"✅ Fallback sonrası yeni ses süresi: {yeni_ses_sure:.2f}s")
                else:
                    if os.path.exists(ses_dosyasi):
                        temp_dosya_temizle(ses_dosyasi)

                    # Yeni metin için TTS başarısızsa eski metin + eski ses birlikte korunur.
                    reels_state = eski_reels_state
                    pipeline_state["reels_state"] = reels_state
                    seslendirme_metni = reels_state.get(
                        "seslendirme_metni", seslendirme_metni
                    )
                    if ilk_ses_dosyasi and os.path.exists(ilk_ses_dosyasi):
                        ses_dosyasi = ilk_ses_dosyasi
                        ses_basarili = True
                        kullanilan_ses_modeli = ilk_ses_modeli
                    else:
                        ses_basarili = False
                    log_ekle("⚠️ Fallback ses üretimi başarısız. İlk başarılı ses ve metin korunuyor.")
            except Exception as fallback_hata:
                if os.path.exists(ses_dosyasi) and ses_dosyasi != ilk_ses_dosyasi:
                    temp_dosya_temizle(ses_dosyasi)

                reels_state = eski_reels_state
                pipeline_state["reels_state"] = reels_state
                seslendirme_metni = reels_state.get(
                    "seslendirme_metni", seslendirme_metni
                )
                if ilk_ses_dosyasi and os.path.exists(ilk_ses_dosyasi):
                    ses_dosyasi = ilk_ses_dosyasi
                    ses_basarili = True
                    kullanilan_ses_modeli = ilk_ses_modeli
                log_ekle(
                    f"⚠️ Fallback voiceover üretimi hatası; "
                    f"ilk ses ve metin korunuyor: {str(fallback_hata)[:180]}"
                )

    if ses_basarili and os.path.exists(ses_dosyasi):
        pipeline_state["ses_dosyasi_son"] = ses_dosyasi

    # Sadece TTS fallback gerçekten yeni bir voiceover ürettiyse
    # önceki QA'yı geçersiz sayıp bir son doğrulama yap.
    if tts_sonrasi_qa_gerekli:
        qa_state, _ = _qa_calistir(
            router, video_state, fact_state, editorial_state,
            reels_state, caption_state, threads_state, sure_saniye, log_ekle
        )
        pipeline_state["qa_state_final"] = qa_state
        if str(qa_state.get("overall", "")).upper() == "PASS":
            log_ekle("✅ TTS fallback sonrası final QA: PASS.")
        elif qa_state.get("overall"):
            log_ekle(f"⚠️ TTS fallback sonrası final QA: {qa_state.get('overall')}.")

    # ---- 9) VIDEO + AUDIO RENDER ----
    _ilerleme(ilerlemeyi_guncelle, 9)
    log_ekle("🎬 Videoya AI sesi ekleniyor...")
    output_video_path = gecici_dosya_yolu("output", "mp4")
    render_basarili = video_ve_sesi_birlestir(temp_input_video, ses_dosyasi, output_video_path, log_ekle)
    final_video_yolu = output_video_path if (render_basarili and os.path.exists(output_video_path)) else ""
    log_ekle("🏁 Pipeline tamamlandı.")

    return {
        # ---- Mevcut UI ile birebir uyumlu alanlar ----
        "seslendirme_metni": seslendirme_metni,
        "reels_aciklamasi": caption_state.get("reels_aciklamasi", ""),
        "reels_hashtagleri": caption_state.get("reels_hashtagleri", []),
        "kapak_basliklari": reels_state.get("kapak_basliklari", []),
        "threads_aciklamasi": threads_state.get("threads_aciklamasi", ""),
        "ses_basarili": ses_basarili,
        "ses_dosyasi": ses_dosyasi,
        "secilen_ses_ingilizce": secilen_ses_ingilizce,
        "kullanilan_metin_modeli": model_reels,
        "kullanilan_ses_modeli": kullanilan_ses_modeli,
        "kullanilan_threads_modeli": model_threads,
        "final_video": final_video_yolu,
        "temp_input_video": temp_input_video,
        # ---- Yeni pipeline alanları (eski UI kullanmasa da sorun çıkarmaz) ----
        "fact_lock": fact_state,
        "editorial_brief": editorial_state,
        "selected_hook": _secilen_hook_getir(reels_state),
        "qa_result": qa_state,
        "pipeline_state": pipeline_state,
    }
