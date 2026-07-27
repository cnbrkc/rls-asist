"""Saf yardımcı fonksiyonlar."""
import os
import re
import json
import tempfile
import uuid
import streamlit as st


def markdown_temizle(metin: str) -> str:
    metin = metin.strip()
    if metin.startswith("```"):
        metin = re.sub(r"^```(?:json)?\s*", "", metin)
        metin = re.sub(r"\s*```$", "", metin)
    return metin.strip()


def json_parse(metin: str) -> dict:
    metin = markdown_temizle(metin)
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        eslesme = re.search(r"\{.*\}", metin, re.DOTALL)
        if eslesme:
            try:
                return json.loads(eslesme.group())
            except json.JSONDecodeError:
                pass
    return {}


def gecici_dosya_olustur(veri: bytes, uzanti: str = ".wav") -> str:
    yol = os.path.join(tempfile.gettempdir(), f"otoxtra_{uuid.uuid4().hex}{uzanti}")
    with open(yol, "wb") as f:
        f.write(veri)
    return yol


def sekmeyi_aktif_tut():
    st.markdown(
        """
        <script>
        setInterval(function() {
            window.postMessage({type: "keepAlive"}, "*");
        }, 30000);
        </script>
        """,
        unsafe_allow_html=True,
    )
