# utils.py
import hashlib
import secrets
import streamlit as st
from datetime import datetime, timedelta, timezone
from io import BytesIO
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def ahora():
    return datetime.now(timezone.utc) - timedelta(hours=5)


def hoy_str():
    return ahora().strftime("%Y-%m-%d")


def hora_corta():
    return ahora().strftime("%H:%M")


def timestamp_str():
    return ahora().strftime("%Y-%m-%d %H:%M:%S")


def es_fin_de_semana(fecha=None):
    return (fecha or ahora().date()).weekday() >= 5


def mask_dni(dni):
    d = str(dni or "").strip()
    return d[:4] + "*" * (len(d) - 4) if len(d) >= 4 else "****"


def hashear_password(password):
    salt = secrets.token_bytes(16)
    d = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260000)
    return f"pbkdf2_sha256$260000${salt.hex()}${d.hex()}"


def verificar_password(password, hash_guardado):
    if hash_guardado.startswith("pbkdf2_"):
        try:
            _, it, salt_hex, hash_hex = hash_guardado.split("$")
            d = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(it)
            )
            return secrets.compare_digest(d.hex(), hash_hex)
        except (ValueError, TypeError):
            return False
    return False


@st.cache_data(ttl=3600, max_entries=50)
def df_a_xlsx(df, hoja="Datos"):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=hoja)
    buf.seek(0)
    return buf.getvalue()


@st.cache_data(ttl=3600, max_entries=20)
def generar_pdf_tabla_ancha(df, titulo, subtitulo=None):
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=(A4[1], A4[0]),
        rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20
    )
    est = getSampleStyleSheet()
    el = [Paragraph(f"<b>{titulo}</b>", est["Heading1"])]
    if subtitulo:
        el.append(Paragraph(subtitulo, est["Normal"]))
    el.append(Spacer(1, 12))
    if not df.empty:
        datos = [df.columns.tolist()] + df.astype(str).values.tolist()
        t = Table(datos, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        el.append(t)
    doc.build(el)
    buf.seek(0)
    return buf.getvalue()