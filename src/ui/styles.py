"""Zentrale UI-Styles ohne unsicheres Roh-HTML aus Nutzereingaben."""

from __future__ import annotations

import streamlit as st

_APP_CSS = """
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2.5rem;
    }
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 10px 14px;
    }
</style>
"""


def inject_global_styles() -> None:
    st.markdown(_APP_CSS, unsafe_allow_html=True)
