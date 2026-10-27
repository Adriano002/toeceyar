# components/firma.py
import os
import streamlit as st
import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(__file__), "firma_build")
_firma = components.declare_component("firma_canvas", path=_DIR)


def firma_widget(key="firma"):
    """Renderiza el canvas de firma y guarda el base64 en session_state."""
    result = _firma(key=key)
    if result and result.get("firma_data"):
        st.session_state[f"_firma_actual_{key}"] = result["firma_data"]
    return result


def firma_guardada(key):
    """Devuelve la última firma guardada para esa key."""
    return st.session_state.get(f"_firma_actual_{key}")


def limpiar_firma(key):
    """Borra la firma del session_state."""
    st.session_state.pop(f"_firma_actual_{key}", None)


def tiene_firma(key):
    """Devuelve True si hay firma guardada."""
    return bool(st.session_state.get(f"_firma_actual_{key}"))