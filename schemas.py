"""
Ultimate Content Engine — Pipeline Şemaları

Eski tek büyük METIN_SCHEMA kaldırıldı. Her editoryal rolün kendi şeması var.
Böylece her model çağrısı yalnızca kendi görevine ait alanları üretir
(attention dilution azalır, JSON daha güvenilir üretilir).
"""

# ============================================================
# 1) FORENSIC VIDEO ANALYSIS
# Görev: Videoda GERÇEKTE ne olduğunu tespit etmek.
# Yaratıcı içerik (hook/cover/caption) ÜRETMEZ.
# ============================================================
VIDEO_ANALYSIS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "video_identity": {
            "type": "OBJECT",
            "properties": {
                "brand": {"type": "STRING"},
                "exact_model": {"type": "STRING", "description": "Tam model adı. Emin değilsen 'UNKNOWN' yaz. Benzer modelin adını uydurma."},
                "variant": {"type": "STRING", "description": "Pro/Plus/Max/GT/EV/DM-i/PHEV/Cross gibi ekler. Yoksa boş bırak."},
                "generation": {"type": "STRING"},
                "body_type": {"type": "STRING"},
                "confidence": {"type": "STRING", "description": "high / medium / low / unknown"},
            },
            "required": ["brand", "exact_model", "confidence"],
        },
        "kapak_ani_saniye": {"type": "NUMBER", "description": "Kapak/hook için en çarpıcı anın videodaki saniyesi."},
        "timeline": {
            "type": "ARRAY",
            "description": "Videoyu görsel geçişlere göre bölen zaman çizelgesi.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "baslangic": {"type": "STRING"},
                    "bitis": {"type": "STRING"},
                    "olay": {"type": "STRING"},
                    "arac_hareketi": {"type": "STRING"},
                    "kamera_hareketi": {"type": "STRING"},
                    "ekran_yazisi": {"type": "STRING"},
                    "teknik_gorsel_detay": {"type": "STRING"},
                },
                "required": ["olay"],
            },
        },
        "observed_facts": {
            "type": "ARRAY",
            "description": "Videoda GERÇEKTEN görülen bilgiler. Yorum/çıkarım değil.",
            "items": {"type": "STRING"},
        },
        "unknowns": {
            "type": "ARRAY",
            "description": "Videodan belirlenemeyen bilgiler.",
            "items": {"type": "STRING"},
        },
        "possible_inference": {
            "type": "ARRAY",
            "description": "Modelin çıkarımı. Gerçek gibi kullanılmayacak, sadece işaret.",
            "items": {"type": "STRING"},
        },
        "visual_opportunities": {
            "type": "ARRAY",
            "description": "Görsel olarak dikkat çekici anlar (hook kararı DEĞİL, sadece fırsat tespiti).",
            "items": {"type": "STRING"},
        },
        "viral_arastirma_ihtiyaclari": {
            "type": "ARRAY",
            "description": "Research aşamasının araştırması gereken açık sorular (ör: 'bu sürüş sistemi hangi seviye otonom').",
            "items": {"type": "STRING"},
        },
    },
    "required": [
        "video_identity", "kapak_ani_saniye", "timeline",
        "observed_facts", "unknowns", "possible_inference", "visual_opportunities",
    ],
}

# ============================================================
# 2) RESEARCH / FACT LOCK
# Görev: Doğrulanabilir gerçekleri bulup TEK bir doğruluk katmanı üretmek.
# ============================================================
FACT_LOCK_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "facts": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "fact": {"type": "STRING"},
                    "status": {"type": "STRING", "description": "OBSERVED / VERIFIED / INFERENCE / UNKNOWN"},
                    "source": {"type": "STRING", "description": "VERIFIED ise kaynak. Yoksa boş."},
                    "source_type": {"type": "STRING", "description": "official / manufacturer / industry / news / other"},
                    "confidence": {"type": "STRING", "description": "high / medium / low"},
                },
                "required": ["fact", "status"],
            },
        },
        "turkiye_satis_durumu": {"type": "STRING", "description": "VAR / YOK / BILINMIYOR"},
        "turkiye_fiyati": {"type": "STRING", "description": "Sadece VERIFIED ise doldur. Yoksa 'Türkiye'de resmi satışı yok' veya 'Bilinmiyor' yaz."},
        "global_fiyat_bilgisi": {"type": "STRING"},
        "arastirma_notu": {"type": "STRING", "description": "Neyin doğrulanamadığı, hangi konuda belirsizlik kaldığı."},
    },
    "required": ["facts", "turkiye_satis_durumu"],
}

# ============================================================
# 3) EDITORIAL BRAIN
# Görev: "Ne biliyoruz" değil, "Hangi hikâye en güçlü sonucu verir" kararı.
# ============================================================
EDITORIAL_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "story_options": {
            "type": "ARRAY",
            "description": "Değerlendirilen olası hikâye açıları (performans/fiyat/teknoloji/pazar vb).",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "isim": {"type": "STRING"},
                    "visual_relevance": {"type": "STRING"},
                    "fact_strength": {"type": "STRING"},
                    "curiosity": {"type": "STRING"},
                    "novelty": {"type": "STRING"},
                    "emotional_trigger": {"type": "STRING"},
                    "turkish_audience_relevance": {"type": "STRING"},
                    "shareability": {"type": "STRING"},
                    "repetition_risk": {"type": "STRING"},
                },
                "required": ["isim"],
            },
        },
        "core_story": {"type": "STRING", "description": "Seçilen ana hikâye."},
        "why_it_matters": {"type": "STRING"},
        "primary_facts": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Fact Lock'tan bu hikâyeyi destekleyen gerçekler."},
        "visual_moments": {"type": "ARRAY", "items": {"type": "STRING"}},
        "audience_trigger": {"type": "STRING"},
        "tone": {"type": "STRING"},
        "things_to_avoid": {"type": "ARRAY", "items": {"type": "STRING"}},
        "potential_hook_territories": {"type": "ARRAY", "items": {"type": "STRING"}},
        "discussion_territory": {"type": "STRING", "description": "Threads için tartışma potansiyeli olan açı."},
    },
    "required": ["core_story", "why_it_matters", "primary_facts", "audience_trigger", "tone"],
}

# ============================================================
# 4) REELS CREATIVE ENGINE
# Görev: Cover + Hook + Voiceover'ı AYNI yaratıcı bağlamda üretmek.
# ============================================================
REELS_CREATIVE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "beyin_firtinasi": {"type": "STRING", "description": "Seslendirmeyi yazmadan önce görsel akışa göre strateji planı."},
        "veri_kilitleme": {"type": "STRING", "description": "Fact Lock'tan kullanılacak kesin rakam/bilgilerin listesi."},
        "oz_elestiri": {"type": "STRING", "description": "kurallar.txt'ye göre kendi planının denetimi."},
        "hook_families": {
            "type": "ARRAY",
            "description": "3-5 farklı kapak/hook/anlatı ailesi. Kapak ve hook aynı fikrin iki parçası, birebir tekrar YASAK.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "kapak_ana": {"type": "STRING"},
                    "kapak_alt": {"type": "STRING"},
                    "ilk_uc_saniye": {"type": "STRING", "description": "Voice hook — kapağı tekrar etmez, tamamlar."},
                    "anlati_yonu": {"type": "STRING"},
                    "curiosity_score": {"type": "NUMBER"},
                    "visual_match_score": {"type": "NUMBER"},
                    "fact_strength_score": {"type": "NUMBER"},
                    "originality_score": {"type": "NUMBER"},
                    "retention_score": {"type": "NUMBER"},
                },
                "required": ["kapak_ana", "kapak_alt", "ilk_uc_saniye", "anlati_yonu"],
            },
        },
        "secilen_aile_index": {"type": "INTEGER", "description": "hook_families içinde en güçlü kombinasyonun index'i (0'dan başlar)."},
        "kapak_basliklari": {
            "type": "ARRAY",
            "description": "Kullanıcıya sunulacak 5 kapak alternatifi (mevcut UI ile uyumlu alan).",
            "items": {
                "type": "OBJECT",
                "properties": {"ana": {"type": "STRING"}, "alt": {"type": "STRING"}},
                "required": ["ana", "alt"],
            },
        },
        "seslendirme_metni": {"type": "STRING", "description": "Seçilen hook ailesiyle uyumlu, tam seslendirme metni."},
    },
    "required": ["hook_families", "secilen_aile_index", "kapak_basliklari", "seslendirme_metni"],
}

# ============================================================
# 5) CAPTION + HASHTAG ENGINE
# Görev: Sesi yazıya çevirmek DEĞİL, videoda anlatılmayan ekstra değer sağlamak.
# ============================================================
CAPTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reels_aciklamasi": {"type": "STRING", "description": "5 katmanlı caption (K1-K5). Hashtag İÇERMEZ."},
        "reels_hashtagleri": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Tam 5 adet, # işaretsiz."},
    },
    "required": ["reels_aciklamasi", "reels_hashtagleri"],
}

# ============================================================
# 6) THREADS ENGINE
# Görev: Caption'dan türetilmez. Fact Lock + Editorial Brief'ten BAĞIMSIZ üretilir.
# ============================================================
THREADS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "threads_aciklamasi": {"type": "STRING", "description": "Max 500 karakter. Soru cümlesi ve hashtag yok."},
    },
    "required": ["threads_aciklamasi"],
}

# ============================================================
# 7) FINAL QA ENGINE
# Görev: Yeni içerik ÜRETMEZ, hakem gibi denetler.
# ============================================================
QA_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fact_check": {"type": "STRING", "description": "PASS veya FAIL: neden"},
        "model_check": {"type": "STRING"},
        "video_check": {"type": "STRING"},
        "current_data_check": {"type": "STRING"},
        "cover_check": {"type": "STRING"},
        "hook_check": {"type": "STRING"},
        "visual_match_check": {"type": "STRING"},
        "repetition_check": {"type": "STRING"},
        "tts_check": {"type": "STRING"},
        "length_check": {"type": "STRING"},
        "caption_check": {"type": "STRING"},
        "hashtag_check": {"type": "STRING"},
        "threads_check": {"type": "STRING"},
        "brand_check": {"type": "STRING"},
        "overall": {"type": "STRING", "description": "PASS veya FAIL"},
        "regeneration_targets": {
            "type": "ARRAY",
            "description": "FAIL olan alanlar: VOICEOVER_FAIL / CAPTION_FAIL / COVER_FAIL / THREADS_FAIL / FACT_FAIL",
            "items": {"type": "STRING"},
        },
    },
    "required": ["overall", "regeneration_targets"],
}

