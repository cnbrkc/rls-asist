"""Genel yardımcı fonksiyonlar (JSON parse, metin temizleme, formatlama)."""
import re
import json
from typing import List

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
