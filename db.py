# db.py — NEON (PostgreSQL)
import streamlit as st
import pandas as pd
import logging
from datetime import datetime, date, time
from sqlalchemy import text

log = logging.getLogger("db")

@st.cache_resource
def _get_conn():
    return st.connection("neon", type="sql")

def obtener_conexion():
    return _get_conn()

def mantener_neon_despierto():
    """Hace un SELECT 1 a Neon para que no entre en modo suspensión."""
    try:
        conn = _get_conn()
        with conn.session as s:
            s.execute(text("SELECT 1"))
    except Exception as e:
        log.warning(f"Keep-alive falló: {e}")

def escribir(sql, params=()):
    conn = _get_conn()
    sql_pg = sql.replace("?", "%s")
    with conn.session as s:
        s.execute(text(sql_pg), params)
        s.commit()

def leer_df(sql, params=()):
    conn = _get_conn()
    sql_pg = sql.replace("?", "%s")
    try:
        with conn.session as s:
            result = s.execute(text(sql_pg), params)
            rows = result.fetchall()
            if not rows:
                return pd.DataFrame()
            
            # Imprimir qué tipo de dato es realmente la fila
            log.info(f"Tipo de fila: {type(rows[0])}")
            log.info(f"Contenido de fila: {rows[0]}")
            
            # Forzar la conversión a diccionario
            datos = []
            for r in rows:
                if hasattr(r, '_mapping'):
                    datos.append(dict(r._mapping))
                elif isinstance(r, tuple):
                    datos.append(dict(zip(result.keys(), r)))
                else:
                    datos.append(dict(r))
                    
            return pd.DataFrame(datos)
    except Exception as e:
        log.error(f"Error en leer_df: {e}")
        return pd.DataFrame()
def to_time(v): return v.strftime("%H:%M") if isinstance(v, (time, datetime)) else str(v)[:5]
def to_date(v): return v.strftime("%Y-%m-%d") if isinstance(v, (date, datetime)) else str(v)[:10]
def to_ts(v): return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else str(v)[:19]
def fmt_time(v, con_seg=False): return to_time(v) if v else ""
def fmt_date(v): return to_date(v) if v else ""
def fmt_ts(v): return to_ts(v) if v else ""

@st.cache_data(ttl=600, max_entries=30)
def listar_grados(): return leer_df("SELECT * FROM grados ORDER BY nombre").to_dict("records")
@st.cache_data(ttl=600, max_entries=30)
def listar_turnos(): return leer_df("SELECT * FROM turnos ORDER BY id").to_dict("records")
@st.cache_data(ttl=600, max_entries=30)
def listar_ventanas(): return leer_df("SELECT * FROM ventanas WHERE activo=1 ORDER BY turno_id, orden").to_dict("records")
