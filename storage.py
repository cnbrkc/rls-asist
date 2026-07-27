"""Üretim kayıtlarının JSON dosyasına yazılması/okunması."""
import json
import os
from datetime import datetime
from config import KAYIT_DOSYASI, MAX_KAYIT, SES_DOSYA_OMRU_SAAT


def kayitlari_yukle() -> list:
    if not os.path.exists(KAYIT_DOSYASI):
        return []
    try:
        with open(KAYIT_DOSYASI, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def kayitlari_kaydet(kayitlar: list):
    with open(KAYIT_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(kayitlar, f, ensure_ascii=False, indent=2)


def eski_sesleri_temizle(kayitlar: list):
    simdi = datetime.now()
    for k in kayitlar:
        try:
            kayit_zamani = datetime.fromisoformat(k.get("kayit_zamani", ""))
            if (simdi - kayit_zamani).total_seconds() > SES_DOSYA_OMRU_SAAT * 3600:
                yol = k.get("ses_dosyasi", "")
                if yol and os.path.exists(yol):
                    os.remove(yol)
                    k["ses_dosyasi"] = None
        except (ValueError, TypeError):
            pass


def kayit_ekle(veri: dict) -> list:
    kayitlar = kayitlari_yukle()
    veri["tarih"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    veri["kayit_zamani"] = datetime.now().isoformat()
    kayitlar.insert(0, veri)
    kayitlar = kayitlar[:MAX_KAYIT]
    kayitlari_kaydet(kayitlar)
    eski_sesleri_temizle(kayitlar)
    kayitlari_kaydet(kayitlar)   # ← BUG DÜZELTME: temizlik sonrası değişiklikleri yaz
    return kayitlar
