"""otoXtra sonuç ekranı.

Yeni Ultimate Pipeline sonuçlarını gösterir:
- Hazır video
- Ayrı ses
- Reels caption + hashtag
- Kapak başlıkları
- Threads
- Fact Lock
- Editorial Brief
- Hook / Creative stratejisi
- Final QA
- Seslendirme metni düzenleme
- Düzenlenmiş metinden yeniden TTS + video üretme

Eski çalışan UI özellikleri korunmuştur.
"""
import os
import re
import json
import base64
import streamlit as st
import streamlit.components.v1 as components
from config import SES_HIZ_CARPANI
from utils import markdown_temizle, kapak_basliklarini_formatla
from storage import tum_kayitlari_sil
from media import temp_dosya_temizle, video_ve_sesi_birlestir, gecici_ses_yolu, gecici_dosya_yolu

def _format_temizle(metin) -> str:
    """Fazla boş satırları temizler."""
    if metin is None:
        return ''
    return re.sub('\\n{3,}', '\n\n', str(metin).strip())

def _liste_metin(madde_listesi) -> str:
    """Listeyi güvenli şekilde madde işaretli metne çevirir."""
    if not madde_listesi:
        return ''
    if not isinstance(madde_listesi, list):
        return str(madde_listesi)
    satirlar = []
    for madde in madde_listesi:
        if isinstance(madde, dict):
            parcalar = []
            for key, value in madde.items():
                if value in (None, ''):
                    continue
                if isinstance(value, list):
                    value = ', '.join((str(x) for x in value))
                parcalar.append(f'{key}: {value}')
            if parcalar:
                satirlar.append('• ' + ' | '.join(parcalar))
        else:
            satirlar.append(f'• {madde}')
    return '\n'.join(satirlar)

def _durum_badge(durum: str) -> str:
    """QA durumunu kullanıcı dostu badge'e çevirir."""
    durum = str(durum or '').upper().strip()
    if durum == 'PASS':
        return '🟢 PASS'
    if durum == 'FAIL':
        return '🔴 FAIL'
    if durum in ('ATLANDI', 'SKIPPED'):
        return '🟡 ATLANDI'
    return f"⚪ {durum or 'BİLİNMİYOR'}"

def _qa_satiri(label: str, value) -> None:
    """QA maddesini düzenli şekilde gösterir."""
    value = str(value or '').strip()
    if not value:
        value = 'Belirtilmedi.'
    value_upper = value.upper()
    if value_upper.startswith('PASS'):
        st.success(f'**{label}:** {value}')
    elif value_upper.startswith('FAIL'):
        st.error(f'**{label}:** {value}')
    else:
        st.markdown(f'**{label}:** {value}')

def _temizlik_sonrasi_sonucu_sil(sonuc: dict) -> None:
    """Sonuca ait geçici medya dosyalarını temizler."""
    temizlenecekler = set()
    for anahtar in ('ses_dosyasi', 'final_video', 'temp_input_video'):
        dosya = sonuc.get(anahtar)
        if dosya:
            temizlenecekler.add(dosya)
    for dosya in st.session_state.get('gecici_ses_dosyalari', []):
        if dosya:
            temizlenecekler.add(dosya)
    for dosya in temizlenecekler:
        try:
            temp_dosya_temizle(dosya)
        except Exception:
            pass
    st.session_state.gecici_ses_dosyalari = []

def _copy_button(metin: str, key: str, label: str) -> None:
    """JS ile tek tıkla kopyalama butonu."""
    js_metin = json.dumps(str(metin), ensure_ascii=False)
    safe_key = re.sub('[^a-zA-Z0-9_]', '_', str(key))
    button_id = f'copyBtn_{safe_key}'
    copy_html = f'\n<button\n    id="{button_id}"\n    onclick="copyText_{safe_key}()"\n    style="\n        width:100%;\n        height:44px;\n        font-size:15px;\n        font-weight:600;\n        background:linear-gradient(135deg,#1E90FF,#00BFFF);\n        color:#fff;\n        border:none;\n        border-radius:8px;\n        cursor:pointer;\n    "\n>\n    {label}\n</button>\n\n<script>\nasync function copyText_{safe_key}() {{\n    const text = {js_metin};\n    const btn = document.getElementById("{button_id}");\n\n    try {{\n        await navigator.clipboard.writeText(text);\n\n        const oldText = btn.innerText;\n        btn.innerText = "✅ Kopyalandı!";\n        btn.style.background = "#28a745";\n\n        setTimeout(() => {{\n            btn.innerText = oldText;\n            btn.style.background =\n                "linear-gradient(135deg,#1E90FF,#00BFFF)";\n        }}, 1800);\n\n    }} catch (err) {{\n        try {{\n            const textArea =\n                document.createElement("textarea");\n\n            textArea.value = text;\n            document.body.appendChild(textArea);\n            textArea.select();\n            document.execCommand("copy");\n            document.body.removeChild(textArea);\n\n            const oldText = btn.innerText;\n            btn.innerText = "✅ Kopyalandı!";\n\n            setTimeout(() => {{\n                btn.innerText = oldText;\n            }}, 1800);\n\n        }} catch (fallbackErr) {{\n            console.log("Copy failed:", fallbackErr);\n        }}\n    }}\n}}\n</script>\n'
    components.html(copy_html, height=52)

def render_results(log_ekle, router) -> None:
    """Üretim sonuçlarını ekrana çiz."""
    if not st.session_state.get('sonuc'):
        return
    sonuc = st.session_state.sonuc
    veri = sonuc.get('veri', {}) or {}
    kullanilan_metin_modeli = sonuc.get('kullanilan_metin_modeli', '?')
    pipeline_state = sonuc.get('pipeline_state', {}) or {}
    fact_state = sonuc.get('fact_lock', sonuc.get('fact_state', pipeline_state.get('fact_state', {}))) or {}
    editorial_state = sonuc.get('editorial_brief', sonuc.get('editorial_state', pipeline_state.get('editorial_state', {}))) or {}
    reels_state = sonuc.get('reels_state', pipeline_state.get('reels_state', {})) or {}
    caption_state = sonuc.get('caption_state', pipeline_state.get('caption_state', {})) or {}
    threads_state = sonuc.get('threads_state', pipeline_state.get('threads_state', {})) or {}
    qa_result = sonuc.get('qa_result', sonuc.get('qa_state_final', pipeline_state.get('qa_state_final', {}))) or {}
    qa_initial = sonuc.get('qa_state_ilk', pipeline_state.get('qa_state_ilk', {})) or {}
    selected_hook = sonuc.get('selected_hook', {}) or {}
    overall = str(qa_result.get('overall', '')).upper()
    if overall == 'PASS':
        st.success(f'✅ Üretim tamamlandı! QA: {_durum_badge(overall)} ({kullanilan_metin_modeli})')
    elif overall == 'FAIL':
        st.warning(f"⚠️ Üretim tamamlandı ancak QA'da uyarı var: {_durum_badge(overall)}")
    else:
        st.success(f'✅ Başarılı! ({kullanilan_metin_modeli})')
    c1, c2 = st.columns([3, 1])
    with c2:
        if st.button('🗑️ Geçmiş Üretimleri Temizle', use_container_width=True, key='clear_all_results'):
            _temizlik_sonrasi_sonucu_sil(sonuc)
            st.session_state.sonuc = None
            st.session_state.log_satirlari = []
            st.session_state._sonuc_versiyon = st.session_state.get('_sonuc_versiyon', 0) + 1
            tum_kayitlari_sil()
            st.rerun()
    st.markdown('### 🎬 Hazır Video (AI Sesli)')
    st.markdown('**📺 AI Ses Eklenmiş Video** (Orijinal video + AI seslendirme)')
    final_video = sonuc.get('final_video', '')
    if final_video and os.path.exists(final_video):
        try:
            with open(final_video, 'rb') as f:
                vid_bytes = f.read()
            show_generated = st.toggle('👁️ Üretilen Videoyu Göster', value=False, key='show_generated_video')
            if show_generated:
                st.video(vid_bytes)
            c_dl, c_share = st.columns(2)
            with c_dl:
                st.download_button('⬇️ İndir (.mp4)', vid_bytes, file_name='otoxtra_sesli.mp4', mime='video/mp4', use_container_width=True, key='download_generated_video')
            with c_share:
                vid_b64 = base64.b64encode(vid_bytes).decode()
                components.html(f'\n<button onclick="shareVideo()" style="\n    width:100%;\n    height:48px;\n    font-size:16px;\n    font-weight:600;\n    background:linear-gradient(135deg,#ff4b4b,#ff6b6b);\n    color:#fff;\n    border:none;\n    border-radius:8px;\n    cursor:pointer;\n">\n    📤 Paylaş / Galeri Kaydet\n</button>\n\n<script>\nasync function shareVideo() {{\n    try {{\n        const b64 = "{vid_b64}";\n        const bin = atob(b64);\n        const arr = new Uint8Array(bin.length);\n\n        for (\n            let i = 0;\n            i < bin.length;\n            i++\n        ) {{\n            arr[i] = bin.charCodeAt(i);\n        }}\n\n        const file = new File(\n            [arr],\n            "otoxtra_sesli.mp4",\n            {{ type: "video/mp4" }}\n        );\n\n        if (\n            navigator.share &&\n            navigator.canShare({{ files: [file] }})\n        ) {{\n            await navigator.share({{\n                files: [file],\n                title: "otoXtra Video"\n            }});\n        }} else {{\n            const url =\n                URL.createObjectURL(file);\n\n            const a =\n                document.createElement("a");\n\n            a.href = url;\n            a.download =\n                "otoxtra_sesli.mp4";\n\n            a.click();\n\n            URL.revokeObjectURL(url);\n        }}\n\n    }} catch(e) {{\n        console.log("Share:", e);\n    }}\n}}\n</script>\n', height=55)
        except Exception as video_hata:
            st.warning('⚠️ Üretilen video okunamadı.')
            if log_ekle:
                log_ekle(f'⚠️ Sonuç videosu okunamadı: {str(video_hata)[:200]}')
    else:
        st.warning('⚠️ Video dosyası oluşturulamadı (ffmpeg hatası veya dosya artık mevcut değil). Sadece ses mevcut olabilir.')
    st.divider()
    st.markdown('### 🎧 Medya (Ayrı Ses)')
    st.markdown(f"**🎙️ Seslendirme** (model: {sonuc.get('kullanilan_ses_modeli', '?')})")
    ses_basarili = bool(sonuc.get('ses_basarili', False))
    ses_dosyasi = sonuc.get('ses_dosyasi', '')
    if ses_basarili and ses_dosyasi and os.path.exists(ses_dosyasi):
        with open(ses_dosyasi, 'rb') as f:
            ses_byte = f.read()
        st.audio(ses_byte, format='audio/wav')
        st.download_button(f"⬇️ {sonuc.get('secilen_ses_ingilizce', 'Ses')} Sesini İndir (.wav)", ses_byte, file_name='seslendirme.wav', mime='audio/wav', key='download_voiceover')
    elif kullanilan_metin_modeli == 'geçmiş':
        st.info('📝 Ayrıntılı geçmiş kayıt. Ses dosyası artık mevcut değil.')
    else:
        st.warning('Ses dosyası bulunamadı.')
    st.divider()
    st.markdown('### 🧠 İçerik Stratejisi')
    st.caption("Yeni pipeline'ın video → araştırma → editoryal → yaratıcı kararlarını özetler.")
    video_state = pipeline_state.get('video_state', {}) or {}
    video_identity = video_state.get('video_identity', {}) or {}
    if video_identity:
        with st.expander('🎥 1. Video Forensic Analysis', expanded=False):
            marka = video_identity.get('brand', '?')
            model = video_identity.get('exact_model', '?')
            confidence = video_identity.get('confidence', '?')
            st.markdown(f'**Araç:** {marka} {model}')
            st.markdown(f'**Güven:** {confidence}')
            observed_facts = video_state.get('observed_facts', [])
            unknowns = video_state.get('unknowns', [])
            visual_opportunities = video_state.get('visual_opportunities', [])
            if observed_facts:
                st.markdown('**Gözlemlenen gerçekler:**')
                st.markdown(_liste_metin(observed_facts))
            if unknowns:
                st.markdown('**Bilinmeyenler:**')
                st.markdown(_liste_metin(unknowns))
            if visual_opportunities:
                st.markdown('**Görsel fırsatlar:**')
                st.markdown(_liste_metin(visual_opportunities))
    with st.expander('🔒 2. Research / Fact Lock', expanded=False):
        satis_durumu = fact_state.get('turkiye_satis_durumu', 'BILINMIYOR')
        st.markdown(f'**Türkiye satış durumu:** `{satis_durumu}`')
        turkiye_fiyati = fact_state.get('turkiye_fiyati', '')
        if turkiye_fiyati:
            st.markdown(f'**Türkiye fiyatı:** {turkiye_fiyati}')
        global_fiyat = fact_state.get('global_fiyat_bilgisi', '')
        if global_fiyat:
            st.markdown(f'**Global fiyat bilgisi:** {global_fiyat}')
        facts = fact_state.get('facts', [])
        if facts:
            st.markdown('**Doğrulanan / tespit edilen bilgiler:**')
            for index, fact in enumerate(facts, start=1):
                if isinstance(fact, dict):
                    fact_text = fact.get('fact', '')
                    status = fact.get('status', '')
                    source = fact.get('source', '')
                    confidence = fact.get('confidence', '')
                    st.markdown(f'**{index}.** {fact_text}')
                    meta = []
                    if status:
                        meta.append(f'Durum: `{status}`')
                    if confidence:
                        meta.append(f'Güven: `{confidence}`')
                    if source:
                        meta.append(f'Kaynak: {source}')
                    if meta:
                        st.caption(' • '.join(meta))
                else:
                    st.markdown(f'**{index}.** {fact}')
        arastirma_notu = fact_state.get('arastirma_notu', '')
        if arastirma_notu:
            st.info(f'**Araştırma notu:** {arastirma_notu}')
    with st.expander('📖 3. Editorial Brain', expanded=False):
        core_story = editorial_state.get('core_story', '')
        if core_story:
            st.markdown(f'### 🎯 Seçilen Hikâye\n{core_story}')
        why_it_matters = editorial_state.get('why_it_matters', '')
        if why_it_matters:
            st.markdown(f'**Neden önemli?**\n\n{why_it_matters}')
        audience_trigger = editorial_state.get('audience_trigger', '')
        if audience_trigger:
            st.markdown(f'**İzleyici tetikleyicisi:** {audience_trigger}')
        discussion_territory = editorial_state.get('discussion_territory', '')
        if discussion_territory:
            st.markdown(f'**Tartışma alanı:** {discussion_territory}')
        primary_facts = editorial_state.get('primary_facts', [])
        if primary_facts:
            st.markdown('**Hikâyeyi destekleyen ana gerçekler:**')
            st.markdown(_liste_metin(primary_facts))
        things_to_avoid = editorial_state.get('things_to_avoid', [])
        if things_to_avoid:
            st.markdown('**Kaçınılacaklar:**')
            st.markdown(_liste_metin(things_to_avoid))
    with st.expander('🎨 4. Reels Creative — Hook / Cover', expanded=False):
        if selected_hook:
            st.markdown('### ⭐ Seçilen Hook Ailesi')
            kapak_ana = selected_hook.get('kapak_ana', '')
            kapak_alt = selected_hook.get('kapak_alt', '')
            ilk_uc_saniye = selected_hook.get('ilk_uc_saniye', '')
            anlati_yonu = selected_hook.get('anlati_yonu', '')
            if kapak_ana:
                st.markdown(f'**Kapak ana:** {kapak_ana}')
            if kapak_alt:
                st.markdown(f'**Kapak alt:** {kapak_alt}')
            if ilk_uc_saniye:
                st.markdown(f'**İlk 3 saniye / Voice Hook:** {ilk_uc_saniye}')
            if anlati_yonu:
                st.markdown(f'**Anlatı yönü:** {anlati_yonu}')
            score_fields = [('Merak', 'curiosity_score'), ('Görsel eşleşme', 'visual_match_score'), ('Gerçek gücü', 'fact_strength_score'), ('Özgünlük', 'originality_score'), ('Retention', 'retention_score')]
            scores = []
            for label, key in score_fields:
                value = selected_hook.get(key)
                if isinstance(value, (int, float)):
                    scores.append(f'{label}: {value}')
            if scores:
                st.caption(' • '.join(scores))
        hook_families = reels_state.get('hook_families', [])
        if hook_families:
            st.markdown('### Diğer Hook Aileleri')
            for index, hook in enumerate(hook_families, start=1):
                if not isinstance(hook, dict):
                    continue
                kapak = hook.get('kapak_ana', '')
                alt = hook.get('kapak_alt', '')
                hook_text = hook.get('ilk_uc_saniye', '')
                st.markdown(f'**{index}.** {kapak}')
                if alt:
                    st.caption(f'Alt: {alt}')
                if hook_text:
                    st.caption(f'Hook: {hook_text}')
        beyin_firtinasi = reels_state.get('beyin_firtinasi', '')
        veri_kilitleme = reels_state.get('veri_kilitleme', '')
        oz_elestiri = reels_state.get('oz_elestiri', '')
        if beyin_firtinasi or veri_kilitleme or oz_elestiri:
            st.markdown('### Creative Strateji Notları')
            if beyin_firtinasi:
                st.markdown('**Beyin fırtınası:**')
                st.info(beyin_firtinasi)
            if veri_kilitleme:
                st.markdown('**Veri kilitleme:**')
                st.warning(veri_kilitleme)
            if oz_elestiri:
                st.markdown('**Öz denetim:**')
                st.error(oz_elestiri)
    st.divider()
    st.markdown('### 📝 Metin İçerikleri (Toplu)')
    aciklama_raw = caption_state.get('reels_aciklamasi', veri.get('reels_aciklamasi', ''))
    hashtagler = caption_state.get('reels_hashtagleri', veri.get('reels_hashtagleri', []))
    kapak_raw = reels_state.get('kapak_basliklari', veri.get('kapak_basliklari', []))
    threads_raw = threads_state.get('threads_aciklamasi', veri.get('threads_aciklamasi', ''))
    aciklama_metni = markdown_temizle(aciklama_raw)
    if hashtagler and isinstance(hashtagler, list):
        hashtag_str = ' '.join((h if str(h).startswith('#') else f'#{h}' for h in hashtagler))
        tam_aciklama = f'{aciklama_metni}\n\n{hashtag_str}'
    else:
        tam_aciklama = aciklama_metni
    basliklar = kapak_basliklarini_formatla(kapak_raw)
    threads = markdown_temizle(threads_raw)
    tam_aciklama = _format_temizle(tam_aciklama)
    basliklar = _format_temizle(basliklar)
    threads = _format_temizle(threads)
    ayrac = '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
    birlesik_metin = f'📌 REELS AÇIKLAMASI\n{tam_aciklama}\n\n{ayrac}\n\n📌 KAPAK BAŞLIKLARI\n{basliklar}\n\n{ayrac}\n\n📌 THREADS AÇIKLAMASI\n{threads}\n'
    _copy_button(birlesik_metin, 'all_texts', '📋 Tüm Metinleri Kopyala (Reels + Başlıklar + Threads)')
    st.text_area('Birleşik Metinler', value=birlesik_metin, height=450, label_visibility='collapsed', key='birlesik_metin_display')
    with st.expander('📌 Reels Caption Detayı', expanded=False):
        st.text_area('Reels Caption', value=aciklama_metni, height=220, label_visibility='collapsed', key='reels_caption_detail')
        if hashtagler:
            st.markdown('**Hashtagler:**')
            st.code(hashtag_str if 'hashtag_str' in locals() else ' '.join((f'#{h}' for h in hashtagler)), language=None)
    with st.expander('📌 Kapak Başlıkları', expanded=False):
        st.text_area('Kapak Başlıkları', value=basliklar, height=220, label_visibility='collapsed', key='cover_titles_detail')
    with st.expander('🧵 Threads', expanded=False):
        st.text_area('Threads', value=threads, height=180, label_visibility='collapsed', key='threads_detail')
    st.divider()
    st.markdown('### 🧪 Final QA')
    st.caption('QA yeni içerik üretmez; üretilen içeriği hakem gibi denetler.')
    if qa_result:
        overall = qa_result.get('overall', 'BILINMIYOR')
        if str(overall).upper() == 'PASS':
            st.success(f'🟢 Final QA: **PASS**')
        elif str(overall).upper() == 'FAIL':
            st.warning(f'🔴 Final QA: **FAIL**')
        else:
            st.info(f'🟡 Final QA: **{overall}**')
        regeneration_targets = qa_result.get('regeneration_targets', []) or []
        if regeneration_targets:
            st.warning('Yeniden üretim tetikleyen alanlar: ' + ', '.join((str(x) for x in regeneration_targets)))
        qa_items = [('🔒 Fact Check', 'fact_check'), ('🤖 Model Check', 'model_check'), ('🎥 Video Check', 'video_check'), ('🌐 Current Data Check', 'current_data_check'), ('🖼️ Cover Check', 'cover_check'), ('🪝 Hook Check', 'hook_check'), ('👀 Visual Match', 'visual_match_check'), ('♻️ Repetition Check', 'repetition_check'), ('🎙️ TTS Check', 'tts_check'), ('📏 Length Check', 'length_check'), ('📝 Caption Check', 'caption_check'), ('#️⃣ Hashtag Check', 'hashtag_check'), ('🧵 Threads Check', 'threads_check'), ('🏎️ Brand Check', 'brand_check')]
        for label, key in qa_items:
            value = qa_result.get(key, '')
            if value:
                _qa_satiri(label, value)
        if qa_initial:
            ilk_overall = qa_initial.get('overall', '')
            final_overall = qa_result.get('overall', '')
            if ilk_overall and final_overall and (str(ilk_overall).upper() != str(final_overall).upper()):
                st.info(f'🔄 QA sonucu yeniden üretim sonrası **{ilk_overall} → {final_overall}** olarak değişti.')
    else:
        st.info('QA sonucu bulunamadı.')
    st.divider()
    st.markdown('### 🎙️ Seslendirme Metni')
    st.caption('TTS için üretilen metin. İstersen düzenleyip yeniden ses ve video üretebilirsin.')
    current_version = st.session_state.get('_sonuc_versiyon', 0)
    last_version = st.session_state.get('_sonuc_versiyon_last', -1)
    if current_version != last_version:
        st.session_state['_sonuc_versiyon_last'] = current_version
        if 'duzenlenmis_ses_metni_widget' in st.session_state:
            del st.session_state['duzenlenmis_ses_metni_widget']
    seslendirme_metni = veri.get('seslendirme_metni', sonuc.get('seslendirme_metni', ''))
    duzenlenmis_ses_metni = st.text_area('Seslendirme Metni', value=st.session_state.get('duzenlenmis_ses_metni_widget', seslendirme_metni), height=300, label_visibility='collapsed', key='duzenlenmis_ses_metni_widget')
    if st.button('🔄 Bu Metinle Yeniden Ses ve Video Üret', use_container_width=True, key='regenerate_audio_video'):
        temiz_metin = (duzenlenmis_ses_metni or '').strip()
        if not temiz_metin:
            st.error('❌ Seslendirme metni boş olamaz.')
        else:
            with st.spinner('🎧 Ses ve video yeniden üretiliyor...'):
                yeni_ses_dosyasi = gecici_ses_yolu()
                try:
                    ses_basarili_yeni, kullanilan_ses_modeli_yeni = router.ses_uret(temiz_metin, sonuc.get('secilen_ses_ingilizce', ''), yeni_ses_dosyasi, log_ekle, hiz_carpani=SES_HIZ_CARPANI)
                    if ses_basarili_yeni and os.path.exists(yeni_ses_dosyasi):
                        eski_ses_dosyasi = sonuc.get('ses_dosyasi', '')
                        if eski_ses_dosyasi and os.path.exists(eski_ses_dosyasi):
                            temp_dosya_temizle(eski_ses_dosyasi)
                        if eski_ses_dosyasi in st.session_state.gecici_ses_dosyalari:
                            st.session_state.gecici_ses_dosyalari.remove(eski_ses_dosyasi)
                        st.session_state.gecici_ses_dosyalari.append(yeni_ses_dosyasi)
                        temp_input_video = sonuc.get('temp_input_video', '')
                        if temp_input_video and os.path.exists(temp_input_video):
                            yeni_output_video = gecici_dosya_yolu('output', 'mp4')
                            render_basarili = video_ve_sesi_birlestir(temp_input_video, yeni_ses_dosyasi, yeni_output_video, log_ekle)
                            if render_basarili and os.path.exists(yeni_output_video):
                                eski_video = sonuc.get('final_video', '')
                                if eski_video and os.path.exists(eski_video):
                                    temp_dosya_temizle(eski_video)
                                st.session_state.sonuc['final_video'] = yeni_output_video
                                log_ekle('✅ Yeni video başarıyla üretildi.')
                            else:
                                log_ekle('⚠️ Video birleştirme başarısız; sadece ses güncellendi.')
                        else:
                            log_ekle('⚠️ Orijinal video bulunamadı; sadece ses güncellendi.')
                        st.session_state.sonuc['ses_dosyasi'] = yeni_ses_dosyasi
                        st.session_state.sonuc['ses_basarili'] = True
                        st.session_state.sonuc['secilen_ses_ingilizce'] = sonuc.get('secilen_ses_ingilizce', '')
                        st.session_state.sonuc['kullanilan_ses_modeli'] = kullanilan_ses_modeli_yeni or sonuc.get('kullanilan_ses_modeli', '?')
                        st.session_state.sonuc['veri']['seslendirme_metni'] = temiz_metin
                        # Kullanıcı metni elle değiştirdiği için önceki QA artık
                        # bu yeni metin için geçerli değildir.
                        st.session_state.sonuc['qa_result'] = {
                            'overall': 'ATLANDI',
                            'regeneration_targets': [],
                            'tts_check': 'ATLANDI: Metin kullanıcı tarafından değiştirildi.'
                        }
                        if isinstance(st.session_state.sonuc.get('pipeline_state'), dict):
                            st.session_state.sonuc['pipeline_state']['qa_state_final'] = st.session_state.sonuc['qa_result']
                        if 'pipeline_state' in st.session_state.sonuc:
                            pipeline_state_local = st.session_state.sonuc['pipeline_state']
                            reels_state_local = pipeline_state_local.get('reels_state', {})
                            if isinstance(reels_state_local, dict):
                                reels_state_local['seslendirme_metni'] = temiz_metin
                        st.session_state._sonuc_versiyon = st.session_state.get('_sonuc_versiyon', 0) + 1
                        st.success('✅ Yeni seslendirme ve video başarıyla oluşturuldu.')
                        st.rerun()
                    else:
                        st.error('❌ Ses üretilemedi. Logları kontrol edin.')
                        if os.path.exists(yeni_ses_dosyasi):
                            temp_dosya_temizle(yeni_ses_dosyasi)
                except Exception as e:
                    if os.path.exists(yeni_ses_dosyasi):
                        temp_dosya_temizle(yeni_ses_dosyasi)
                    st.error('❌ Yeniden üretim sırasında beklenmeyen hata oluştu.')
                    if log_ekle:
                        log_ekle(f'❌ Yeniden TTS/video hatası: {str(e)[:300]}')
    with st.expander('🔧 Geliştirici: Pipeline State', expanded=False):
        st.caption("Debug amacıyla pipeline'ın oluşturduğu state'ler. Normal kullanımda açmana gerek yok.")
        if pipeline_state:
            try:
                st.json(pipeline_state)
            except Exception:
                st.code(str(pipeline_state), language=None)
