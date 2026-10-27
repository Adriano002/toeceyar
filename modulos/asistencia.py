# modulos/asistencia.py — PARTE 1/12
import streamlit as st
import pandas as pd
import qrcode
import re
import secrets
import logging
import base64
from io import BytesIO
from datetime import datetime, timedelta, date
from calendar import monthrange
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                 SimpleDocTemplate, Spacer, Table, TableStyle)

from db import escribir, leer_df, listar_grados, listar_turnos, listar_ventanas, obtener_conexion
from utils import (ahora, hoy_str, hora_corta, timestamp_str,
                   mask_dni, hashear_password, verificar_password,
                   df_a_xlsx, generar_pdf_tabla_ancha)
from components.qr_scanner import qr_scanner, reset_qr

log = logging.getLogger("asistencia")

MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

PUNTUAL = "Puntual"
TARDANZA = "Tardanza"
FALTA = "Falta"
PERMISO = "Permiso"
REF_ASISTIO = "Asistio"
ACC_PERDONADO = "PERDONADO"
ACC_DERIVADO = "DERIVADO_DIRECCION"

VENT_CLASES = "clases"
VENT_REF = "reforzamiento"
TIPO_ASIST_EVENTO = "evento"

MAX_DIAS_PERMISO = 7
HORAS_CIERRE_EVENTO = 2
LIMITE_NUEVO = 3
LIMITE_REINCIDENTE = 1

C_PRIMARIO = "#B85C38"


def _nombre_completo(a):
    return (a['apellido_paterno'] + " " + (a['apellido_materno'] or "") +
            ", " + a['nombres']).strip(", ")


def _ip():
    try:
        return st.context.headers.get("X-Forwarded-For", "local")
    except Exception:
        return "local"


def auditar(usuario, accion, va=None, vn=None, tb=None, rid=None):
    try:
        escribir("INSERT INTO auditoria(usuario,accion,fecha,valor_anterior,"
                 "valor_nuevo,tabla_afectada,registro_id,ip) "
                 "VALUES(?,?,?,?,?,?,?,?)",
                 (usuario, accion, timestamp_str(), va, vn, tb, rid, _ip()))
    except Exception as e:
        log.warning("audit: %s", e)


def confirmar_accion(clave, texto_boton="Confirmar",
                     texto_check="¿Estás seguro de hacer esta acción?",
                     tipo_boton="primary"):
    check = st.checkbox(texto_check, key=f"conf_{clave}")
    if st.button(texto_boton, type=tipo_boton, key=f"btn_conf_{clave}",
                 disabled=not check):
        return True
    return False


def calcular_limite(es_reincidente):
    return LIMITE_REINCIDENTE if es_reincidente else LIMITE_NUEVO


def _safe_df(fn, default_cols=None):
    try:
        df = fn()
        if df is None:
            return pd.DataFrame(columns=default_cols or [])
        return df
    except Exception as e:
        log.warning("_safe_df: %s", e)
        return pd.DataFrame(columns=default_cols or [])


def aplicar_estilos():
    st.markdown("""
    <style>
    :root{
        --primario: #E87B4A;
        --primario-dark: #D66535;
        --primario-soft: rgba(232,123,74,.15);
        --primario-borde: rgba(232,123,74,.35);
        --texto-titulo: #C4562A;
        --radius: 12px;
        --radius-sm: 8px;
        --sombra: 0 2px 8px rgba(0,0,0,.06);
    }
    @media (prefers-color-scheme: dark){
        :root{
            --primario: #F08A5C;
            --primario-dark: #E87B4A;
            --primario-soft: rgba(240,138,92,.20);
            --primario-borde: rgba(240,138,92,.45);
            --texto-titulo: #F5A582;
        }
    }
    h1, h2, h3 { color: var(--texto-titulo) !important; font-weight: 800 !important; }
    .stButton > button, .stFormSubmitButton > button {
        background: var(--primario) !important;
        color: #FFF !important;
        border-radius: var(--radius-sm) !important;
        font-weight: 700 !important;
        border: none !important;
        padding: 10px 20px !important;
    }
    .stButton > button:hover { background: var(--primario-dark) !important; }
    div[data-testid="stMetric"] {
        background: var(--primario-soft);
        border: 1px solid var(--primario-borde);
        border-radius: var(--radius);
        padding: 16px 20px !important;
    }
    div[data-testid="stMetricValue"] { color: var(--texto-titulo) !important; font-weight: 800 !important; }
    .perfil-hero {
        background: linear-gradient(135deg, var(--primario), var(--primario-dark));
        border-radius: 14px; padding: 26px 30px; margin-bottom: 22px;
        color: #FFF; display: flex; align-items: center; gap: 22px; flex-wrap: wrap;
    }
    .perfil-hero .hero-avatar {
        width: 84px; height: 84px; border-radius: 50%;
        background: rgba(255,255,255,.20); border: 2px solid rgba(255,255,255,.45);
        display: flex; align-items: center; justify-content: center;
        font-size: 34px; font-weight: 800; color: #FFF;
    }
    .perfil-hero .hero-nombre { font-size: 24px; font-weight: 800; color: #FFF !important; }
    .perfil-hero .hero-meta { font-size: 14px; opacity: .95; color: #FFF !important; }
    .perfil-hero .hero-badge {
        display: inline-block; margin-top: 10px; padding: 4px 14px;
        border-radius: 20px; font-size: 10px; font-weight: 800;
        text-transform: uppercase; background: rgba(255,255,255,.25);
        color: #FFF !important;
    }
    .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 14px; }
    .kpi-card {
        background: var(--primario-soft); border: 1px solid var(--primario-borde);
        border-radius: 10px; padding: 16px 12px; text-align: center;
    }
    .kpi-card .kpi-num { font-size: 30px; font-weight: 800; color: var(--texto-titulo); }
    .kpi-card .kpi-lbl { font-size: 11px; font-weight: 800; text-transform: uppercase; opacity: 0.75; }
    .kpi-card .kpi-lbl-alerta { color: #C62828; opacity: 1; }
    .qr-msg { padding: 16px 20px; border-radius: 8px; margin: 10px 0;
              border: 1px solid rgba(128,128,128,.15); border-left: 5px solid #808080; }
    .qr-puntual { border-left-color: #22C55E; background: rgba(34,197,94,.06); }
    .qr-tardanza { border-left-color: #F59E0B; background: rgba(245,158,11,.06); }
    .qr-bloqueado { border-left-color: #EF4444; border: 2px solid #EF4444; background: rgba(239,68,68,.10); }
    </style>
    """, unsafe_allow_html=True)


def enrutar(opcion):
    aplicar_estilos()
    if opcion == "Puerta":
        vista_puerta()
    elif opcion == "Alumnos":
        vista_alumnos()
    elif opcion == "Panel Direccion":
        vista_panel_direccion()
    elif opcion == "Carnets":
        vista_carnets()
    elif opcion == "Justificaciones":
        vista_justificaciones_permisos()
    elif opcion == "Reportes":
        vista_reportes()
    elif opcion == "Reportes Avanzados":
        vista_reportes_avanzados()
    elif opcion == "Bloqueados":
        vista_bloqueados()
    elif opcion == "Dias especiales":
        vista_dias_especiales_avanzado()
    elif opcion == "Ventanas":
        vista_ventanas()
    elif opcion == "Usuarios":
        vista_usuarios()
    elif opcion == "Auditoria":
        vista_auditoria()
    elif opcion == "Mi cuenta":
        vista_mi_cuenta()
    elif opcion == "Grados y Secciones":
        vista_grados_secciones()
    elif opcion == "Periodos":
        vista_periodos()
    elif opcion == "Mantenimiento":
        vista_mantenimiento()
    elif opcion == "Backup":
        vista_backup()


def vista_reportes_avanzados():
    st.title("📊 Reportes Avanzados")
    tabs = st.tabs([
        "General por auxiliar",
        "Cierre mensual PDF",
        "Reporte diario PDF",
    ])
    with tabs[0]:
        vista_reporte_general_auxiliar()
    with tabs[1]:
        vista_cierre_mensual_pdf()
    with tabs[2]:
        vista_reporte_diario_pdf()


def _ventana_activa(turno_id, fecha):
    if not turno_id:
        return None
    h = hora_corta()
    df = leer_df("SELECT * FROM ventanas WHERE turno_id=? AND activo=1 ORDER BY orden", (turno_id,))
    for _, v in df.iterrows():
        if v["hora_apertura"] <= h <= v["hora_cierre"]:
            return v.to_dict()
    return None


def _dia_especial_hoy(fecha):
    df = leer_df("SELECT * FROM dias_especiales WHERE fecha=? AND activo=1", (str(fecha),))
    if df.empty:
        return None
    feriado = df[df["tipo"] == "feriado"]
    if not feriado.empty:
        return feriado.iloc[0].to_dict()
    evento = df[df["tipo"] == "evento"]
    if not evento.empty:
        return evento.iloc[0].to_dict()
    return None


def obtener_periodo_activo():
    df = leer_df("SELECT * FROM periodos WHERE activo=1 LIMIT 1")
    return df.iloc[0].to_dict() if not df.empty else None


def periodo_tiene_alumnos(pid):
    df = leer_df("SELECT COUNT(*) AS n FROM alumnos WHERE periodo_id=? AND activo=1", (pid,))
    return int(df.iloc[0]["n"]) > 0 if not df.empty else False


def sistema_bloqueado():
    p = obtener_periodo_activo()
    return not p or not periodo_tiene_alumnos(p["id"])


def listar_periodos():
    return leer_df("SELECT id,nombre,fecha_inicio,fecha_fin,activo,cerrado FROM periodos ORDER BY id DESC")


def info_periodo_con_alumnos():
    return leer_df("""
        SELECT p.id, p.nombre, p.fecha_inicio, p.fecha_fin, p.activo, p.cerrado,
               (SELECT COUNT(*) FROM alumnos a WHERE a.periodo_id=p.id AND a.activo=1) AS alumnos_activos,
               (SELECT COUNT(*) FROM alumnos a WHERE a.periodo_id=p.id) AS alumnos_total
        FROM periodos p ORDER BY p.id DESC
    """)


def activar_periodo(idp, usuario):
    df = leer_df("SELECT cerrado FROM periodos WHERE id=?", (idp,))
    if df.empty:
        return False, "Periodo no encontrado."
    if int(df.iloc[0]["cerrado"]):
        return False, "Ese periodo está cerrado."
    escribir("UPDATE periodos SET activo=0")
    escribir("UPDATE periodos SET activo=1 WHERE id=?", (idp,))
    auditar(usuario["usuario"], f"Activo periodo id={idp}", tb="periodos", rid=idp)
    return True, "Periodo activado."


def crear_periodo_manual(nombre, fecha_inicio, fecha_fin, usuario):
    try:
        escribir("UPDATE periodos SET activo = 0")
        escribir("INSERT INTO periodos(nombre, fecha_inicio, fecha_fin, activo, cerrado) VALUES(?, ?, ?, 1, 0)",
                 (nombre, str(fecha_inicio), str(fecha_fin)))
        auditar(usuario["usuario"], f"Creó periodo manual: {nombre}")
        return True, "Periodo creado y activado correctamente."
    except Exception as e:
        return False, f"Error al crear periodo: {e}"


def cerrar_anio_escolar(usuario, pid, nuevo_nombre, fi, ff):
    df = leer_df("SELECT * FROM periodos WHERE id=?", (pid,))
    if df.empty:
        return False, "Periodo no encontrado."
    p = df.iloc[0].to_dict()
    if int(p.get("cerrado", 0)):
        return False, "Ese periodo ya está cerrado."
    fecha_cierre = timestamp_str()
    escribir("INSERT INTO cierres_anuales(periodo_id, fecha_cierre, generado_por) VALUES(?, ?, ?)",
             (pid, fecha_cierre, usuario["usuario"]))
    escribir("UPDATE periodos SET activo=0, fecha_cierre=?, cerrado=1 WHERE id=?", (fecha_cierre, pid))
    escribir("UPDATE alumnos SET activo=0, retirado_en=? WHERE periodo_id=?", (fecha_cierre, pid))
    escribir("INSERT INTO periodos(nombre, fecha_inicio, fecha_fin, activo, cerrado) VALUES(?, ?, ?, 1, 0)",
             (nuevo_nombre, str(fi), str(ff)))
    auditar(usuario["usuario"], f"Cerró periodo {p['nombre']}", tb="periodos", rid=pid)
    return True, f"Periodo '{p['nombre']}' cerrado. Nuevo: '{nuevo_nombre}'."


def listar_cierres_anuales():
    return leer_df("""
        SELECT c.id, p.nombre AS periodo, c.fecha_cierre, c.generado_por
        FROM cierres_anuales c JOIN periodos p ON c.periodo_id = p.id
        ORDER BY c.id DESC
    """)

# modulos/asistencia.py — PARTE 3/12


def _fecha_ultimo_desbloqueo(idal):
    df = leer_df("""
        SELECT fecha_fin FROM bloqueos WHERE alumno_id=? AND activo=0 AND fecha_fin IS NOT NULL
        ORDER BY fecha_fin DESC LIMIT 1
    """, (idal,))
    return df.iloc[0]["fecha_fin"] if not df.empty else None


def _es_reincidente(idal):
    return _fecha_ultimo_desbloqueo(idal) is not None


def contar_tardanzas_desde_ultimo_desbloqueo(idal):
    desde = _fecha_ultimo_desbloqueo(idal)
    if desde is None:
        df = leer_df("""
            SELECT COUNT(*) AS n FROM tardanzas WHERE alumno_id=? AND justificada=0
            AND periodo_id=(SELECT id FROM periodos WHERE activo=1 LIMIT 1)
        """, (idal,))
    else:
        df = leer_df("SELECT COUNT(*) AS n FROM tardanzas WHERE alumno_id=? AND justificada=0 AND fecha > ?",
                     (idal, str(desde)[:10]))
    return int(df.iloc[0]["n"]) if not df.empty else 0


def contar_tardanzas_injustificadas(idal):
    df = leer_df("SELECT COUNT(*) AS n FROM tardanzas WHERE alumno_id=? AND justificada=0", (idal,))
    return int(df.iloc[0]["n"]) if not df.empty else 0


def alumno_bloqueado(idal):
    df = leer_df("SELECT * FROM bloqueos WHERE alumno_id=? AND activo=1 ORDER BY id DESC LIMIT 1", (idal,))
    return df.iloc[0].to_dict() if not df.empty else None


def crear_bloqueo(idal, motivo, usuario, origen="automatico"):
    escribir("INSERT INTO bloqueos(alumno_id,motivo,activo,fecha_inicio,creado_por,origen) VALUES(?,?,1,?,?,?)",
             (idal, motivo, hoy_str(), usuario["usuario"], origen))
    auditar(usuario["usuario"], f"Bloqueo {origen} alumno_id={idal}", tb="bloqueos", rid=idal)


def liberar_bloqueo(idal, usuario, obs=""):
    escribir("UPDATE bloqueos SET activo=0,fecha_fin=?,liberado_por=? WHERE alumno_id=? AND activo=1",
             (timestamp_str(), usuario["usuario"], idal))
    auditar(usuario["usuario"], f"Libero bloqueo alumno_id={idal}. Obs: {obs}", tb="bloqueos", rid=idal)


def historial_bloqueos_alumno(idal):
    return leer_df("SELECT id, motivo, activo, fecha_inicio, fecha_fin, creado_por, origen, liberado_por FROM bloqueos WHERE alumno_id=? ORDER BY id DESC", (idal,))


def listar_bloqueados():
    return leer_df("""
        SELECT b.id, a.id AS alumno_id, a.dni,
        a.apellido_paterno||' '||COALESCE(a.apellido_materno,'')||', '||a.nombres AS alumno,
        g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno,
        b.motivo, b.fecha_inicio, COALESCE(b.origen,'automatico') AS origen
        FROM bloqueos b
        JOIN alumnos a ON b.alumno_id = a.id
        LEFT JOIN secciones s ON a.seccion_id = s.id
        LEFT JOIN grados g ON s.grado_id = g.id
        LEFT JOIN turnos t ON s.turno_id = t.id
        WHERE b.activo = 1 ORDER BY b.fecha_inicio DESC
    """)

# modulos/asistencia.py — PARTE 4/12


def hay_permiso_activo(idal, fecha):
    df = leer_df("SELECT id FROM permisos WHERE alumno_id=? AND activo=1 AND fecha_inicio<=? AND fecha_fin>=? LIMIT 1",
                 (idal, str(fecha), str(fecha)))
    return not df.empty


def _aplicar_just_prev(idal, fecha, tipo):
    df = leer_df("SELECT id FROM justificaciones_previas WHERE alumno_id=? AND fecha_objetivo=? AND tipo=? AND aplicada=0",
                 (idal, str(fecha), tipo))
    if not df.empty:
        escribir("UPDATE justificaciones_previas SET aplicada=1 WHERE id=?", (int(df.iloc[0]["id"]),))
        return True
    return False


def _puede_justificar(fecha_objetivo_str, tipo_asistencia=None, ventana_id=None):
    try:
        f_obj = datetime.strptime(fecha_objetivo_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False, "Fecha inválida."
    if tipo_asistencia and tipo_asistencia != FALTA:
        return False, "Solo se pueden justificar FALTAS."
    hoy = ahora().date()
    diff = (hoy - f_obj).days
    if diff > 0: return False, "Ya pasó la ventana."
    if diff < -2: return False, "Solo se puede justificar hasta pasado mañana."
    return True, ""


def crear_justificacion_previa(idal, fecha_obj, tipo, motivo, usuario):
    if tipo != FALTA: return False, "Solo se pueden registrar justificaciones para FALTAS."
    ok, msg = _puede_justificar(fecha_obj, tipo_asistencia=FALTA)
    if not ok: return False, msg
    if not motivo or not motivo.strip(): return False, "El motivo es obligatorio."
    df = leer_df("SELECT id FROM justificaciones_previas WHERE alumno_id=? AND fecha_objetivo=?", (idal, fecha_obj))
    if not df.empty: return False, "Ya existe una justificación para ese alumno en esa fecha."
    escribir("""INSERT INTO justificaciones_previas(alumno_id, fecha_objetivo, tipo, motivo, creado_por, timestamp, aplicada)
                VALUES(?, ?, ?, ?, ?, ?, 0)""",
             (idal, fecha_obj, FALTA, motivo.strip(), usuario["usuario"], timestamp_str()))
    auditar(usuario["usuario"], f"Creo justificación previa {fecha_obj} id={idal}", tb="justificaciones_previas", rid=idal)
    return True, "Justificación registrada."


def anular_justificacion_previa(id_just, usuario, motivo_anulacion=""):
    df = leer_df("SELECT jp.id, jp.alumno_id, jp.fecha_objetivo, jp.tipo, COALESCE(jp.motivo,'') AS motivo, jp.aplicada FROM justificaciones_previas jp WHERE jp.id=?", (id_just,))
    if df.empty: return False, "Justificación previa no encontrada."
    just = df.iloc[0].to_dict()
    if int(just["aplicada"]) == -1: return False, "Esta justificación previa ya estaba anulada."
    if int(just["aplicada"]) == 1: return False, "Esta justificación ya fue aplicada y no se puede anular."
    escribir("UPDATE justificaciones_previas SET aplicada=-1 WHERE id=?", (id_just,))
    auditar(usuario["usuario"], f"Anuló justificación previa id={id_just}" + (f" | Motivo: {motivo_anulacion.strip()}" if motivo_anulacion.strip() else ""), tb="justificaciones_previas", rid=id_just)
    return True, "Justificación previa anulada."


def reactivar_justificacion_previa(id_just, usuario, motivo_nuevo=""):
    df = leer_df("SELECT jp.id, jp.aplicada, COALESCE(jp.motivo,'') AS motivo FROM justificaciones_previas jp WHERE jp.id=?", (id_just,))
    if df.empty: return False, "Justificación previa no encontrada."
    just = df.iloc[0].to_dict()
    if int(just["aplicada"]) != -1: return False, "Esta justificación no está anulada."
    motivo_final = (motivo_nuevo.strip() if motivo_nuevo and motivo_nuevo.strip() else just["motivo"])
    escribir("UPDATE justificaciones_previas SET aplicada=0, motivo=? WHERE id=?", (motivo_final, id_just))
    auditar(usuario["usuario"], f"Reactivo justificación previa id={id_just}", tb="justificaciones_previas", rid=id_just)
    return True, "Justificación reactivada (pendiente)."


def crear_permiso(idal, fi, ff, motivo, usuario):
    try:
        fi_d = datetime.strptime(fi, "%Y-%m-%d").date()
        ff_d = datetime.strptime(ff, "%Y-%m-%d").date()
    except (ValueError, TypeError): return False, "Fechas inválidas."
    hoy = ahora().date()
    if fi_d < hoy + timedelta(days=1): return False, "El permiso solo puede empezar desde mañana."
    if ff_d < fi_d: return False, "Fecha fin anterior a inicio."
    dias = (ff_d - fi_d).days + 1
    if dias > MAX_DIAS_PERMISO: return False, f"El permiso no puede exceder {MAX_DIAS_PERMISO} días."
    if not motivo or not motivo.strip(): return False, "Motivo obligatorio."
    df = leer_df("SELECT id FROM permisos WHERE alumno_id=? AND activo=1 AND NOT (fecha_fin < ? OR fecha_inicio > ?)", (idal, fi, ff))
    if not df.empty: return False, "El alumno ya tiene un permiso que se solapa."
    periodo = leer_df("SELECT id FROM periodos WHERE activo=1 LIMIT 1")
    pid = int(periodo.iloc[0]["id"]) if not periodo.empty else None
    escribir("""INSERT INTO permisos(alumno_id, fecha_inicio, fecha_fin, motivo, creado_por, timestamp, activo, periodo_id)
                VALUES(?, ?, ?, ?, ?, ?, 1, ?)""",
             (idal, fi, ff, motivo.strip(), usuario["usuario"], timestamp_str(), pid))
    auditar(usuario["usuario"], f"Creo permiso {fi} a {ff} id={idal}", tb="permisos", rid=idal)
    return True, f"Permiso registrado del {fi} al {ff}."


def eliminar_permiso(id_permiso, usuario, motivo_eliminacion=""):
    df = leer_df("SELECT * FROM permisos WHERE id=? AND activo=1", (id_permiso,))
    if df.empty: return False, "Permiso no encontrado o ya anulado."
    perm = df.iloc[0].to_dict()
    aplicar = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE alumno_id=? AND fecha BETWEEN ? AND ? AND estado='Permiso'", (perm["alumno_id"], perm["fecha_inicio"], perm["fecha_fin"]))
    if int(aplicar.iloc[0]["n"]) > 0: return False, "Este permiso ya fue aplicado y no se puede anular."
    escribir("UPDATE permisos SET activo=0 WHERE id=?", (id_permiso,))
    auditar(usuario["usuario"], f"Anuló permiso id={id_permiso}", tb="permisos", rid=id_permiso)
    return True, "Permiso anulado."

# modulos/asistencia.py — PARTE 5/12


def registrar_entrada(dni, usuario, origen="qr"):
    dni = (dni or "").strip()
    if not re.fullmatch(r"\d{8}", dni): return False, "ERROR", "DNI inválido", {}
    df_al = leer_df("""
        SELECT a.*, g.nombre AS grado, s.nombre AS seccion, s.id AS seccion_id,
               t.nombre AS turno, t.id AS turno_id
        FROM alumnos a
        LEFT JOIN secciones s ON a.seccion_id = s.id
        LEFT JOIN grados g ON s.grado_id = g.id
        LEFT JOIN turnos t ON s.turno_id = t.id
        WHERE a.dni=? AND a.activo=1
    """, (dni,))
    if df_al.empty: return False, "ERROR", "DNI no encontrado", {}
    al = df_al.iloc[0].to_dict()

    bloq = alumno_bloqueado(al["id"])
    if bloq:
        auditar(usuario["usuario"], "Intento escaneo bloqueado DNI " + dni, tb="bloqueos", rid=al["id"])
        return False, "BLOQUEADO", (_nombre_completo(al) + " | BLOQUEADO - retener y llevar a Dirección"), {"alumno": al, "motivo": bloq["motivo"]}

    reincidente = _es_reincidente(al["id"])
    limite = calcular_limite(reincidente)
    n_previas = contar_tardanzas_desde_ultimo_desbloqueo(al["id"])
    if n_previas >= limite:
        crear_bloqueo(al["id"], f"{n_previas} tardanza(s) acumulada(s) - reincidente={reincidente}", usuario, "automatico")
        return False, "BLOQUEADO", (_nombre_completo(al) + " | BLOQUEADO (límite alcanzado)"), {"alumno": al, "motivo": "límite alcanzado"}

    fecha = hoy_str()
    hora = hora_corta()
    dia = _dia_especial_hoy(fecha)
    if dia and dia.get("tipo") == "feriado": return False, "ERROR", "Hoy es feriado, no se registra", {}
    periodo = leer_df("SELECT id FROM periodos WHERE activo=1 LIMIT 1")
    pid = int(periodo.iloc[0]["id"]) if not periodo.empty else None
    ventana = _ventana_activa(al.get("turno_id"), fecha)
    if not ventana: return False, "ERROR", (_nombre_completo(al) + " | Sin ventana activa (" + hora + ")"), {"alumno": al}

    df_ast = leer_df("SELECT id, estado FROM asistencias WHERE alumno_id=? AND fecha=? AND tipo='clases'", (al["id"], fecha))
    if not df_ast.empty: return False, "ERROR", (_nombre_completo(al) + f" ya registró hoy ({df_ast.iloc[0]['estado']})"), {}

    limite_hora = ventana.get("hora_limite_puntual") or ventana["hora_apertura"]
    estado = PUNTUAL if hora <= limite_hora else TARDANZA
    permiso = hay_permiso_activo(al["id"], fecha)
    escribir("""INSERT INTO asistencias(alumno_id, fecha, ventana_id, tipo, hora, estado, justificada, origen, periodo_id)
                VALUES(?, ?, ?, 'clases', ?, ?, ?, ?, ?)""",
             (al["id"], fecha, ventana["id"], hora, estado, 1 if permiso else 0, origen, pid))

    if estado == TARDANZA:
        n = n_previas + 1
        accion = ACC_PERDONADO if n < limite else ACC_DERIVADO
        escribir("""INSERT INTO tardanzas(alumno_id, fecha, hora, numero, accion, justificada, origen, registrado_por, timestamp, periodo_id)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (al["id"], fecha, hora, n, accion, 1 if permiso else 0, origen, usuario["usuario"], timestamp_str(), pid))
        auditar(usuario["usuario"], f"Tardanza {n}a DNI {dni} -> {accion}", tb="tardanzas")
        alcanzo = (n >= limite)
        msg = (_nombre_completo(al) + " | " + (al["grado"] or "") + " " + (al["seccion"] or "") + f" | Tardanza {n}a ({accion}) {hora}")
        if alcanzo: msg += " | ⚠️ MAÑANA NO PODRÁ ESCANEAR"
        return True, "TARDANZA", msg, {"alumno": al, "numero": n, "accion": accion, "alcanzo_limite": alcanzo}

    auditar(usuario["usuario"], f"Entrada Puntual {origen} DNI {dni}", tb="asistencias")
    return True, "PUNTUAL", (_nombre_completo(al) + " | " + (al["grado"] or "") + " " + (al["seccion"] or "") + " | Puntual " + hora), {"alumno": al}

# modulos/asistencia.py — PARTE 6/12


def vista_puerta():
    usuario = st.session_state["user"]
    st.title("🚪 Control de Puerta")
    st.caption(f"Fecha: {hoy_str()} — Hora: {hora_corta()}")
    dia = _dia_especial_hoy(hoy_str())
    if dia:
        if dia.get("tipo") == "feriado":
            st.error(f"🚫 Hoy es FERIADO: {dia.get('descripcion') or ''}")
            return
        elif dia.get("tipo") == "evento":
            st.info(f"📅 Evento hoy: {dia.get('descripcion')} — Entrada: {dia.get('hora_entrada')}")

    bloqueados = listar_bloqueados()
    if not bloqueados.empty:
        st.warning(f"⚠️ {len(bloqueados)} alumnos bloqueados")
        with st.expander("Ver bloqueados"):
            st.dataframe(bloqueados, use_container_width=True, hide_index=True)

    st.subheader("Escanea el QR del alumno")
    result = qr_scanner(key="puerta")
    if result and result.get("qr_dni"):
        dni = result["qr_dni"]
        ok, tipo, msg, extra = registrar_entrada(dni, usuario, "qr")
        if tipo == "PUNTUAL": st.success(f"✅ {msg}")
        elif tipo == "TARDANZA": st.warning(f"⚠️ {msg}")
        elif tipo == "BLOQUEADO":
            st.error(f"🚫 {msg}")
            alumno = extra.get("alumno")
            if alumno:
                st.session_state["_bloqueado_scan"] = alumno
        else: st.info(msg)
        reset_qr("puerta")
        st.rerun()

    if st.session_state.get("_bloqueado_scan"):
        alumno = st.session_state["_bloqueado_scan"]
        st.markdown("---")
        st.warning(f"¿Desbloquear a {alumno['nombres']}?")
        c1, c2 = st.columns(2)
        if c1.button("Sí, desbloquear", type="primary"):
            liberar_bloqueo(alumno["id"], usuario, "Desbloqueo desde escaneo")
            st.session_state.pop("_bloqueado_scan", None)
            reset_qr("puerta")
            st.rerun()
        if c2.button("No, mantener bloqueado"):
            st.session_state.pop("_bloqueado_scan", None)
            reset_qr("puerta")
            st.rerun()


def vista_bloqueados():
    st.title("🚫 Alumnos Bloqueados")
    usuario = st.session_state["user"]
    st.caption("Reglas: alumno nuevo → 3 tardanzas → bloqueo al día siguiente. Alumno reincidente → 1 tardanza → bloqueo al día siguiente.")
    df = listar_bloqueados()
    st.metric("Total bloqueados", len(df))
    if df.empty:
        st.success("No hay alumnos bloqueados actualmente.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.subheader("Desbloquear alumno")
    ops = {f"{r['alumno']} — DNI {r['dni']} — {r['grado']} {r['seccion']}": r["alumno_id"] for _, r in df.iterrows()}
    sel = st.selectbox("Alumno", list(ops.keys()))
    idal = ops[sel]
    al_df = leer_df("""SELECT a.*, g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno
                       FROM alumnos a LEFT JOIN secciones s ON a.seccion_id = s.id
                       LEFT JOIN grados g ON s.grado_id = g.id LEFT JOIN turnos t ON s.turno_id = t.id
                       WHERE a.id=?""", (idal,))
    al = al_df.iloc[0].to_dict()
    bloq = alumno_bloqueado(idal)
    if bloq:
        st.info(f"Motivo: **{bloq['motivo']}**")
        st.info(f"Fecha bloqueo: **{bloq['fecha_inicio']}**")
    with st.expander("Historial de bloqueos"):
        st.dataframe(historial_bloqueos_alumno(idal), use_container_width=True, hide_index=True)
    motivo = st.text_input("Motivo de desbloqueo (obligatorio)", key=f"mo_{idal}")
    if confirmar_accion(f"lib_{idal}", "Desbloquear alumno", "¿Estás seguro de desbloquear a este alumno?"):
        if not motivo.strip(): st.error("El motivo es obligatorio.")
        else:
            liberar_bloqueo(idal, usuario, motivo.strip())
            st.toast(f"Alumno {al['nombres']} desbloqueado.")
            st.rerun()

# modulos/asistencia.py — PARTE 7/12


def vista_panel_direccion():
    st.title("📊 Panel Dirección")
    fecha = hoy_str()
    total_al = leer_df("SELECT COUNT(*) AS n FROM alumnos WHERE activo=1")
    puntuales = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE fecha=? AND estado='Puntual'", (fecha,))
    tardanzas = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE fecha=? AND estado='Tardanza'", (fecha,))
    faltas = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE fecha=? AND estado='Falta'", (fecha,))
    bloqueados = leer_df("SELECT COUNT(*) AS n FROM bloqueos WHERE activo=1")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Alumnos", int(total_al.iloc[0]["n"]) if not total_al.empty else 0)
    c2.metric("Puntuales", int(puntuales.iloc[0]["n"]) if not puntuales.empty else 0)
    c3.metric("Tardanzas", int(tardanzas.iloc[0]["n"]) if not tardanzas.empty else 0)
    c4.metric("Faltas", int(faltas.iloc[0]["n"]) if not faltas.empty else 0)
    c5.metric("Bloqueados", int(bloqueados.iloc[0]["n"]) if not bloqueados.empty else 0)

    st.markdown("---")
    st.subheader("Métricas por turno")
    turnos = listar_turnos()
    for t in turnos:
        with st.expander(f"Turno {t['nombre']}"):
            df = leer_df("""SELECT COUNT(*) AS n FROM asistencias ast
                            JOIN alumnos a ON ast.alumno_id = a.id
                            JOIN secciones s ON a.seccion_id = s.id
                            WHERE ast.fecha = ? AND s.turno_id = ? AND ast.tipo='clases'""", (fecha, t["id"]))
            st.metric("Registros", int(df.iloc[0]["n"]) if not df.empty else 0)

    st.markdown("---")
    st.subheader("Últimos escaneos")
    df = leer_df("""SELECT a.apellido_paterno, a.nombres, ast.hora, ast.estado, ast.tipo
                    FROM asistencias ast JOIN alumnos a ON ast.alumno_id = a.id
                    WHERE ast.fecha = ? ORDER BY ast.hora DESC LIMIT 50""", (fecha,))
    if df.empty: st.info("Sin escaneos hoy")
    else: st.dataframe(df, use_container_width=True, hide_index=True)


def marcar_faltas_al_cierre():
    fecha = hoy_str()
    hora = hora_corta()
    periodo = leer_df("SELECT id FROM periodos WHERE activo=1 LIMIT 1")
    pid = int(periodo.iloc[0]["id"]) if not periodo.empty else None
    dia = _dia_especial_hoy(fecha)
    if dia and dia.get("tipo") == "feriado": return
    if ahora().weekday() >= 5: return
    for t in listar_turnos():
        for v in listar_ventanas(t["id"]):
            if hora < v["hora_cierre"]: continue
            tipo = "clases" if v["tipo"] == "clases" else "reforzamiento"
            est = "Falta" if v["tipo"] == "clases" else "No asistio"
            alumnos = leer_df("""SELECT a.id FROM alumnos a
                                 JOIN secciones s ON a.seccion_id = s.id
                                 WHERE s.turno_id=? AND a.activo=1""", (t["id"],))
            for _, al in alumnos.iterrows():
                existe = leer_df("SELECT id FROM asistencias WHERE alumno_id=? AND fecha=? AND tipo=?", (al["id"], fecha, tipo))
                if not existe.empty: continue
                if hay_permiso_activo(al["id"], fecha):
                    escribir("""INSERT INTO asistencias(alumno_id, fecha, ventana_id, tipo, hora, estado, justificada, observacion, origen, periodo_id)
                                VALUES(?, ?, ?, ?, ?, 'Permiso', 1, 'Permiso', 'manual', ?)""",
                             (al["id"], fecha, v["id"], tipo, hora, pid))
                    continue
                jp = _aplicar_just_prev(al["id"], fecha, "Falta") if v["tipo"] == "clases" else False
                escribir("""INSERT INTO asistencias(alumno_id, fecha, ventana_id, tipo, hora, estado, justificada, origen, periodo_id)
                            VALUES(?, ?, ?, ?, ?, ?, ?, 'auto', ?)""",
                         (al["id"], fecha, v["id"], tipo, hora, est, 1 if jp else 0, pid))

# modulos/asistencia.py — PARTE 8/12


def vista_alumnos():
    st.title("👨‍🎓 Alumnos")
    tabs = st.tabs(["Listar", "Crear", "Importar Excel", "Perfil"])
    with tabs[0]: _alumnos_listar()
    with tabs[1]: _alumnos_crear()
    with tabs[2]: _alumnos_importar()
    with tabs[3]: _perfil_alumno()


def _alumnos_listar():
    c1, c2, c3 = st.columns([3, 2, 2])
    with c1: texto = st.text_input("Buscar nombre o DNI", key="al_t")
    with c2: grado = st.text_input("Grado", key="al_g")
    with c3: seccion = st.text_input("Sección", key="al_s")
    q = """SELECT a.id, a.dni, a.nombres, a.apellido_paterno, a.apellido_materno,
                  g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno
           FROM alumnos a LEFT JOIN secciones s ON a.seccion_id = s.id
           LEFT JOIN grados g ON s.grado_id = g.id LEFT JOIN turnos t ON s.turno_id = t.id
           WHERE a.activo = 1"""
    p = []
    if texto:
        for w in texto.split():
            q += " AND (a.nombres LIKE ? OR a.apellido_paterno LIKE ? OR a.dni LIKE ?)"
            p += [f"%{w}%", f"%{w}%", f"%{w}%"]
    if grado: q += " AND g.nombre = ?"; p.append(grado)
    if seccion: q += " AND s.nombre = ?"; p.append(seccion)
    q += " ORDER BY a.apellido_paterno LIMIT 500"
    df = leer_df(q, p)
    st.write(f"**{len(df)} alumnos**")
    if not df.empty: st.dataframe(df, use_container_width=True, hide_index=True)


def _alumnos_crear():
    st.subheader("Crear alumno")
    c1, c2 = st.columns(2)
    with c1:
        dni = st.text_input("DNI *", max_chars=8, key="cr_dni")
        nombres = st.text_input("Nombres *", key="cr_nom")
        ap_pat = st.text_input("Apellido Paterno *", key="cr_pat")
    with c2:
        ap_mat = st.text_input("Apellido Materno", key="cr_mat")
        apoderado = st.text_input("Apoderado", key="cr_apo")
        telefono = st.text_input("Teléfono apoderado", key="cr_tel")
    if st.button("Crear alumno", type="primary"):
        if not dni or not nombres or not ap_pat: st.error("Completa DNI, nombres y apellido paterno")
        elif not re.fullmatch(r"\d{8}", dni): st.error("DNI inválido (8 dígitos)")
        else:
            try:
                escribir("""INSERT INTO alumnos(dni, nombres, apellido_paterno, apellido_materno, nombre_apoderado, telefono_apoderado)
                            VALUES(?, ?, ?, ?, ?, ?)""",
                         (dni, nombres, ap_pat, ap_mat or None, apoderado or None, telefono or None))
                st.success("Alumno creado")
                st.rerun()
            except Exception as e: st.error(f"Error: {e}")


def _alumnos_importar():
    st.subheader("Importar alumnos desde Excel")
    st.caption("Columnas: DNI, Nombres, Apellido Paterno, Apellido Materno, Grado, Sección, Turno, Apoderado, Teléfono")
    archivo = st.file_uploader("Sube Excel", type=["xlsx", "xls"], key="al_imp")
    if not archivo: return
    df = pd.read_excel(archivo)
    st.write(f"{len(df)} filas")
    st.dataframe(df.head(), use_container_width=True)
    if st.button("Importar todos", type="primary"):
        contador = 0
        for _, fila in df.iterrows():
            try:
                dni = str(fila.get("DNI", "")).strip()
                if not dni or len(dni) != 8: continue
                escribir("""INSERT OR IGNORE INTO alumnos(dni, nombres, apellido_paterno, apellido_materno, nombre_apoderado, telefono_apoderado)
                            VALUES(?, ?, ?, ?, ?, ?)""",
                         (dni, str(fila.get("Nombres", "")), str(fila.get("Apellido Paterno", "")),
                          str(fila.get("Apellido Materno", "")), str(fila.get("Apoderado", "")), str(fila.get("Teléfono", ""))))
                contador += 1
            except Exception as e: st.warning(f"Error en fila: {e}")
        st.success(f"{contador} alumnos importados")
        st.rerun()


def _perfil_alumno():
    st.subheader("Perfil de alumno")
    dni = st.text_input("DNI del alumno", key="perf_dni")
    if not dni or len(dni) != 8: return
    al_df = leer_df("""SELECT a.*, g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno
                       FROM alumnos a LEFT JOIN secciones s ON a.seccion_id = s.id
                       LEFT JOIN grados g ON s.grado_id = g.id LEFT JOIN turnos t ON s.turno_id = t.id
                       WHERE a.dni=? AND a.activo=1""", (dni,))
    if al_df.empty: st.error("Alumno no encontrado"); return
    al = al_df.iloc[0].to_dict()
    nombre = _nombre_completo(al)
    inicial = (al['apellido_paterno'] or al['nombres'] or "?")[0].upper()
    bloqueado = alumno_bloqueado(al["id"])
    badge = "BLOQUEADO" if bloqueado else "ACTIVO"
    st.markdown(f"""
    <div class="perfil-hero">
        <div class="hero-avatar">{inicial}</div>
        <div class="hero-info">
            <div class="hero-nombre">{nombre}</div>
            <div class="hero-meta">{al['grado'] or ''} {al['seccion'] or ''} | Turno {al['turno'] or '-'} | DNI {mask_dni(al['dni'])}</div>
            <span class="hero-badge">{badge}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    total_p = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE alumno_id=? AND estado='Puntual'", (al["id"],))
    total_t = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE alumno_id=? AND estado='Tardanza'", (al["id"],))
    total_f = leer_df("SELECT COUNT(*) AS n FROM asistencias WHERE alumno_id=? AND estado='Falta'", (al["id"],))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Puntuales", int(total_p.iloc[0]["n"]) if not total_p.empty else 0)
    c2.metric("Tardanzas", int(total_t.iloc[0]["n"]) if not total_t.empty else 0)
    c3.metric("Faltas", int(total_f.iloc[0]["n"]) if not total_f.empty else 0)
    c4.metric("Bloqueado", "SÍ" if bloqueado else "NO")
    st.markdown("---")
    st.subheader("Historial de asistencias")
    df_h = leer_df("""SELECT fecha, hora, estado, tipo FROM asistencias
                      WHERE alumno_id=? ORDER BY fecha DESC LIMIT 50""", (al["id"],))
    if not df_h.empty: st.dataframe(df_h, use_container_width=True, hide_index=True)
    else: st.info("Sin registros")  

# modulos/asistencia.py — PARTE 9/12


def _generar_fotocheck_pil(alumno, escudo_path=None):
    from PIL import Image, ImageDraw, ImageFont
    ANCHO_PX = 980
    ALTO_PX = 626
    NARANJA_OSCURO = (184, 92, 56)
    NARANJA_CLARO = (212, 132, 96)
    NARANJA_FRANJA = (184, 92, 56)
    FONDO = (255, 240, 225)
    BLANCO = (255, 255, 255)
    NEGRO = (17, 17, 17)
    GRIS_LABEL = (90, 60, 30)
    GRIS_TXT = (150, 150, 150)

    img = Image.new("RGB", (ANCHO_PX, ALTO_PX), FONDO)
    draw = ImageDraw.Draw(img)
    color_punto = (235, 210, 180)
    paso = 22
    for py in range(0, ALTO_PX, paso):
        for px in range(0, ANCHO_PX, paso):
            draw.ellipse([px - 1, py - 1, px + 1, py + 1], fill=color_punto)

    if escudo_path and Path(escudo_path).exists():
        try:
            esc = Image.open(str(escudo_path)).convert("RGBA").resize((300, 300), Image.LANCZOS)
            a = esc.split()[3]
            a = a.point(lambda p: int(p * 0.15))
            esc.putalpha(a)
            img.paste(esc, ((ANCHO_PX - 300) // 2 + 110, (ALTO_PX - 300) // 2), esc)
        except Exception: pass

    FOTO_W = 240
    FOTO_H = 310
    FRANJA_W = FOTO_W
    for y in range(ALTO_PX):
        t = y / ALTO_PX
        r = int(NARANJA_OSCURO[0] + (NARANJA_CLARO[0] - NARANJA_OSCURO[0]) * t)
        g = int(NARANJA_OSCURO[1] + (NARANJA_CLARO[1] - NARANJA_OSCURO[1]) * t)
        b = int(NARANJA_OSCURO[2] + (NARANJA_CLARO[2] - NARANJA_OSCURO[2]) * t)
        draw.line([(0, y), (FRANJA_W, y)], fill=(r, g, b))

    def _font(size, bold=False, italic=False):
        from pathlib import Path as _P
        ruta = _P(__file__).parent.parent / "arial.ttf"
        try: return ImageFont.truetype(str(ruta), size)
        except Exception:
            try:
                base = ImageFont.load_default()
                return base.font_variant(size=size)
            except Exception: return ImageFont.load_default()

    def _dibujar_texto(x, y, texto, font, color):
        draw.text((x, y), texto, fill=color, font=font)

    f_colegio = _font(19, bold=True)
    f_foto = _font(25, bold=True)
    f_titulo = _font(34, bold=True)
    f_frase = _font(28, bold=True, italic=True)
    f_label = _font(30, bold=True)

    esc_size = int(FRANJA_W * 0.75)
    esc_x = (FRANJA_W - esc_size) // 2
    espacio = ALTO_PX - FOTO_H
    alto_bloque_texto = 3 * 19
    alto_bloque_total = esc_size + 8 + alto_bloque_texto
    esc_y = max(10, (espacio - alto_bloque_total) // 2 + 6)

    if escudo_path and Path(escudo_path).exists():
        try:
            esc = Image.open(str(escudo_path)).convert("RGBA").resize((esc_size, esc_size), Image.LANCZOS)
            img.paste(esc, (esc_x, esc_y), esc)
        except Exception: pass

    def _txt_centrado(texto, y, font, color):
        try:
            bbox = draw.textbbox((0, 0), texto, font=font)
            tw = bbox[2] - bbox[0]
        except Exception: tw = len(texto) * 7.5
        _dibujar_texto((FRANJA_W - tw) // 2, y, texto, font, color)

    y_txt = esc_y + esc_size + 7
    for lbl in ["INSTITUCION", "EDUCATIVA", "YARINACOCHA"]:
        _txt_centrado(lbl, y_txt, f_colegio, BLANCO)
        y_txt += 19

    foto_x = 0
    foto_y = ALTO_PX - FOTO_H
    draw.rectangle([foto_x, foto_y, foto_x + FOTO_W, foto_y + FOTO_H], fill=BLANCO)
    draw.rectangle([foto_x, foto_y, foto_x + FOTO_W - 1, foto_y + FOTO_H - 1], outline=NARANJA_FRANJA, width=1)
    try:
        bbox = draw.textbbox((0, 0), "FOTO", font=f_foto)
        tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
    except Exception: tw, th = 42, 13
    draw.text((foto_x + (FOTO_W - tw) // 2, foto_y + (FOTO_H - th) // 2), "FOTO", fill=GRIS_TXT, font=f_foto)

    DER_X = FRANJA_W + 18
    titulo_txt = "FOTOCHECK DEL ESTUDIANTE"
    try:
        bbox = draw.textbbox((0, 0), titulo_txt, font=f_titulo)
        tw = bbox[2] - bbox[0]
    except Exception: tw = 300
    espacio_d = ANCHO_PX - DER_X
    _dibujar_texto(DER_X + (espacio_d - tw) // 2, 12, titulo_txt, f_titulo, NEGRO)

    ap_p = (alumno.get('apellido_paterno') or "").upper()
    ap_m = (alumno.get('apellido_materno') or "").upper()
    nombres = (alumno.get('nombres') or "").upper()
    dni = alumno["dni"]
    grado = (alumno.get('grado') or "").upper()
    seccion = (alumno.get('seccion') or "").upper()
    turno = (alumno.get('turno') or "").upper()
    ANIO = str(datetime.now().year)
    info_x = DER_X
    QR_SIZE = 225
    qr_x = ANCHO_PX - QR_SIZE - 12
    ancho_info = qr_x - info_x - 12

    def _ajustar(texto, size_ini, max_ancho, bold):
        size = size_ini
        while size > 10:
            f = _font(size, bold=bold)
            try: ancho = draw.textlength(texto, font=f)
            except Exception: ancho = len(texto) * size * 0.55
            if ancho <= max_ancho: return f
            size -= 1
        return _font(10, bold=bold)

    INFO_Y = 110
    alto_linea = 66
    ap_full = ap_p + " " + ap_m
    _dibujar_texto(info_x, INFO_Y, ap_full, _ajustar(ap_full, 48, ancho_info, True), NEGRO)
    y2 = INFO_Y + alto_linea
    _dibujar_texto(info_x, y2, nombres, _ajustar(nombres, 48, ancho_info, True), NEGRO)

    def _linea(y, label, valor, size=42):
        _dibujar_texto(info_x, y, label, f_label, GRIS_LABEL)
        an = draw.textlength(label, font=f_label)
        vx = info_x + int(an) + 10
        _dibujar_texto(vx, y, valor, _ajustar(valor, size, ancho_info - int(an) - 10, True), NEGRO)

    _linea(y2 + alto_linea, "DNI:", dni)
    _linea(y2 + 2 * alto_linea, "GRADO:", f'{grado} "{seccion}"')
    _linea(y2 + 3 * alto_linea, "TURNO:", turno)
    _linea(y2 + 4 * alto_linea, "PERIODO:", ANIO)

    qr = qrcode.QRCode(version=1, box_size=10, border=1)
    qr.add_data(str(alumno["dni"]).strip())
    qr.make(fit=True)
    qr_img_pil = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((QR_SIZE, QR_SIZE), Image.LANCZOS)
    img.paste(qr_img_pil, (qr_x, 70))

    frase = '"Ser del CNY, es ser mejor"'
    try:
        bbox = draw.textbbox((0, 0), frase, font=f_frase)
        fw = bbox[2] - bbox[0]
    except Exception: fw = 280
    _dibujar_texto(DER_X + (espacio_d - fw) // 2, ALTO_PX - 50, frase, f_frase, NARANJA_FRANJA)
    return img      

# modulos/asistencia.py — PARTE 10/12


def _render_carnets(filas, titulo=None):
    buf = BytesIO()
    m = 5
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=m, leftMargin=m, topMargin=m, bottomMargin=m)
    est = getSampleStyleSheet()
    MM = 2.8346
    ANCHO = 85.0 * MM
    ALTO = 53.0 * MM
    escudo_path = Path("escudo.png")

    def _fotocheck(alumno):
        img = _generar_fotocheck_pil(alumno, escudo_path if escudo_path.exists() else None)
        ib = BytesIO(); img.save(ib, format="PNG"); ib.seek(0)
        return RLImage(ib, width=ANCHO, height=ALTO)

    el = []
    if titulo:
        el.append(Paragraph(f"<b>{titulo}</b>", est["Heading2"]))
        el.append(Spacer(1, 6))
    sep_x = 6; sep_y = 10; caben_x = 2
    alto_hoja = A4[1] - 2 * m
    caben_y = max(1, int((alto_hoja + sep_y) // (ALTO + sep_y)))
    fotochecks = [_fotocheck(a) for a in filas]
    for i in range(0, len(fotochecks), caben_x * caben_y):
        lote = fotochecks[i:i + caben_x * caben_y]
        tabla_filas = []
        for j in range(0, len(lote), caben_x):
            fila = lote[j:j + caben_x]
            while len(fila) < caben_x: fila.append("")
            tabla_filas.append(fila)
        while len(tabla_filas) < caben_y: tabla_filas.append([""] * caben_x)
        t = Table(tabla_filas, colWidths=[ANCHO, ANCHO], rowHeights=[ALTO] * len(tabla_filas), hAlign="CENTER")
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), sep_x / 2), ("RIGHTPADDING", (0, 0), (-1, -1), sep_x / 2),
            ("TOPPADDING", (0, 0), (-1, -1), sep_y / 2), ("BOTTOMPADDING", (0, 0), (-1, -1), sep_y / 2),
        ]))
        el.append(t)
        if i + caben_x * caben_y < len(fotochecks): el.append(PageBreak())
    doc.build(el)
    buf.seek(0)
    return buf.getvalue()


def pdf_carnets_por_seccion(idsec):
    df = leer_df("""SELECT a.*, s.nombre AS seccion, g.nombre AS grado, t.nombre AS turno
                    FROM alumnos a JOIN secciones s ON a.seccion_id=s.id
                    JOIN grados g ON s.grado_id=g.id JOIN turnos t ON s.turno_id=t.id
                    WHERE a.seccion_id=? AND a.activo=1 ORDER BY a.apellido_paterno""", (idsec,))
    filas = [r.to_dict() for _, r in df.iterrows()]
    return _render_carnets(filas) if filas else None


def pdf_carnets_todos():
    df = leer_df("""SELECT a.*, s.nombre AS seccion, g.nombre AS grado, t.nombre AS turno
                    FROM alumnos a JOIN secciones s ON a.seccion_id=s.id
                    JOIN grados g ON s.grado_id=g.id JOIN turnos t ON s.turno_id=t.id
                    WHERE a.activo=1 ORDER BY t.nombre, g.nombre, s.nombre, a.apellido_paterno""")
    filas = [r.to_dict() for _, r in df.iterrows()]
    return _render_carnets(filas, "Carnets - Todos los salones") if filas else None


def vista_carnets():
    st.title("🎴 Carnets QR")
    tabs = st.tabs(["Todos", "Por sección", "Individual"])
    with tabs[0]:
        if st.button("Generar PDF de todos", type="primary"):
            with st.spinner("Generando PDF..."):
                pdf = pdf_carnets_todos()
            if pdf:
                st.download_button("Descargar PDF", pdf, "carnets_todos.pdf", "application/pdf", use_container_width=True)
            else: st.warning("No hay alumnos activos")
    with tabs[1]:
        grados = listar_grados()
        if grados:
            g = st.selectbox("Grado", grados, format_func=lambda x: x["nombre"])
            secs = leer_df("SELECT * FROM secciones WHERE grado_id=? ORDER BY nombre", (g["id"],))
            if not secs.empty:
                s = st.selectbox("Sección", secs.to_dict("records"), format_func=lambda x: x["nombre"])
                if st.button("Generar PDF de esta sección", type="primary"):
                    with st.spinner("Generando..."):
                        pdf = pdf_carnets_por_seccion(s["id"])
                    if pdf:
                        st.download_button("Descargar", pdf, f"carnets_{s['nombre']}.pdf", "application/pdf", use_container_width=True)
    with tabs[2]:
        dni = st.text_input("DNI del alumno", key="carnet_dni")
        if dni and len(dni) == 8:
            al_df = leer_df("""SELECT a.*, s.nombre AS seccion, g.nombre AS grado, t.nombre AS turno
                               FROM alumnos a LEFT JOIN secciones s ON a.seccion_id=s.id
                               LEFT JOIN grados g ON s.grado_id=g.id LEFT JOIN turnos t ON s.turno_id=t.id
                               WHERE a.dni=? AND a.activo=1""", (dni,))
            if not al_df.empty:
                pdf = _render_carnets([al_df.iloc[0].to_dict()])
                if pdf: st.download_button("Descargar carnet", pdf, f"carnet_{dni}.pdf", "application/pdf", use_container_width=True)
            else: st.error("Alumno no encontrado")


def vista_reportes():
    st.title("📈 Reportes")
    tabs = st.tabs(["Diario", "Mensual", "Por alumno", "General por turno", "PDF Multilhoja"])
    with tabs[0]:
        fecha = st.date_input("Fecha", value=ahora().date(), key="rep_dia")
        df = leer_df("""SELECT a.apellido_paterno, a.nombres, a.dni, ast.hora, ast.estado, ast.tipo
                        FROM asistencias ast JOIN alumnos a ON ast.alumno_id = a.id
                        WHERE ast.fecha = ? ORDER BY ast.hora DESC""", (str(fecha),))
        if df.empty: st.info("Sin asistencias ese día")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("Descargar Excel", df_a_xlsx(df, "Diario"), f"asistencias_{fecha}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with tabs[1]:
        anio = st.number_input("Año", 2024, 2100, value=ahora().year)
        mes = st.selectbox("Mes", range(1, 13), index=ahora().month - 1)
        ini = f"{anio:04d}-{mes:02d}-01"
        fin = f"{anio+1:04d}-01-01" if mes == 12 else f"{anio:04d}-{mes+1:02d}-01"
        df = leer_df("""SELECT a.apellido_paterno, a.nombres, ast.fecha, ast.estado
                        FROM asistencias ast JOIN alumnos a ON ast.alumno_id = a.id
                        WHERE ast.fecha >= ? AND ast.fecha < ? ORDER BY ast.fecha""", (ini, fin))
        if df.empty: st.info("Sin datos ese mes")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("Descargar Excel", df_a_xlsx(df, "Mensual"), f"asistencias_{anio}_{mes:02d}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with tabs[2]:
        dni = st.text_input("DNI del alumno", key="rep_dni")
        if dni:
            df = leer_df("""SELECT ast.fecha, ast.hora, ast.estado, ast.tipo FROM asistencias ast
                            JOIN alumnos a ON ast.alumno_id = a.id WHERE a.dni = ? ORDER BY ast.fecha DESC""", (dni,))
            if df.empty: st.info("Sin registros")
            else: st.dataframe(df, use_container_width=True, hide_index=True)
    with tabs[3]:
        fecha_gen = st.date_input("Fecha", value=ahora().date(), key="rep_gen")
        df = leer_df("""SELECT t.nombre AS turno, g.nombre AS grado, s.nombre AS seccion, COUNT(ast.id) AS asistencias
                        FROM asistencias ast JOIN alumnos a ON ast.alumno_id = a.id
                        JOIN secciones s ON a.seccion_id = s.id JOIN grados g ON s.grado_id = g.id
                        JOIN turnos t ON s.turno_id = t.id WHERE ast.fecha = ?
                        GROUP BY t.nombre, g.nombre, s.nombre ORDER BY t.nombre, g.nombre""", (str(fecha_gen),))
        if not df.empty: st.dataframe(df, use_container_width=True, hide_index=True)
    with tabs[4]:
        st.subheader("PDF Multilhoja")
        fecha_pdf = st.date_input("Fecha para PDF", value=ahora().date(), key="rep_pdf_dia")
        if st.button("Generar PDF diario", type="primary"):
            with st.spinner("Generando..."):
                pdf = generar_pdf_multilhoja_diario(str(fecha_pdf))
            if pdf:
                st.download_button("Descargar PDF", pdf, f"reporte_diario_{fecha_pdf}.pdf", "application/pdf", use_container_width=True)


def generar_pdf_multilhoja_diario(fecha):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(A4[1], A4[0]), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    est = getSampleStyleSheet()
    el = []
    el.append(Paragraph(f"<b>Reporte Diario — {fecha}</b>", est["Heading1"]))
    el.append(Spacer(1, 12))
    df = leer_df("""SELECT t.nombre AS Turno, g.nombre AS Grado, s.nombre AS Seccion,
                    COUNT(ast.id) AS Asistencias
                    FROM asistencias ast JOIN alumnos a ON ast.alumno_id = a.id
                    JOIN secciones s ON a.seccion_id = s.id JOIN grados g ON s.grado_id = g.id
                    JOIN turnos t ON s.turno_id = t.id WHERE ast.fecha = ?
                    GROUP BY t.nombre, g.nombre, s.nombre ORDER BY t.nombre, g.nombre""", (fecha,))
    if not df.empty:
        datos = [df.columns.tolist()] + df.astype(str).values.tolist()
        t = Table(datos, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(C_PRIMARIO)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        el.append(t)
    doc.build(el)
    buf.seek(0)
    return buf.getvalue()  

# modulos/asistencia.py — PARTE 11/12


def vista_justificaciones_permisos():
    st.title("📝 Justificaciones y Permisos")
    tabs = st.tabs(["Justificaciones previas", "Permisos"])
    with tabs[0]: _justificaciones_previas()
    with tabs[1]: _permisos()


def _justificaciones_previas():
    st.subheader("Justificaciones previas (hoy, mañana, pasado)")
    df = leer_df("""SELECT jp.id, jp.fecha_objetivo, jp.motivo, jp.aplicada,
                    a.nombres, a.apellido_paterno, a.dni
                    FROM justificaciones_previas jp JOIN alumnos a ON jp.alumno_id = a.id
                    WHERE jp.fecha_objetivo BETWEEN ? AND ? ORDER BY jp.fecha_objetivo""",
                 (hoy_str(), (ahora() + timedelta(days=2)).strftime("%Y-%m-%d")))
    if df.empty: st.info("Sin justificaciones")
    else: st.dataframe(df, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.subheader("Registrar justificación previa")
    with st.form("form_just"):
        dni = st.text_input("DNI alumno")
        fecha_obj = st.date_input("Fecha objetivo", min_value=ahora().date(), max_value=ahora().date() + timedelta(days=2))
        motivo = st.text_area("Motivo")
        if st.form_submit_button("Registrar", type="primary"):
            al = leer_df("SELECT id FROM alumnos WHERE dni=?", (dni,))
            if al.empty: st.error("Alumno no encontrado")
            else:
                ok, msg = crear_justificacion_previa(int(al.iloc[0]["id"]), str(fecha_obj), FALTA, motivo, st.session_state["user"])
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)


def _permisos():
    st.subheader("Permisos de inasistencia")
    df = leer_df("""SELECT p.id, p.fecha_inicio, p.fecha_fin, p.motivo, p.activo,
                    a.nombres, a.apellido_paterno FROM permisos p JOIN alumnos a ON p.alumno_id = a.id
                    ORDER BY p.fecha_inicio DESC LIMIT 100""")
    if df.empty: st.info("Sin permisos")
    else: st.dataframe(df, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.subheader("Registrar permiso")
    with st.form("form_perm"):
        dni = st.text_input("DNI alumno")
        fi = st.date_input("Fecha inicio", min_value=ahora().date() + timedelta(days=1))
        ff = st.date_input("Fecha fin", min_value=ahora().date() + timedelta(days=1))
        motivo = st.text_area("Motivo")
        if st.form_submit_button("Registrar", type="primary"):
            al = leer_df("SELECT id FROM alumnos WHERE dni=?", (dni,))
            if al.empty: st.error("Alumno no encontrado")
            else:
                ok, msg = crear_permiso(int(al.iloc[0]["id"]), str(fi), str(ff), motivo, st.session_state["user"])
                if ok: st.success(msg); st.rerun()
                else: st.error(msg)


def vista_dias_especiales():
    st.title("📅 Días Especiales")
    tabs = st.tabs(["Crear", "Listar"])
    with tabs[0]:
        with st.form("form_dia"):
            fecha = st.date_input("Fecha", min_value=ahora().date())
            desc = st.text_input("Descripción / Nombre")
            tipo = st.radio("Tipo", ["Evento", "Feriado"], horizontal=True)
            turnos = listar_turnos()
            turno_opts = {"Ambos": None}; turno_opts.update({t["nombre"]: t["id"] for t in turnos})
            t_lbl = st.selectbox("Turno", list(turno_opts.keys()))
            hora = st.time_input("Hora entrada", value=datetime.strptime("08:00", "%H:%M").time())
            contar_clases = st.checkbox("Contar como clases normales")
            if st.form_submit_button("Crear", type="primary"):
                if not desc.strip(): st.error("Descripción obligatoria")
                else:
                    periodo = leer_df("SELECT id FROM periodos WHERE activo=1 LIMIT 1")
                    pid = int(periodo.iloc[0]["id"]) if not periodo.empty else None
                    escribir("""INSERT INTO dias_especiales(fecha, descripcion, turno_id, hora_entrada, tipo, periodo_id, contar_como_clases)
                                VALUES(?, ?, ?, ?, ?, ?, ?)""",
                             (str(fecha), desc.strip(), turno_opts[t_lbl],
                              hora.strftime("%H:%M") if tipo == "Evento" else None,
                              "evento" if tipo == "Evento" else "feriado", pid, 1 if contar_clases else 0))
                    st.success("Día especial creado")
                    st.rerun()
    with tabs[1]:
        df = leer_df("""SELECT d.id, d.fecha, d.descripcion, d.tipo, COALESCE(t.nombre,'Ambos') AS turno,
                        d.hora_entrada, d.contar_como_clases FROM dias_especiales d
                        LEFT JOIN turnos t ON d.turno_id = t.id
                        WHERE d.activo = 1 AND d.fecha >= ? ORDER BY d.fecha""", (hoy_str(),))
        if df.empty: st.info("Sin días especiales")
        else: st.dataframe(df, use_container_width=True, hide_index=True)


def vista_ventanas():
    st.title("⏰ Ventanas de Asistencia")
    for turno in listar_turnos():
        st.subheader(f"Turno {turno['nombre']}")
        for v in listar_ventanas(turno["id"]):
            with st.expander(f"{v['nombre']} ({v['tipo']})"):
                st.write(f"Apertura: {v['hora_apertura']}")
                st.write(f"Límite puntual: {v['hora_limite_puntual']}")
                st.write(f"Cierre: {v['hora_cierre']}")


def vista_usuarios():
    st.title("👥 Usuarios")
    tabs = st.tabs(["Listar", "Crear", "Asignar auxiliares"])
    with tabs[0]:
        df = leer_df("SELECT id, usuario, rol, nombres, activo, ultimo_login FROM usuarios ORDER BY usuario")
        if df.empty: st.info("Sin usuarios")
        else: st.dataframe(df, use_container_width=True, hide_index=True)
    with tabs[1]:
        with st.form("form_user"):
            u = st.text_input("Usuario"); p = st.text_input("Contraseña", type="password")
            n = st.text_input("Nombres"); r = st.selectbox("Rol", ["Admin", "Direccion", "Coordinador", "Auxiliar", "Docente"])
            if st.form_submit_button("Crear", type="primary"):
                if not u or not p or not n: st.error("Completa todos los campos")
                elif len(p) < 6: st.error("Mínimo 6 caracteres")
                else:
                    existe = leer_df("SELECT id FROM usuarios WHERE LOWER(usuario)=?", (u.strip().lower(),))
                    if not existe.empty: st.error("Usuario ya existe")
                    else:
                        escribir("INSERT INTO usuarios(usuario, password, rol, nombres) VALUES(?, ?, ?, ?)",
                                 (u.strip().lower(), hashear_password(p), r, n.strip()))
                        st.success("Usuario creado"); st.rerun()
    with tabs[2]:
        _asignar_auxiliares()


def _asignar_auxiliares():
    st.subheader("Asignar secciones a Auxiliares")
    dfa = leer_df("SELECT id, usuario, nombres FROM usuarios WHERE rol='Auxiliar' AND activo=1 ORDER BY nombres")
    if dfa.empty: st.info("Sin auxiliares"); return
    ops = {f"{r['nombres']} ({r['usuario']})": r["id"] for _, r in dfa.iterrows()}
    sel = st.selectbox("Auxiliar", list(ops.keys()), key="asig_aux")
    ida = ops[sel]
    secs = leer_df("""SELECT s.id, s.nombre, g.nombre AS grado FROM secciones s
                      JOIN grados g ON s.grado_id=g.id ORDER BY g.nombre, s.nombre""")
    if secs.empty: st.info("Sin secciones"); return
    asig_df = leer_df("SELECT seccion_id FROM auxiliar_secciones WHERE usuario_id=?", (ida,))
    asignadas = set(asig_df["seccion_id"].tolist()) if not asig_df.empty else set()
    sel_s = []
    for _, s in secs.iterrows():
        if st.checkbox(f"{s['grado']} {s['nombre']}", value=s["id"] in asignadas, key=f"asig_{ida}_{s['id']}"):
            sel_s.append(s["id"])
    if confirmar_accion("asig_" + str(ida), "Guardar asignaciones", "¿Guardar estas asignaciones?"):
        escribir("DELETE FROM auxiliar_secciones WHERE usuario_id=?", (ida,))
        for sid in sel_s:
            try: escribir("INSERT INTO auxiliar_secciones(usuario_id, seccion_id) VALUES(?, ?)", (ida, sid))
            except Exception: pass
        st.success("Asignaciones guardadas"); st.rerun() 

# modulos/asistencia.py — PARTE 12/12


def vista_auditoria():
    st.title("🔍 Auditoría")
    df = leer_df("SELECT id, usuario, accion, fecha, tabla_afectada, registro_id, ip FROM auditoria ORDER BY id DESC LIMIT 500")
    st.write(f"**{len(df)} registros**")
    if not df.empty: st.dataframe(df, use_container_width=True, hide_index=True)


def vista_mi_cuenta():
    st.title("👤 Mi Cuenta")
    usuario = st.session_state["user"]
    st.markdown(f"""
    **Usuario:** {usuario['usuario']}
    **Rol:** {usuario['rol']}
    **Nombres:** {usuario['nombres']}
    **Último login:** {usuario.get('ultimo_login') or 'Nunca'}
    """)
    if usuario["rol"] == "Auxiliar":
        df_secs = leer_df("""SELECT g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno
                             FROM auxiliar_secciones a JOIN secciones s ON a.seccion_id=s.id
                             JOIN grados g ON s.grado_id=g.id JOIN turnos t ON s.turno_id=t.id
                             WHERE a.usuario_id=? ORDER BY g.nombre, s.nombre""", (usuario["id"],))
        st.markdown("---"); st.subheader("Mis secciones asignadas")
        if df_secs.empty: st.warning("No tienes secciones asignadas.")
        else: st.dataframe(df_secs, use_container_width=True, hide_index=True)
    st.markdown("---")
    st.subheader("Cambiar contraseña")
    with st.form("form_pwd"):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Nueva contraseña", type="password")
        confirma = st.text_input("Confirmar nueva", type="password")
        if st.form_submit_button("Cambiar", type="primary"):
            if not verificar_password(actual, usuario["password"]): st.error("Contraseña actual incorrecta")
            elif len(nueva) < 6: st.error("Mínimo 6 caracteres")
            elif nueva != confirma: st.error("No coinciden")
            else:
                h = hashear_password(nueva)
                escribir("UPDATE usuarios SET password=? WHERE id=?", (h, usuario["id"]))
                st.session_state["user"]["password"] = h
                st.success("Contraseña actualizada")


def vista_grados_secciones():
    st.title("🏫 Grados y Secciones")
    df = leer_df("""SELECT g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno,
                    (SELECT COUNT(*) FROM alumnos a WHERE a.seccion_id=s.id AND a.activo=1) AS alumnos
                    FROM secciones s JOIN grados g ON s.grado_id = g.id JOIN turnos t ON s.turno_id = t.id
                    ORDER BY t.nombre, g.nombre, s.nombre""")
    if df.empty: st.info("No hay secciones")
    else: st.dataframe(df, use_container_width=True, hide_index=True)


def vista_periodos():
    st.title("📅 Periodos")
    usuario = st.session_state["user"]
    tabs = st.tabs(["Activo", "Crear", "Cerrar año", "Historial"])
    with tabs[0]:
        p = obtener_periodo_activo()
        if p: st.success(f"Periodo activo: **{p['nombre']}** ({p['fecha_inicio']} al {p['fecha_fin']})")
        else: st.warning("No hay periodo activo")
    with tabs[1]:
        with st.form("form_periodo"):
            nombre = st.text_input("Nombre", value=str(ahora().year))
            fi = st.date_input("Fecha inicio", value=date(ahora().year, 3, 1))
            ff = st.date_input("Fecha fin", value=date(ahora().year, 12, 31))
            if st.form_submit_button("Crear y activar", type="primary"):
                if not nombre.strip(): st.error("Nombre obligatorio")
                else:
                    ok, msg = crear_periodo_manual(nombre, fi, ff, usuario)
                    if ok: st.success(msg); st.rerun()
                    else: st.error(msg)
    with tabs[2]:
        st.subheader("Cerrar año escolar y crear nuevo periodo")
        p = obtener_periodo_activo()
        if not p: st.warning("No hay periodo activo para cerrar")
        else:
            st.info(f"Cerrando: **{p['nombre']}**")
            with st.form("form_cierre"):
                nuevo_nombre = st.text_input("Nombre del nuevo periodo", value=str(ahora().year + 1))
                fi = st.date_input("Inicio nuevo", value=date(ahora().year + 1, 3, 1))
                ff = st.date_input("Fin nuevo", value=date(ahora().year + 1, 12, 31))
                if st.form_submit_button("Cerrar y crear nuevo", type="primary"):
                    if confirmar_accion("cierre_anual", "Confirmar cierre", "¿Cerrar este periodo?"):
                        ok, msg = cerrar_anio_escolar(usuario, p["id"], nuevo_nombre, fi, ff)
                        if ok: st.success(msg); st.rerun()
                        else: st.error(msg)
    with tabs[3]:
        df = info_periodo_con_alumnos()
        if not df.empty: st.dataframe(df, use_container_width=True, hide_index=True)
        df_c = listar_cierres_anuales()
        if not df_c.empty:
            st.subheader("Cierres anuales")
            st.dataframe(df_c, use_container_width=True, hide_index=True)


def vista_backup():
    st.title("💾 Backup")
    st.info("Con Turso, la base de datos se sincroniza automáticamente en la nube.")
    st.caption(f"Archivo local: data/replica.db")
    try:
        p = Path("data/replica.db")
        if p.exists():
            st.success(f"BD local: {p.stat().st_size / 1024:.1f} KB")
        else: st.warning("No hay BD local (se creará al conectar a Turso)")
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════
# BLOQUE A — REPORTE GENERAL POR AUXILIAR
# ═══════════════════════════════════════════════════════════════════

def vista_reporte_general_auxiliar():
    st.subheader("Reporte general por auxiliar")
    st.caption("Muestra TODAS las secciones del turno. Si no hay asistencias, aparecen con 0.")

    turnos = listar_turnos()
    if not turnos:
        st.info("Sin turnos configurados.")
        return

    ops = {t["nombre"]: t["id"] for t in turnos}
    sel_turno = st.selectbox("Turno", list(ops.keys()), key="repgen_turno")
    id_turno = ops[sel_turno]

    ventana_clases = None
    for v in listar_ventanas(id_turno):
        if v["tipo"] == "clases":
            ventana_clases = v
            break

    if not ventana_clases:
        st.warning("Este turno no tiene ventana de clases configurada.")
        return

    hoy_d = ahora().date()
    c1, c2 = st.columns(2)
    with c1:
        desde = st.date_input("Desde", hoy_d, key="repgen_desde")
    with c2:
        hasta = st.date_input("Hasta", hoy_d, key="repgen_hasta")

    if desde > hasta:
        st.error("La fecha Desde no puede ser mayor que Hasta.")
        return

    pid = None
    dfp = listar_periodos()
    if not dfp.empty:
        ops_p = {}
        for _, r in dfp.iterrows():
            et = f"{r['nombre']} ({r['fecha_inicio']} - {r['fecha_fin']})"
            if r["cerrado"]:
                et += " [CERRADO]"
            elif r["activo"]:
                et += " [ACTIVO]"
            ops_p[et] = r["id"]
        sel_lbl = st.selectbox("Periodo", list(ops_p.keys()), key="repgen_pid")
        pid = ops_p[sel_lbl]

    cond_periodo = " AND ast.periodo_id = ?" if pid is not None else ""

    q = f"""
    SELECT
        s.id AS seccion_id,
        g.nombre AS grado,
        s.nombre AS seccion,
        COALESCE(u.nombres, '(Sin auxiliar)') AS auxiliar,
        COALESCE((
            SELECT COUNT(*) FROM asistencias ast
            JOIN alumnos a ON ast.alumno_id = a.id
            WHERE a.seccion_id = s.id AND a.activo = 1
              AND ast.tipo = 'clases' AND ast.estado = 'Puntual'
              AND ast.fecha BETWEEN ? AND ? {cond_periodo}
        ), 0) AS puntuales,
        COALESCE((
            SELECT COUNT(*) FROM asistencias ast
            JOIN alumnos a ON ast.alumno_id = a.id
            WHERE a.seccion_id = s.id AND a.activo = 1
              AND ast.tipo = 'clases' AND ast.estado = 'Falta'
              AND ast.fecha BETWEEN ? AND ? {cond_periodo}
        ), 0) AS faltas
    FROM secciones s
    JOIN grados g ON s.grado_id = g.id
    LEFT JOIN auxiliar_secciones ause ON ause.seccion_id = s.id
    LEFT JOIN usuarios u ON u.id = ause.usuario_id AND u.rol = 'Auxiliar' AND u.activo = 1
    WHERE s.turno_id = ?
    ORDER BY g.nombre, s.nombre, u.nombres
    """

    p = [str(desde), str(hasta)]
    if pid is not None:
        p.append(pid)
    p += [str(desde), str(hasta)]
    if pid is not None:
        p.append(pid)
    p.append(id_turno)

    df = leer_df(q, p)
    if df.empty:
        st.warning("No hay secciones creadas en este turno.")
        return

    df["total"] = df["puntuales"] + df["faltas"]

    st.markdown("---")
    st.markdown(f"**Turno {sel_turno}** — del {desde} al {hasta}")
    st.caption(f"{len(df)} secciones en este turno.")

    filas = []
    for aux in df["auxiliar"].unique().tolist():
        df_aux = df[df["auxiliar"] == aux]
        for _, row in df_aux.iterrows():
            filas.append({
                "Auxiliar": aux,
                "Grado": row["grado"],
                "Seccion": row["seccion"],
                "Puntuales": int(row["puntuales"]),
                "Faltas": int(row["faltas"]),
                "Total": int(row["total"]),
            })
        filas.append({
            "Auxiliar": f"  >> Subtotal {aux}",
            "Grado": "", "Seccion": "",
            "Puntuales": int(df_aux["puntuales"].sum()),
            "Faltas": int(df_aux["faltas"].sum()),
            "Total": int(df_aux["total"].sum()),
        })
    filas.append({
        "Auxiliar": "TOTAL GENERAL",
        "Grado": "", "Seccion": "",
        "Puntuales": int(df["puntuales"].sum()),
        "Faltas": int(df["faltas"].sum()),
        "Total": int(df["total"].sum()),
    })

    df_export = pd.DataFrame(filas)
    st.dataframe(df_export, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Descargar")
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Excel", df_a_xlsx(df_export, "General por auxiliar"),
            f"Reporte_general_{sel_turno}_{desde}_{hasta}.xlsx",
            use_container_width=True, key="repgen_dl_x"
        )
    with c2:
        st.download_button(
            "PDF",
            generar_pdf_tabla_ancha(
                df_export, f"Reporte general {sel_turno}",
                f"{desde} a {hasta}"
            ),
            f"Reporte_general_{sel_turno}_{desde}_{hasta}.pdf",
            "application/pdf", use_container_width=True, key="repgen_dl_p"
        )

# ═══════════════════════════════════════════════════════════════════
# BLOQUE B — CIERRE MENSUAL CON PDF
# ═══════════════════════════════════════════════════════════════════

def _generar_hojas_mensual(mes, anio, ids_secs):
    hojas = {}
    ult = monthrange(anio, mes)[1]
    ini = date(anio, mes, 1)
    fin = date(anio, mes, ult)

    dias_especiales_mes = set()
    df_de = leer_df(
        "SELECT fecha FROM dias_especiales WHERE fecha BETWEEN ? AND ? AND activo=1 AND tipo='evento'",
        (str(ini), str(fin))
    )
    for _, r in df_de.iterrows():
        try:
            f = datetime.strptime(str(r["fecha"])[:10], "%Y-%m-%d").date()
            dias_especiales_mes.add(f)
        except Exception:
            pass

    for idsec in ids_secs:
        sec_df = leer_df(
            "SELECT s.id, s.nombre AS seccion, g.nombre AS grado, t.nombre AS turno "
            "FROM secciones s JOIN grados g ON s.grado_id=g.id "
            "JOIN turnos t ON s.turno_id=t.id WHERE s.id=?",
            (idsec,)
        )
        if sec_df.empty:
            continue
        sec = sec_df.iloc[0].to_dict()

        dias = []
        for d in range(1, ult + 1):
            f = date(anio, mes, d)
            if f.weekday() >= 5 and f not in dias_especiales_mes:
                continue
            dias.append(f)

        df_al = leer_df(
            "SELECT a.id AS alumno_id, "
            "a.apellido_paterno||' '||COALESCE(a.apellido_materno,'') AS apellidos, "
            "a.nombres FROM alumnos a WHERE a.seccion_id=? AND a.activo=1 "
            "ORDER BY a.apellido_paterno",
            (idsec,)
        )
        if df_al.empty:
            continue

        asis = {}
        df_ast = leer_df(
            "SELECT alumno_id, fecha, estado FROM asistencias "
            "WHERE fecha BETWEEN ? AND ? AND tipo='clases' "
            "AND alumno_id IN (SELECT id FROM alumnos WHERE seccion_id=?)",
            (str(ini), str(fin), idsec)
        )
        for _, r in df_ast.iterrows():
            f_str = str(r["fecha"])[:10]
            asis[(r["alumno_id"], f_str)] = "F" if r["estado"] == "Falta" else "P"

        filas = []
        for _, al in df_al.iterrows():
            fila = {"Apellidos": al["apellidos"], "Nombres": al["nombres"]}
            tp = tf = 0
            for d in dias:
                f_str = d.strftime("%Y-%m-%d")
                etq = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"][d.weekday()] + " " + str(d.day).zfill(2)
                est = asis.get((al["alumno_id"], f_str), "-")
                fila[etq] = est
                if est == "P":
                    tp += 1
                elif est == "F":
                    tf += 1
            fila["Total P"] = tp
            fila["Total F"] = tf
            filas.append(fila)
        df_cal = pd.DataFrame(filas)
        cols_base = ["Apellidos", "Nombres"]
        cols_dias = [c for c in df_cal.columns if c not in cols_base and not c.startswith("Total")]
        df_cal = df_cal[cols_base + cols_dias + ["Total P", "Total F"]]

        filas_f = []
        for _, al in df_al.iterrows():
            faltas = sum(1 for d in dias
                         if asis.get((al["alumno_id"], d.strftime("%Y-%m-%d"))) == "F")
            if faltas > 0:
                filas_f.append({
                    "Apellidos": al["apellidos"],
                    "Nombres": al["nombres"],
                    "Faltas en el mes": faltas
                })
        df_faltas = (pd.DataFrame(filas_f) if filas_f
                     else pd.DataFrame(columns=["Apellidos", "Nombres", "Faltas en el mes"]))

        nombre_hoja = f"{sec['grado']} {sec['seccion']} - {sec['turno']}"
        hojas[nombre_hoja] = [
            ("CALENDARIO DEL MES", df_cal),
            ("CONTEO DE FALTAS (solo los que faltaron)", df_faltas),
        ]
    return hojas


def vista_cierre_mensual_pdf():
    st.subheader("Cierre mensual con PDF")
    c1, c2 = st.columns(2)
    with c1:
        anio = st.number_input("Año", 2024, 2100, value=ahora().year, key="cm_anio")
    with c2:
        mes = st.selectbox("Mes", range(1, 13), index=ahora().month - 1, key="cm_mes")

    grados = listar_grados()
    if not grados:
        st.info("Sin grados configurados")
        return

    g = st.selectbox("Grado", grados, format_func=lambda x: x["nombre"], key="cm_grado")
    secs_df = leer_df("SELECT * FROM secciones WHERE grado_id=? ORDER BY nombre", (g["id"],))
    if secs_df.empty:
        st.info("Sin secciones para este grado")
        return

    secs_list = [{"id": -1, "nombre": "TODAS LAS SECCIONES"}] + secs_df.to_dict("records")
    s = st.selectbox("Sección", secs_list, format_func=lambda x: x["nombre"], key="cm_sec")

    if st.button("Generar PDF de cierre mensual", type="primary"):
        ids = [s["id"]] if s["id"] != -1 else secs_df["id"].tolist()
        with st.spinner("Generando PDF..."):
            hojas = _generar_hojas_mensual(int(mes), int(anio), ids)
            if not hojas:
                st.warning("Sin datos para ese mes")
                return
            pdf = _generar_pdf_multilhoja_cierre(hojas, f"Cierre Mensual {MESES_ES[int(mes)]} {int(anio)}")
        st.download_button(
            "Descargar PDF", pdf,
            f"Cierre_mensual_{anio}_{mes:02d}.pdf",
            "application/pdf", use_container_width=True
        )


def _generar_pdf_multilhoja_cierre(hojas, titulo_base):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(A4[1], A4[0]), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    est = getSampleStyleSheet()
    el = []
    primera = True
    for nombre_hoja, bloques in hojas.items():
        if not primera:
            el.append(PageBreak())
        primera = False
        el.append(Paragraph(f"<b>{titulo_base}</b>", est["Heading2"]))
        el.append(Paragraph(f"<b>{nombre_hoja}</b>", est["Heading3"]))
        el.append(Spacer(1, 10))
        for titulo_bloque, df in bloques:
            el.append(Paragraph(f"<b>{titulo_bloque}</b>", est["Heading4"]))
            el.append(Spacer(1, 4))
            if df is None or df.empty:
                el.append(Paragraph("Sin datos.", est["Normal"]))
                el.append(Spacer(1, 10))
                continue
            datos = [df.columns.tolist()] + df.astype(str).values.tolist()
            at = A4[1] - 30
            n_cols = len(df.columns)
            ac = at / n_cols
            t = Table(datos, colWidths=[ac] * n_cols, repeatRows=1)
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            el.append(t)
            el.append(Spacer(1, 12))
    doc.build(el)
    buf.seek(0)
    return buf.getvalue()

# ═══════════════════════════════════════════════════════════════════
# BLOQUE C — REPORTE DIARIO PDF POR SECCIÓN + HOJA FALTARON
# ═══════════════════════════════════════════════════════════════════

def _hoja_faltaron_dia(fecha, ids_secs):
    todos_just = []
    todos_injust = []
    for idsec in ids_secs:
        sec_df = leer_df(
            "SELECT s.id, s.nombre AS seccion, g.nombre AS grado FROM secciones s "
            "JOIN grados g ON s.grado_id=g.id WHERE s.id=?",
            (idsec,)
        )
        if sec_df.empty:
            continue
        sec = sec_df.iloc[0].to_dict()
        grado_secc = f"{sec['grado']} {sec['seccion']}"

        df_just = leer_df(
            "SELECT a.apellido_paterno||' '||COALESCE(a.apellido_materno,'')||', '||a.nombres AS Alumno "
            "FROM alumnos a JOIN asistencias ast ON ast.alumno_id=a.id "
            "WHERE a.seccion_id=? AND a.activo=1 AND ast.fecha=? "
            "AND ast.tipo='clases' AND ast.estado='Falta' AND ast.justificada=1 "
            "ORDER BY a.apellido_paterno",
            (idsec, str(fecha))
        )
        df_injust = leer_df(
            "SELECT a.apellido_paterno||' '||COALESCE(a.apellido_materno,'')||', '||a.nombres AS Alumno "
            "FROM alumnos a JOIN asistencias ast ON ast.alumno_id=a.id "
            "WHERE a.seccion_id=? AND a.activo=1 AND ast.fecha=? "
            "AND ast.tipo='clases' AND ast.estado='Falta' AND ast.justificada=0 "
            "ORDER BY a.apellido_paterno",
            (idsec, str(fecha))
        )
        for _, r in df_just.iterrows():
            todos_just.append({"Grado": grado_secc, "Alumno": r["Alumno"]})
        for _, r in df_injust.iterrows():
            todos_injust.append({"Grado": grado_secc, "Alumno": r["Alumno"]})

    filas = []
    n_max = max(len(todos_just), len(todos_injust))
    for i in range(n_max):
        fila = {}
        if i < len(todos_just):
            fila["J_Grado"] = todos_just[i]["Grado"]
            fila["J_Alumno"] = todos_just[i]["Alumno"]
        else:
            fila["J_Grado"] = ""
            fila["J_Alumno"] = ""
        if i < len(todos_injust):
            fila["F_Grado"] = todos_injust[i]["Grado"]
            fila["F_Alumno"] = todos_injust[i]["Alumno"]
        else:
            fila["F_Grado"] = ""
            fila["F_Alumno"] = ""
        filas.append(fila)

    if filas:
        df_lado = pd.DataFrame(filas).rename(columns={
            "J_Grado": "Grado/Secc.",
            "J_Alumno": "Apellidos y Nombres (JUST)",
            "F_Grado": "Grado/Secc. ",
            "F_Alumno": "Apellidos y Nombres (INJUST)",
        })
    else:
        df_lado = pd.DataFrame(columns=[
            "Grado/Secc.", "Apellidos y Nombres (JUST)",
            "Grado/Secc. ", "Apellidos y Nombres (INJUST)",
        ])

    titulo = (f"FALTAS DEL DIA {fecha}   | JUSTIFICADAS: {len(todos_just)}   "
              f"| INJUSTIFICADAS: {len(todos_injust)}")
    return [(titulo, df_lado)]


def _generar_hojas_diario(fecha, ids_secs):
    hojas = {}
    for idsec in ids_secs:
        sec_df = leer_df(
            "SELECT s.id, s.nombre AS seccion, g.nombre AS grado, t.nombre AS turno "
            "FROM secciones s JOIN grados g ON s.grado_id=g.id "
            "JOIN turnos t ON s.turno_id=t.id WHERE s.id=?",
            (idsec,)
        )
        if sec_df.empty:
            continue
        sec = sec_df.iloc[0].to_dict()

        df_clases = leer_df(
            "SELECT a.apellido_paterno||' '||COALESCE(a.apellido_materno,'') AS Apellidos, "
            "a.nombres AS Nombres, "
            "CASE WHEN ast.estado IS NULL THEN '-' "
            "WHEN ast.estado='Puntual' THEN 'P' "
            "WHEN ast.estado='Tardanza' THEN 'T' "
            "WHEN ast.estado='Falta' AND ast.justificada=1 THEN 'J' "
            "WHEN ast.estado='Falta' THEN 'F' "
            "WHEN ast.estado='Permiso' THEN 'PERMISO' "
            "ELSE ast.estado END AS Estado "
            "FROM alumnos a LEFT JOIN asistencias ast ON ast.alumno_id=a.id "
            "AND ast.fecha=? AND ast.tipo IN ('clases','evento') "
            "WHERE a.seccion_id=? AND a.activo=1 "
            "ORDER BY a.apellido_paterno, a.apellido_materno",
            (str(fecha), idsec)
        )
        if not df_clases.empty:
            df_clases.insert(0, "N", range(1, len(df_clases) + 1))

        nombre_hoja = f"{sec['grado']} {sec['seccion']} - {sec['turno']}"
        hojas[nombre_hoja] = [
            ("ASISTENCIA DE CLASES (P=Puntual | T=Tardanza | J=Falta just. | F=Falta)", df_clases),
        ]

    bloques_faltaron = _hoja_faltaron_dia(fecha, ids_secs)
    hojas = {"ALUMNOS QUE FALTARON": bloques_faltaron, **hojas}
    return hojas


def vista_reporte_diario_pdf():
    st.subheader("Reporte diario PDF por sección")
    fecha = st.date_input("Fecha", value=ahora().date(), key="repdia_pdf")

    grados = listar_grados()
    if not grados:
        st.info("Sin grados")
        return

    g = st.selectbox("Grado", grados, format_func=lambda x: x["nombre"], key="repdia_g")
    secs_df = leer_df("SELECT * FROM secciones WHERE grado_id=? ORDER BY nombre", (g["id"],))
    if secs_df.empty:
        st.info("Sin secciones")
        return

    secs_list = [{"id": -1, "nombre": "TODAS LAS SECCIONES"}] + secs_df.to_dict("records")
    s = st.selectbox("Sección", secs_list, format_func=lambda x: x["nombre"], key="repdia_s")

    if st.button("Generar PDF diario", type="primary"):
        ids = [s["id"]] if s["id"] != -1 else secs_df["id"].tolist()
        with st.spinner("Generando PDF..."):
            hojas = _generar_hojas_diario(str(fecha), ids)
            if not hojas:
                st.warning("Sin datos")
                return
            pdf = _generar_pdf_multilhoja_cierre(hojas, f"Reporte Diario {fecha}")
        st.download_button(
            "Descargar PDF", pdf,
            f"Reporte_diario_{fecha}.pdf",
            "application/pdf", use_container_width=True
        )

# ═══════════════════════════════════════════════════════════════════
# BLOQUE D — DÍAS ESPECIALES POR SECCIÓN + MANTENIMIENTO + CAMBIO PWD
# ═══════════════════════════════════════════════════════════════════

def vista_dias_especiales_avanzado():
    st.title("📅 Días Especiales Avanzado")
    usuario = st.session_state["user"]
    tabs = st.tabs(["Crear", "Listar"])

    with tabs[0]:
        tipo = st.radio("Tipo", ["Evento", "Feriado"], key="dia_av_tipo", horizontal=True)
        c1, c2 = st.columns(2)
        with c1:
            fecha = st.date_input("Fecha", min_value=ahora().date(), key="dia_av_fecha")
            desc = st.text_input("Descripción", key="dia_av_desc")
        with c2:
            if tipo == "Evento":
                turnos_opts = {"Ambos": None}
                turnos_opts.update({t["nombre"]: t["id"] for t in listar_turnos()})
                t_lbl = st.selectbox("Turno", list(turnos_opts.keys()), key="dia_av_turno")
                hora_t = st.time_input("Hora entrada", value=datetime.strptime("08:00", "%H:%M").time(), key="dia_av_hora")
                hora = hora_t.strftime("%H:%M")
            else:
                turnos_opts = {"Ambos": None}
                t_lbl = "Ambos"
                hora = "00:00"

        contar_como_clases = False
        if tipo == "Evento":
            contar_como_clases = st.checkbox("Contar como CLASES NORMALES (no como evento)", key="dia_av_contar")

        alcance = "Todo el colegio"
        if tipo == "Evento":
            alcance = st.radio("Aplica a:", ["Todo el colegio", "Solo algunas secciones"], key="dia_av_alcance", horizontal=True)

        selecciones_secciones = []
        if tipo == "Evento" and alcance == "Solo algunas secciones":
            st.markdown("**Alcance del día especial:**")
            with st.expander("Seleccionar grados y secciones", expanded=True):
                for g in listar_grados():
                    st.checkbox("Todo " + g["nombre"], key="dia_av_grado_" + str(g["id"]))
                    secs = leer_df("SELECT * FROM secciones WHERE grado_id=? ORDER BY nombre", (g["id"],))
                    for _, s in secs.iterrows():
                        if st.checkbox(f"   {g['nombre']} {s['nombre']}", key=f"dia_av_sec_{g['id']}_{s['id']}"):
                            selecciones_secciones.append(s["id"])

        if st.button("Crear día especial", type="primary"):
            if not desc.strip():
                st.error("Descripción requerida.")
            elif tipo == "Evento" and alcance == "Solo algunas secciones" and not selecciones_secciones:
                st.error("Selecciona al menos una sección.")
            else:
                selecciones_secciones = list(set(selecciones_secciones))
                idt = turnos_opts.get(t_lbl) if tipo == "Evento" else None
                periodo = leer_df("SELECT id FROM periodos WHERE activo=1 LIMIT 1")
                pid = int(periodo.iloc[0]["id"]) if not periodo.empty else None
                escribir("""
                    INSERT INTO dias_especiales(fecha, descripcion, turno_id,
                        hora_entrada, tipo, periodo_id, contar_como_clases)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (str(fecha), desc.strip(), idt, hora,
                      "evento" if tipo == "Evento" else "feriado",
                      pid, 1 if contar_como_clases else 0))
                if selecciones_secciones:
                    dia_id = leer_df("SELECT MAX(id) AS id FROM dias_especiales").iloc[0]["id"]
                    for sid in selecciones_secciones:
                        try:
                            escribir(
                                "INSERT INTO dias_especiales_secciones(dia_especial_id, seccion_id) VALUES(?, ?)",
                                (int(dia_id), sid)
                            )
                        except Exception:
                            pass
                st.success("Día especial creado")
                st.rerun()

    with tabs[1]:
        df = leer_df("""
            SELECT d.id, d.fecha, d.descripcion, COALESCE(t.nombre,'Ambos') AS turno,
                   d.hora_entrada, d.tipo, d.contar_como_clases,
                   (SELECT GROUP_CONCAT(g.nombre || ' ' || s.nombre, ', ')
                    FROM dias_especiales_secciones ds
                    JOIN secciones s ON ds.seccion_id = s.id
                    JOIN grados g ON s.grado_id = g.id
                    WHERE ds.dia_especial_id = d.id) AS secciones_aplicadas
            FROM dias_especiales d LEFT JOIN turnos t ON d.turno_id = t.id
            WHERE d.fecha >= ? AND d.activo=1 ORDER BY d.fecha
        """, (hoy_str(),))
        if df.empty:
            st.info("Sin días especiales")
        else:
            df_show = df.copy()
            df_show["contar_como_clases"] = df_show["contar_como_clases"].apply(
                lambda x: "Clases normales" if x else "Evento"
            )
            df_show["secciones_aplicadas"] = df_show["secciones_aplicadas"].fillna("Todo el colegio")
            st.dataframe(df_show, use_container_width=True, hide_index=True)


def modo_mantenimiento():
    df = leer_df("SELECT valor FROM config WHERE clave='mantenimiento'")
    return bool(not df.empty and df.iloc[0]["valor"] == "1")


def activar_mantenimiento(usuario, mensaje=""):
    escribir("INSERT INTO config(clave, valor) VALUES('mantenimiento', '1') "
             "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor")
    escribir("INSERT INTO config(clave, valor) VALUES('mantenimiento_msg', ?) "
             "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor", (mensaje or "",))
    auditar(usuario["usuario"], "Activó modo mantenimiento")


def desactivar_mantenimiento(usuario):
    escribir("INSERT INTO config(clave, valor) VALUES('mantenimiento', '0') "
             "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor")
    auditar(usuario["usuario"], "Desactivó modo mantenimiento")


def vista_mantenimiento():
    st.title("🛠️ Modo Mantenimiento")
    usuario = st.session_state["user"]
    if modo_mantenimiento():
        st.error("El sistema está en MANTENIMIENTO.")
        if confirmar_accion("mant_off", "Desactivar mantenimiento", "¿Desactivar mantenimiento?"):
            desactivar_mantenimiento(usuario)
            st.success("Mantenimiento desactivado")
            st.rerun()
    else:
        st.success("El sistema está operativo.")
        msg = st.text_input("Mensaje para mostrar (opcional)", key="mant_msg")
        if confirmar_accion("mant_on", "Activar mantenimiento", "¿Activar mantenimiento?"):
            activar_mantenimiento(usuario, msg)
            st.success("Mantenimiento activado")
            st.rerun()


def vista_mantenimiento_bloqueado():
    st.title("Sistema en mantenimiento")
    df = leer_df("SELECT valor FROM config WHERE clave='mantenimiento_msg'")
    if not df.empty and df.iloc[0]["valor"]:
        st.warning(df.iloc[0]["valor"])
    st.info("Vuelve a intentarlo más tarde.")


def vista_cambio_password_obligatorio():
    usuario = st.session_state["user"]
    st.title("Cambio obligatorio de contraseña")
    st.warning("Tu cuenta tiene una contraseña temporal.")
    with st.form("cambio_pwd_obl"):
        nueva = st.text_input("Nueva contraseña", type="password")
        confirma = st.text_input("Confirmar", type="password")
        if st.form_submit_button("Cambiar", type="primary"):
            if len(nueva) < 6:
                st.error("Mínimo 6 caracteres")
            elif nueva != confirma:
                st.error("No coinciden")
            else:
                h = hashear_password(nueva)
                escribir("UPDATE usuarios SET password=?, debe_cambiar_password=0 WHERE id=?",
                         (h, usuario["id"]))
                st.session_state["user"]["debe_cambiar_password"] = 0
                st.session_state["user"]["password"] = h
                auditar(usuario["usuario"], "Cambio pwd obligatorio")
                st.rerun()

# ═══════════════════════════════════════════════════════════════════
# BLOQUE E — SELECTOR VISUAL Y PERFIL COMPLETO
# ═══════════════════════════════════════════════════════════════════

def _selector_grado_seccion(clave, titulo="Elige el grado"):
    idsec = st.session_state.get(clave + "_idsec")
    if idsec:
        return idsec

    idg = st.session_state.get(clave + "_grado")
    if idg:
        g_df = leer_df("SELECT * FROM grados WHERE id=?", (idg,))
        if g_df.empty:
            st.session_state.pop(clave + "_grado", None)
            st.rerun()
            return None
        g = g_df.iloc[0].to_dict()
        if st.button("← Regresar a grados", key=clave + "_volver_g"):
            st.session_state.pop(clave + "_grado", None)
            st.rerun()
        st.subheader(f"Secciones de {g['nombre']}")
        secs = leer_df("SELECT * FROM secciones WHERE grado_id=? ORDER BY nombre", (g["id"],))
        if secs.empty:
            st.info("Sin secciones.")
            return None
        for _, s in secs.iterrows():
            n_df = leer_df("SELECT COUNT(*) AS n FROM alumnos WHERE seccion_id=? AND activo=1", (s["id"],))
            n = int(n_df.iloc[0]["n"]) if not n_df.empty else 0
            if st.button(f"{s['nombre']}  ({n})", use_container_width=True, key=f"{clave}_s_{s['id']}"):
                st.session_state[clave + "_idsec"] = int(s["id"])
                st.rerun()
        return None

    st.markdown(f"### {titulo}")
    grados = listar_grados()
    if not grados:
        st.info("No hay grados.")
        return None
    for g in grados:
        secs = leer_df("SELECT COUNT(*) AS n FROM secciones WHERE grado_id=?", (g["id"],))
        n = int(secs.iloc[0]["n"]) if not secs.empty else 0
        if st.button(f"{g['nombre']}  ({n})", use_container_width=True, key=f"{clave}_g_{g['id']}"):
            st.session_state[clave + "_grado"] = g["id"]
            st.rerun()
    return None


def _selector_alumno_lista(clave, idsec, on_click_key):
    sec_df = leer_df("""
        SELECT s.id, s.nombre AS seccion, g.nombre AS grado, t.nombre AS turno
        FROM secciones s JOIN grados g ON s.grado_id=g.id
        JOIN turnos t ON s.turno_id=t.id WHERE s.id=?
    """, (idsec,))
    if sec_df.empty:
        st.warning("Sección no encontrada.")
        st.session_state.pop(clave + "_idsec", None)
        st.session_state.pop(clave + "_grado", None)
        st.rerun()
        return None
    sec = sec_df.iloc[0].to_dict()

    if st.button("← Regresar a secciones", key=clave + "_volver_s"):
        st.session_state.pop(clave + "_idsec", None)
        st.session_state.pop(on_click_key, None)
        st.rerun()

    st.markdown(f"### {sec['grado']} {sec['seccion']} - Turno {sec['turno']}")

    df = leer_df(
        "SELECT a.id, a.dni, a.nombres, a.apellido_paterno, a.apellido_materno, "
        "a.apellido_paterno||' '||COALESCE(a.apellido_materno,'')||', '||a.nombres AS nombre_completo "
        "FROM alumnos a WHERE a.seccion_id=? AND a.activo=1 "
        "ORDER BY a.apellido_paterno, a.apellido_materno, a.nombres",
        (idsec,)
    )
    if df.empty:
        st.info("Sin alumnos activos.")
        return None

    st.caption(f"{len(df)} alumnos. Aprieta un nombre para seleccionarlo.")
    for _, al in df.iterrows():
        if st.button(al["nombre_completo"], use_container_width=True, key=f"{clave}_al_{al['id']}"):
            st.session_state[on_click_key] = int(al["id"])
            st.rerun()

    idal = st.session_state.get(on_click_key)
    if not idal:
        return None

    al_df = leer_df("""
        SELECT a.id, a.dni, a.nombres, a.apellido_paterno, a.apellido_materno,
               a.seccion_id, a.nombre_apoderado, a.telefono_apoderado,
               g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno
        FROM alumnos a JOIN secciones s ON a.seccion_id=s.id
        JOIN grados g ON s.grado_id=g.id JOIN turnos t ON s.turno_id=t.id
        WHERE a.id=?
    """, (idal,))
    if al_df.empty:
        return None
    return al_df.iloc[0].to_dict()


def perfil_alumno_datos(idal):
    try:
        al_df = leer_df("""
            SELECT a.*, g.nombre AS grado, s.nombre AS seccion, t.nombre AS turno,
                   s.id AS seccion_id, t.id AS turno_id
            FROM alumnos a JOIN secciones s ON a.seccion_id=s.id
            JOIN grados g ON s.grado_id=g.id JOIN turnos t ON s.turno_id=t.id
            WHERE a.id=?
        """, (idal,))
        if al_df.empty:
            return {}
        a = al_df.iloc[0].to_dict()
    except Exception as e:
        log.exception("perfil_alumno_datos: %s", e)
        return {}

    da = leer_df("""
        SELECT a.id, a.fecha, a.hora, a.tipo, a.estado,
               COALESCE(a.justificada,0) AS justificada,
               COALESCE(a.observacion,'') AS observacion,
               COALESCE(a.origen,'qr') AS origen,
               COALESCE(a.justificado_por,'') AS justificado_por,
               a.ventana_id
        FROM asistencias a WHERE a.alumno_id=?
        ORDER BY a.fecha DESC, a.hora DESC
    """, (idal,))

    dt = leer_df("""
        SELECT fecha, hora, numero AS "N", accion,
               COALESCE(justificada,0) AS justificada,
               COALESCE(origen,'qr') AS origen
        FROM tardanzas WHERE alumno_id=? ORDER BY fecha DESC, hora DESC
    """, (idal,))

    db = leer_df("""
        SELECT fecha_inicio, COALESCE(fecha_fin,'-') AS fecha_fin,
               COALESCE(motivo,'') AS motivo, COALESCE(activo,0) AS activo
        FROM bloqueos WHERE alumno_id=? ORDER BY fecha_inicio DESC
    """, (idal,))

    dp = leer_df("""
        SELECT id, fecha_inicio, fecha_fin, COALESCE(motivo,'') AS motivo,
               COALESCE(activo,0) AS activo, COALESCE(creado_por,'') AS creado_por
        FROM permisos WHERE alumno_id=? ORDER BY fecha_inicio DESC
    """, (idal,))

    dj = leer_df("""
        SELECT id, fecha_objetivo, tipo, COALESCE(motivo,'') AS motivo,
               COALESCE(aplicada,0) AS aplicada, COALESCE(creado_por,'') AS creado_por
        FROM justificaciones_previas WHERE alumno_id=?
        ORDER BY fecha_objetivo DESC
    """, (idal,))

    tp = int((da["estado"] == PUNTUAL).sum()) if not da.empty else 0
    tf = int((da["estado"] == FALTA).sum()) if not da.empty else 0
    tt = int((da["estado"] == TARDANZA).sum()) if not da.empty else 0

    return {
        "alumno": a, "asistencias": da, "tardanzas": dt, "bloqueos": db,
        "permisos": dp, "justificaciones_previas": dj,
        "total_puntuales": tp, "total_faltas": tf, "total_tardanzas": tt,
        "tard_injust": contar_tardanzas_injustificadas(idal),
        "n_ciclo": contar_tardanzas_desde_ultimo_desbloqueo(idal),
        "reincidente": _es_reincidente(idal),
        "limite": calcular_limite(_es_reincidente(idal)),
        "bloqueado": alumno_bloqueado(idal) is not None
    }


def vista_perfil_completo(idal):
    d = perfil_alumno_datos(idal)
    if not d:
        st.warning("Alumno no encontrado.")
        return
    al = d["alumno"]
    usuario = st.session_state["user"]
    nombre = _nombre_completo(al)
    inicial = (al['apellido_paterno'] or al['nombres'] or "?")[0].upper()
    badge = "BLOQUEADO" if d["bloqueado"] else "ACTIVO"

    st.markdown(f"""
    <div class="perfil-hero">
        <div class="hero-avatar">{inicial}</div>
        <div class="hero-info">
            <div class="hero-nombre">{nombre}</div>
            <div class="hero-meta">{al['grado']} {al['seccion']} | Turno {al['turno']} | DNI {al['dni']}</div>
            <span class="hero-badge">{badge}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="kpi-grid">', unsafe_allow_html=True)
    st.markdown(f"""
        <div class="kpi-card"><div class="kpi-num">{d['total_puntuales']}</div><div class="kpi-lbl">Puntuales</div></div>
        <div class="kpi-card"><div class="kpi-num">{d['total_tardanzas']}</div><div class="kpi-lbl">Tardanzas</div></div>
        <div class="kpi-card"><div class="kpi-num">{d['total_faltas']}</div><div class="kpi-lbl">Faltas</div></div>
        <div class="kpi-card"><div class="kpi-num">{d['tard_injust']}</div><div class="kpi-lbl">Tard. Injust.</div></div>
        <div class="kpi-card"><div class="kpi-num">{d['n_ciclo']}</div><div class="kpi-lbl">Tard. ciclo</div></div>
        <div class="kpi-card"><div class="kpi-num">{d['limite']}</div><div class="kpi-lbl">Límite</div></div>
        <div class="kpi-card"><div class="kpi-num">{"SÍ" if d['reincidente'] else "NO"}</div><div class="kpi-lbl">Reincidente</div></div>
        <div class="kpi-card"><div class="kpi-num">{"SÍ" if d['bloqueado'] else "NO"}</div><div class="kpi-lbl">Bloqueado</div></div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Asistencias", "Tardanzas", "Bloqueos", "Permisos", "Justificaciones"])
    with tabs[0]:
        if d["asistencias"].empty:
            st.info("Sin asistencias")
        else:
            st.dataframe(d["asistencias"], use_container_width=True, hide_index=True)
    with tabs[1]:
        if d["tardanzas"].empty:
            st.info("Sin tardanzas")
        else:
            st.dataframe(d["tardanzas"], use_container_width=True, hide_index=True)
    with tabs[2]:
        if d["bloqueos"].empty:
            st.info("Sin bloqueos")
        else:
            st.dataframe(d["bloqueos"], use_container_width=True, hide_index=True)
    with tabs[3]:
        if d["permisos"].empty:
            st.info("Sin permisos")
        else:
            st.dataframe(d["permisos"], use_container_width=True, hide_index=True)
    with tabs[4]:
        if d["justificaciones_previas"].empty:
            st.info("Sin justificaciones")
        else:
            st.dataframe(d["justificaciones_previas"], use_container_width=True, hide_index=True)