"""Telegram Bot API gönderim fonksiyonları."""
import os
import time
import requests as http_requests


def telegram_mesaj_gonder(bot_token: str, chat_id: str, metin: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": metin}
        resp = http_requests.post(url, json=payload, timeout=30)
        return resp.status_code == 200
    except Exception:
        return False


def telegram_ses_gonder(
    bot_token: str, chat_id: str, dosya_yolu: str, baslik: str = "otoXtra_seslendirme"
) -> bool:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
        with open(dosya_yolu, "rb") as f:
            resp = http_requests.post(
                url,
                data={"chat_id": chat_id, "title": baslik, "performer": "otoXtra"},
                files={"audio": (f"{baslik}.wav", f, "audio/wav")},
                timeout=60,
            )
        return resp.status_code == 200
    except Exception:
        return False


def telegram_toplu_gonder(
    bot_token: str,
    chat_id: str,
    veri: dict,
    ses_dosyasi: str = None,
    log_ekle=None,
) -> dict:
    sonuclar = {"basarili": 0, "basarisiz": 0, "detay": []}

    def _gonder(mesaj: str, etiket: str):
        ok = telegram_mesaj_gonder(bot_token, chat_id, mesaj)
        if ok:
            sonuclar["basarili"] += 1
            sonuclar["detay"].append(f"✅ {etiket}")
            if log_ekle:
                log_ekle(f"📤 {etiket} → gönderildi")
        else:
            sonuclar["basarisiz"] += 1
            sonuclar["detay"].append(f"❌ {etiket}")
            if log_ekle:
                log_ekle(f"❌ {etiket} → BAŞARISIZ")
        time.sleep(0.5)

    # 1) Seslendirme Metni
    ses_metni = veri.get("seslendirme_metni", "").strip()
    if ses_metni:
        _gonder(f"🎙️ SESLENDİRME METNİ\n{'─' * 30}\n\n{ses_metni}", "Seslendirme Metni")

    # 2) Reels Açıklaması + Hashtagler
    aciklama = veri.get("reels_aciklamasi", "").strip()
    hashtagler = veri.get("reels_hashtagleri", [])
    if aciklama:
        hashtag_str = ""
        if hashtagler and isinstance(hashtagler, list):
            hashtag_str = "\n\n" + " ".join(
                [h if str(h).startswith("#") else f"#{h}" for h in hashtagler]
            )
        _gonder(
            f"📝 REELS AÇIKLAMASI\n{'─' * 30}\n\n{aciklama}{hashtag_str}",
            "Reels Açıklaması",
        )

    # 3) Kapak Başlıkları (TEK TEK)
    kapaklar = veri.get("kapak_basliklari", [])
    if kapaklar and isinstance(kapaklar, list):
        for i, secenek in enumerate(kapaklar, start=1):
            if isinstance(secenek, dict):
                ana = secenek.get("ana", "").strip()
                alt = secenek.get("alt", "").strip()
                mesaj = f"🏷️ KAPAK BAŞLIĞI {i}\n{'─' * 30}\n\n{ana}"
                if alt:
                    mesaj += f"\n{alt}"
            else:
                mesaj = f"🏷️ KAPAK BAŞLIĞI {i}\n{'─' * 30}\n\n{str(secenek).strip()}"
            _gonder(mesaj, f"Kapak Başlığı {i}")

    # 4) Threads Açıklaması
    threads = veri.get("threads_aciklamasi", "").strip()
    if threads:
        _gonder(f"🧵 THREADS AÇIKLAMASI\n{'─' * 30}\n\n{threads}", "Threads Açıklaması")

    # 5) Ses Dosyası
    if ses_dosyasi and os.path.exists(ses_dosyasi):
        ok = telegram_ses_gonder(bot_token, chat_id, ses_dosyasi, "otoXtra_seslendirme")
        if ok:
            sonuclar["basarili"] += 1
            sonuclar["detay"].append("✅ Ses Dosyası")
            if log_ekle:
                log_ekle("📤 Ses Dosyası → gönderildi")
        else:
            sonuclar["basarisiz"] += 1
            sonuclar["detay"].append("❌ Ses Dosyası")
            if log_ekle:
                log_ekle("❌ Ses Dosyası → BAŞARISIZ")

    return sonuclar
