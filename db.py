# db.py — SOLO Turso
import libsql
import streamlit as st
import logging
import pandas as pd
from pathlib import Path

log = logging.getLogger("db")
LOCAL_DB_PATH = "data/replica.db"
Path("data").mkdir(exist_ok=True)


@st.cache_resource(ttl=3600)
def obtener_conexion():
    try:
        url = st.secrets["turso"]["url"]
        token = st.secrets["turso"]["token"]
        con = libsql.connect(
            LOCAL_DB_PATH,
            sync_url=url,
            auth_token=token,
            sync_interval=30,
        )
        #con.row_factory = libsql.Row
        cur = con.cursor()
        from schema import aplicar_schema
        aplicar_schema(cur)
        con.commit()
        return con
    except Exception as e:
        log.error(f"Error Turso: {e}")
        st.error("Error de conexión a la BD. Revisa los Secrets.")
        st.stop()


def _sync(con):
    try:
        con.sync()
    except Exception as e:
        log.warning(f"Sync Turso falló: {e}")


def escribir(sql, params=()):
    con = obtener_conexion()
    with con:
        con.execute(sql, params)
    _sync(con)


def leer_df(sql, params=()):
    con = obtener_conexion()
    cur = con.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


@st.cache_data(ttl=600, max_entries=30)
def listar_grados():
    return leer_df("SELECT * FROM grados ORDER BY nombre").to_dict("records")


@st.cache_data(ttl=600, max_entries=30)
def listar_turnos():
    return leer_df("SELECT * FROM turnos ORDER BY id").to_dict("records")


@st.cache_data(ttl=600, max_entries=30)
def listar_ventanas():
    return leer_df(
        "SELECT * FROM ventanas WHERE activo=1 ORDER BY turno_id, orden"
    ).to_dict("records")


# ═══════════════════════════════════════════════════════════════════
# COMPATIBILIDAD CON asistencia.py ORIGINAL
# ═══════════════════════════════════════════════════════════════════
from contextlib import contextmanager
from datetime import datetime, date, time


@contextmanager
def cursor(dict_rows=True):
    con = obtener_conexion()
    cur = con.cursor()
    try:
        yield con, cur
    except Exception:
        try:
            con.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            con.commit()
        except Exception:
            pass


def to_time(v):
    if v is None or v == "":
        return None
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, datetime):
        return v.strftime("%H:%M")
    return str(v)[:5]


def to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def to_ts(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:19]


def fmt_time(v, con_seg=False):
    if v is None:
        return ""
    if isinstance(v, time):
        return v.strftime("%H:%M:%S" if con_seg else "%H:%M")
    if isinstance(v, datetime):
        return v.strftime("%H:%M:%S" if con_seg else "%H:%M")
    s = str(v)
    return s[:8] if con_seg else (s[:5] if len(s) >= 5 else s)


def fmt_date(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def fmt_ts(v):
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)[:19]
