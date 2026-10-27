# components/qr_scanner.py
import os
import streamlit as st
import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(__file__), "qr_build")
_qr = components.declare_component("qr_scanner", path=_DIR)


def qr_scanner(key="qr"):
    """
    Escáner QR con cámara.
    Devuelve dict con .qr_dni si escaneó, o None.
    Usa patrón candado para NO reiniciar la cámara en cada rerun.
    """
    if f"_qr_mounted_{key}" not in st.session_state:
        st.session_state[f"_qr_mounted_{key}"] = True
        return _qr(key=key)
    return None


def reset_qr(key="qr"):
    """Borra el candado para reiniciar la cámara."""
    st.session_state.pop(f"_qr_mounted_{key}", None)