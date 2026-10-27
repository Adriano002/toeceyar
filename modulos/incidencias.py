from db import obtener_conexion

def obtener_conexion():
    return obtener_conexion()


import base64
import hashlib
import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from .asistencia import auditar, obtener_periodo_activo, confirmar_accion
import pandas as pd
import qrcode
import streamlit as st
from components.firma import firma_widget, firma_guardada, limpiar_firma, tiene_firma
from components.qr_scanner import qr_scanner

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

from db import escribir, leer_df
from utils import (ahora, hoy_str, hora_corta, timestamp_str, mask_dni,
                   hashear_password, verificar_password)

LOG_DIR = Path("logs"); LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "incidencias.log", encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("incidencias")


TIPOS_INCIDENCIA = ["Leve", "Grave", "Muy grave"]
CATEGORIAS = ["Conducta", "Academico", "Salud", "Tardanza recurrente",
              "Falta de respeto", "Daño a propiedad", "Decomiso", "Otro"]
ESTADOS = ["Abierta", "En proceso", "Resuelta", "Archivada"]

ESTADOS_DECOMISO = ["Retenido", "Por devolver", "Devuelto", "Vencido"]
OBJETOS_COMUNES = ["Celular", "Cartera", "Perfume", "Audífonos", "Reloj",
                   "Joyas", "Billetera", "Mochila", "Otro"]

COLOR_AZUL = "#0A3D91"
COLOR_AZUL_DARK = "#072A63"
COLOR_AZUL_SOFT = "rgba(10,61,145,.08)"
COLOR_AZUL_BORDER = "rgba(10,61,145,.25)"
COLOR_AZUL_LIGHT = "#E8EFF9"

# UTILIDADES
def _nombre_archivo_acta(incidencia, alumno):
    def _limpiar(txt):
        if not txt:
            return "SinDato"
        txt = str(txt).strip()
        reemplazos = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U",
            "ñ": "n", "Ñ": "N", "ü": "u", "Ü": "U",
        }
        for k, v in reemplazos.items():
            txt = txt.replace(k, v)
        txt = re.sub(r"[^A-Za-z0-9]+", "_", txt)
        txt = re.sub(r"_+", "_", txt).strip("_")
        return txt or "SinDato"

    ap_p = _limpiar(alumno.get("apellido_paterno") if alumno else "")
    ap_m = _limpiar(alumno.get("apellido_materno") if alumno else "")
    nombres = _limpiar(alumno.get("nombres") if alumno else "")
    fecha = (incidencia.get("fecha") if incidencia else None) or hoy_str()
    return f"Acta_{ap_p}_{ap_m}_{nombres}_{fecha}.pdf"

def dias_desde(fecha_str):
    try:
        f = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        return (ahora().date() - f).days
    except Exception:
        return 0

def dias_hasta(fecha_str):
    try:
        f = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        return (f - ahora().date()).days
    except Exception:
        return 0


# TOASTS 
def mostrar_toast_pendiente():
    t = st.session_state.pop("_toast_msg", None)
    if t:
        if t.get("tipo") == "ok":
            st.success(t.get("msg"))
        elif t.get("tipo") == "warn":
            st.warning(t.get("msg"))
        else:
            st.error(t.get("msg"))

def guardar_toast(msg, tipo="ok"):
    st.session_state["_toast_msg"] = {"msg": msg, "tipo": tipo}

# HELPERS ALUMNOS 
def obtener_grados():
    df = leer_df("""SELECT DISTINCT grado FROM alumnos
                    WHERE activo=1 AND grado IS NOT NULL AND grado!=''
                    ORDER BY grado""")
    return [""] + df["grado"].tolist()

def obtener_secciones(grado=""):
    if grado:
        df = leer_df("""SELECT DISTINCT seccion FROM alumnos
                        WHERE activo=1 AND grado=? AND seccion IS NOT NULL
                        AND seccion!='' ORDER BY seccion""", (grado,))
    else:
        df = leer_df("""SELECT DISTINCT seccion FROM alumnos
                        WHERE activo=1 AND seccion IS NOT NULL
                        AND seccion!='' ORDER BY seccion""")
    return [""] + df["seccion"].tolist()

def buscar_alumno_por_dni(dni):
    con = obtener_conexion()
    cur = con.execute("SELECT * FROM alumnos WHERE dni=? AND activo=1", (dni,))
    f = cur.fetchone()
    return dict(f) if f else None

def _escape_like(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

def buscar_alumnos(texto="", grado="", seccion="", dni="", limite=300):
    q = """SELECT id,dni,nombres,apellido_paterno,apellido_materno,
           grado,seccion,turno,nombre_apoderado,telefono_apoderado,
           direccion,fecha_nacimiento,email_apoderado
           FROM alumnos WHERE activo=1"""
    p = []
    if texto:
        for w in [x.strip() for x in texto.split() if x.strip()]:
            q += (" AND (nombres LIKE ? ESCAPE '\\' OR apellido_paterno LIKE ? ESCAPE '\\' "
                  "OR apellido_materno LIKE ? ESCAPE '\\')")
            pat = f"%{_escape_like(w)}%"
            p += [pat, pat, pat]
    if dni:
        q += " AND dni LIKE ? ESCAPE '\\'"; p.append(f"%{_escape_like(dni)}%")
    if grado:
        q += " AND grado = ?"; p.append(grado)
    if seccion:
        q += " AND seccion = ?"; p.append(seccion)
    q += " ORDER BY apellido_paterno LIMIT ?"; p.append(limite)
    return leer_df(q, p)

def crear_alumno(dni, nombres, ap, am, grado, seccion, turno,
                 apo_n, apo_t, direccion, fecha_nac, email_apo, usuario):
    try:
        escribir("""INSERT INTO alumnos(dni,nombres,apellido_paterno,
                    apellido_materno,grado,seccion,turno,
                    nombre_apoderado,telefono_apoderado,direccion,
                    fecha_nacimiento,email_apoderado)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (dni or None, nombres, ap, am or None, grado, seccion, turno,
                  apo_n or None, apo_t or None, direccion or None,
                  fecha_nac or None, email_apo or None))
        auditar(usuario["usuario"], f"Creo alumno DNI {mask_dni(dni)}", "alumnos")
        return True, f"Alumno {nombres} creado."
    except Exception as e:
        if "unique" in str(e).lower():
            return False, f"Ya existe un alumno con DNI {mask_dni(dni)}"
        log.error("crear_alumno: %s", e)
        return False, "Error al crear."

def editar_alumno(idal, grado, seccion, turno, apo_n, apo_t,
                  direccion, fecha_nac, email_apo, usuario):
    escribir("""UPDATE alumnos SET grado=?,seccion=?,turno=?,
                nombre_apoderado=?,telefono_apoderado=?,direccion=?,
                fecha_nacimiento=?,email_apoderado=? WHERE id=?""",
             (grado, seccion, turno, apo_n or None, apo_t or None,
              direccion or None, fecha_nac or None, email_apo or None, idal))
    auditar(usuario["usuario"], f"Edito alumno id={idal}", "alumnos", idal)
    return True, "Alumno editado."

def retirar_alumno(idal, usuario):
    escribir("UPDATE alumnos SET activo=0 WHERE id=?", (idal,))
    auditar(usuario["usuario"], f"Desactivo alumno id={idal}", "alumnos", idal)
    return True, "Alumno desactivado."

def reactivar_alumno(idal, usuario):
    escribir("UPDATE alumnos SET activo=1 WHERE id=?", (idal,))
    auditar(usuario["usuario"], f"Reactivo alumno id={idal}", "alumnos", idal)
    return True, "Alumno reactivado."

def _obtener_alumno(al_id):
    con = obtener_conexion()
    cur = con.execute("SELECT * FROM alumnos WHERE id=?", (al_id,))
    f = cur.fetchone()
    return dict(f) if f else None

# INCIDENCIAS
def crear_incidencia(alumno_id, fecha, tipo, categoria, descripcion,
                     reportado_por, requiere_acta, tipo_acta, usuario):
    con = obtener_conexion()
    cur = con.execute("""INSERT INTO incidencias(alumno_id,fecha,hora,tipo,categoria,
                      descripcion,reportado_por,estado,requiere_acta,tipo_acta,
                      created_at)
                      VALUES(?,?,?,?,?,?,?,'Abierta',?,?,?)""",
                   (alumno_id, fecha, hora_corta(), tipo, categoria, descripcion,
                    reportado_por, 1 if requiere_acta else 0,
                    tipo_acta if requiere_acta else None, timestamp_str()))
    con.commit()
    inc_id = cur.lastrowid
    auditar(usuario["usuario"],
            f"Creo incidencia id={inc_id} para alumno_id={alumno_id}",
            "incidencias", inc_id)
    return True, "Incidencia registrada.", inc_id

def cambiar_estado_incidencia(inc_id, nuevo_estado, usuario):
    escribir("UPDATE incidencias SET estado=? WHERE id=?",
             (nuevo_estado, inc_id))
    auditar(usuario["usuario"],
            f"Cambio estado incidencia id={inc_id} a {nuevo_estado}",
            "incidencias", inc_id)
    return True, "Estado actualizado."

def eliminar_incidencia(inc_id, usuario):
    con = obtener_conexion()
    con.execute("DELETE FROM actas WHERE incidencia_id=?", (inc_id,))
    con.execute("UPDATE decomisos SET incidencia_id=NULL WHERE incidencia_id=?",
                (inc_id,))
    con.execute("DELETE FROM incidencias WHERE id=?", (inc_id,))
    con.commit()
    auditar(usuario["usuario"], f"Elimino incidencia id={inc_id}",
            "incidencias", inc_id)
    return True, "Incidencia eliminada."

def _obtener_incidencia(inc_id):
    con = obtener_conexion()
    cur = con.execute("SELECT * FROM incidencias WHERE id=?", (inc_id,))
    f = cur.fetchone()
    return dict(f) if f else None

# DECOMISOS
def crear_decomiso(alumno_id, incidencia_id, objeto, descripcion,
                   fecha_limite, usuario):
    if fecha_limite:
        try:
            fl = datetime.strptime(fecha_limite, "%Y-%m-%d").date()
            if fl < ahora().date():
                return False, f"Fecha de devolución {fecha_limite} ya pasó."
        except ValueError:
            return False, f"Fecha de devolución inválida: {fecha_limite}"
    escribir("""INSERT INTO decomisos(alumno_id,incidencia_id,fecha_decomiso,
                  hora_decomiso,objeto,descripcion,retenido_por,fecha_limite,
                  estado,created_at)
                  VALUES(?,?,?,?,?,?,?,?,'Retenido',?)""",
             (alumno_id, incidencia_id, hoy_str(), hora_corta(),
              objeto, descripcion or None, usuario["nombres"],
              fecha_limite or None, timestamp_str()))
    auditar(usuario["usuario"],
            f"Decomiso '{objeto}' a alumno_id={alumno_id}",
            "decomisos")
    return True, f"Decomiso de '{objeto}' registrado."

def crear_decomisos_batch(alumno_id, incidencia_id, lista_objetos, usuario):
    creados = 0
    errores = []
    for o in lista_objetos:
        if not o.get("objeto", "").strip():
            continue
        ok, msg = crear_decomiso(
            alumno_id, incidencia_id,
            o["objeto"].strip(),
            o.get("descripcion", "").strip(),
            o.get("fecha_limite"),
            usuario)
        if ok:
            creados += 1
        else:
            errores.append(msg)
    return creados, errores

def devolver_decomiso(dec_id, devuelto_a, observaciones, usuario):
    con = obtener_conexion()
    cur = con.execute("SELECT * FROM decomisos WHERE id=?", (dec_id,))
    f = cur.fetchone()
    if not f:
        return False, "Decomiso no encontrado."
    d = dict(f)
    if d["estado"] == "Devuelto":
        return False, "Este decomiso ya fue devuelto."
    escribir("""UPDATE decomisos SET estado='Devuelto',fecha_devolucion=?,
                devuelto_a=?,observaciones=? WHERE id=?""",
             (timestamp_str(), devuelto_a or None,
              observaciones or None, dec_id))
    auditar(usuario["usuario"],
            f"Devolvio decomiso id={dec_id} ({d['objeto']})",
            "decomisos", dec_id)
    return True, f"Decomiso de '{d['objeto']}' devuelto."

def cambiar_estado_decomiso(dec_id, nuevo_estado, usuario):
    escribir("UPDATE decomisos SET estado=? WHERE id=?",
             (nuevo_estado, dec_id))
    auditar(usuario["usuario"],
            f"Cambio estado decomiso id={dec_id} a {nuevo_estado}",
            "decomisos", dec_id)
    return True, "Estado actualizado."

def listar_decomisos_alumno(alumno_id):
    return leer_df("""SELECT id, fecha_decomiso, hora_decomiso, objeto,
                      descripcion, retenido_por, fecha_limite, estado,
                      fecha_devolucion, devuelto_a, observaciones
                      FROM decomisos WHERE alumno_id=?
                      ORDER BY estado!='Devuelto', fecha_decomiso DESC""",
                   (alumno_id,))

def listar_decomisos_activos():
    return leer_df("""SELECT d.id, d.fecha_decomiso, d.hora_decomiso,
                      d.objeto, d.descripcion, d.fecha_limite, d.estado,
                      al.id AS alumno_id,
                      al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS alumno,
                      al.grado, al.seccion
                      FROM decomisos d JOIN alumnos al ON d.alumno_id=al.id
                      WHERE d.estado != 'Devuelto'
                      ORDER BY d.fecha_decomiso DESC""")

def listar_decomisos_todos():
    return leer_df("""SELECT d.id, d.fecha_decomiso, d.hora_decomiso,
                      d.objeto, d.descripcion, d.fecha_limite, d.estado,
                      d.fecha_devolucion, d.devuelto_a,
                      al.id AS alumno_id,
                      al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS alumno,
                      al.grado, al.seccion
                      FROM decomisos d JOIN alumnos al ON d.alumno_id=al.id
                      ORDER BY d.estado='Devuelto', d.fecha_decomiso DESC""")

def actualizar_vencidos():
    try:
        escribir("""UPDATE decomisos SET estado='Vencido'
                    WHERE estado IN ('Retenido','Por devolver')
                      AND fecha_limite IS NOT NULL
                      AND fecha_limite < ?""", (hoy_str(),))
    except Exception as e:
        log.warning("actualizar_vencidos: %s", e)

# PDF ACTA 
def _wrap_text(texto, ancho):
    palabras = str(texto).split()
    lineas = []
    actual = ""
    for p in palabras:
        if len(actual) + len(p) + 1 <= ancho:
            actual = (actual + " " + p).strip()
        else:
            if actual:
                lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas or [""]

def generar_pdf_acta(incidencia, alumno, acta_data):
    if not alumno:
        alumno = {}
    if not incidencia:
        incidencia = {}
    buf = BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=A4)
    width, height = A4

    c.setFillColorRGB(0.039, 0.239, 0.568)
    c.rect(0, height - 3.8*cm, width, 3.8*cm, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2*cm, height - 1.5*cm, "ACTA DE INCIDENCIA")

    c.setFont("Helvetica-Bold", 12)
    nombre_al_cab = (f"{alumno.get('apellido_paterno','')} "
                     f"{alumno.get('apellido_materno','') or ''}, "
                     f"{alumno.get('nombres','')}")
    c.drawString(2*cm, height - 2.2*cm, f"Alumno: {nombre_al_cab}")

    c.setFont("Helvetica", 11)
    c.drawString(2*cm, height - 2.75*cm,
                 f"Fecha de incidencia: {incidencia.get('fecha','')} "
                 f"{incidencia.get('hora','')}")

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(2*cm, height - 3.25*cm,
                 f"Acta emitida: {timestamp_str()}")

    y = height - 4.8*cm
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Datos del alumno")
    y -= 0.7*cm
    c.setFont("Helvetica", 11)
    nombre_al = (f"{alumno.get('apellido_paterno','')} "
                 f"{alumno.get('apellido_materno','') or ''}, "
                 f"{alumno.get('nombres','')}")
    c.drawString(2*cm, y, f"Nombre: {nombre_al}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"DNI: {alumno.get('dni','')}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Grado y sección: {alumno.get('grado','')} "
                          f"{alumno.get('seccion','')}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Turno: {alumno.get('turno','') or '-'}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Apoderado: {alumno.get('nombre_apoderado','') or '-'}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Teléfono apoderado: "
                          f"{alumno.get('telefono_apoderado','') or '-'}")

    y -= 0.9*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Datos de la incidencia")
    y -= 0.7*cm
    c.setFont("Helvetica", 11)
    c.drawString(2*cm, y, f"Fecha: {incidencia.get('fecha','')} "
                          f"{incidencia.get('hora','')}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Tipo: {incidencia.get('tipo','')}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Categoría: {incidencia.get('categoria','') or '-'}")
    y -= 0.55*cm
    c.drawString(2*cm, y, f"Reportado por: {incidencia.get('reportado_por','')}")

    y -= 0.9*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Descripción de los hechos")
    y -= 0.7*cm
    c.setFont("Helvetica", 10)
    texto = incidencia.get("descripcion", "") or ""
    for linea in _wrap_text(texto, 95):
        c.drawString(2*cm, y, linea)
        y -= 0.5*cm
        if y < 6*cm:
            c.showPage()
            y = height - 2*cm
            c.setFont("Helvetica", 10)

    y -= 0.5*cm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Observaciones / Acuerdos")
    y -= 0.7*cm
    c.setFont("Helvetica", 10)
    obs = acta_data.get("observaciones", "") or ""
    for linea in _wrap_text(obs, 95):
        c.drawString(2*cm, y, linea)
        y -= 0.5*cm
        if y < 6*cm:
            c.showPage()
            y = height - 2*cm
            c.setFont("Helvetica", 10)

    y -= 1.4*cm
    if y < 8*cm:
        c.showPage()
        y = height - 3*cm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, y, "Firmas")
    y -= 1.2*cm

    firma_al = acta_data.get("firma_alumno_base64")
    if firma_al:
        try:
            img_bytes = base64.b64decode(firma_al.split(",")[-1])
            img = ImageReader(BytesIO(img_bytes))
            c.drawImage(img, 2*cm, y - 2.5*cm, width=6*cm, height=2.2*cm,
                        preserveAspectRatio=True, mask='auto')
        except Exception as e:
            log.warning("firma alumno pdf: %s", e)
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, y - 3*cm, "____________________________")
    c.drawString(2*cm, y - 3.5*cm,
                 f"Alumno: {acta_data.get('nombre_alumno','') or nombre_al}")

    firma_apo = acta_data.get("firma_apoderado_base64")
    if firma_apo:
        try:
            img_bytes = base64.b64decode(firma_apo.split(",")[-1])
            img = ImageReader(BytesIO(img_bytes))
            c.drawImage(img, 10*cm, y - 2.5*cm, width=6*cm, height=2.2*cm,
                        preserveAspectRatio=True, mask='auto')
        except Exception as e:
            log.warning("firma apoderado pdf: %s", e)
    c.setFont("Helvetica", 10)
    c.drawString(10*cm, y - 3*cm, "____________________________")
    c.drawString(10*cm, y - 3.5*cm,
                 f"Apoderado: {acta_data.get('nombre_apoderado','') or alumno.get('nombre_apoderado','') or '-'}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()

def crear_acta_doble(incidencia_id, firmante, firma_alumno, firma_apoderado,
                     obs, nombre_alumno, nombre_apoderado, usuario):
    con = obtener_conexion()
    cur = con.execute("SELECT * FROM incidencias WHERE id=?", (incidencia_id,))
    inc = cur.fetchone()
    if not inc:
        return False, "Incidencia no encontrada."
    inc = dict(inc)

    if not inc.get("requiere_acta"):
        return False, ("Esta incidencia no requiere acta. "
                       "Si necesitas firmar una, marca 'requiere acta' primero.")

    cur = con.execute("SELECT * FROM alumnos WHERE id=?", (inc["alumno_id"],))
    al = cur.fetchone()
    if not al:
        return False, "Alumno no encontrado."
    al = dict(al)

    if not firma_alumno or not firma_apoderado:
        return False, "Faltan firmas."
    if firma_alumno == firma_apoderado:
        return False, ("Las firmas del alumno y del apoderado son idénticas. "
                       "Vuelve a firmar cada una por separado.")

    acta_data = {
        "tipo": "alumno_apoderado",
        "firmante_nombre": firmante,
        "observaciones": obs,
        "firma_alumno_base64": firma_alumno,
        "firma_apoderado_base64": firma_apoderado,
        "nombre_alumno": nombre_alumno,
        "nombre_apoderado": nombre_apoderado,
    }
    pdf_bytes = generar_pdf_acta(inc, al, acta_data)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

    escribir("""INSERT INTO actas(incidencia_id,tipo,firmante_nombre,
                firma_base64,firmado_en,observaciones,
                firma_alumno_base64,firma_apoderado_base64,
                nombre_alumno,nombre_apoderado,pdf_base64)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
             (incidencia_id, "alumno_apoderado", firmante,
              firma_apoderado or firma_alumno, timestamp_str(), obs or None,
              firma_alumno, firma_apoderado, nombre_alumno, nombre_apoderado,
              pdf_b64))
    auditar(usuario["usuario"],
            f"Firmo acta (alumno+apoderado) incidencia id={incidencia_id}",
            "actas", incidencia_id)
    return True, "Acta firmada y PDF generado."

def actas_de_incidencia(inc_id):
    return leer_df("""SELECT id,tipo,firmante_nombre,firmado_en,
                      observaciones,nombre_alumno,nombre_apoderado,
                      pdf_base64
                      FROM actas
                      WHERE incidencia_id=? ORDER BY id""", (inc_id,))

# ESCANER 
def componente_escaner(key):
    mount_id = st.session_state.get(f"_qr_mount_{key}", 0)
    result = qr_scanner(key=f"qr_{key}_{mount_id}", on_scan=lambda: None)
    if result is not None and getattr(result, "qr_dni", None):
        return str(result.qr_dni).strip()
    return None

def escaner_widget(key="escaner"):
    dni = componente_escaner(key)
    if not dni:
        return None
    procesado_key = f"_qr_procesado_{key}"
    ult = st.session_state.get(procesado_key, {})
    if ult.get("dni") == dni and (time.time() - ult.get("ts", 0)) < 3.0:
        return None
    st.session_state[procesado_key] = {"dni": dni, "ts": time.time()}
    st.session_state[f"_qr_mount_{key}"] = \
        st.session_state.get(f"_qr_mount_{key}", 0) + 1
    al = buscar_alumno_por_dni(dni)
    if al:
        return al
    st.error(f"No hay alumno con DNI {mask_dni(dni)}")
    return None

def limpiar_escaner(key):
    st.session_state.pop(f"_qr_procesado_{key}", None)
    st.session_state.pop(f"_ult_qr_{key}", None)
    st.session_state.pop(f"_scan_alumno_{key}", None)

# ==========================================
# VISTA ESCANER (FLUJO NUEVO EN PANTALLA ÚNICA)
# ==========================================
def vista_escaner():
    mostrar_toast_pendiente()
    st.title("Escáner QR")
    
    if st.session_state.pop("_reset_escaner", False):
        st.session_state.pop("_scan_alumno_qr", None)
        st.session_state.pop("scan_accion", None)
        st.session_state.pop("scan_tipo", None)
        limpiar_escaner("qr")

    if "_scan_alumno_qr" not in st.session_state:
        al = escaner_widget("qr")
        if al: st.session_state["_scan_alumno_qr"] = al
        else: return

    al = st.session_state["_scan_alumno_qr"]
    st.success(f"✓ {al['nombres']} {al['apellido_paterno']} — {al['grado'] or ''} {al['seccion'] or ''} — DNI {mask_dni(al['dni'])}")
    
    if st.button("🔄 Escanear otro alumno", key="reset_scan"):
        st.session_state["_reset_escaner"] = True
        st.rerun()
        
    st.markdown("---")

    # 1. Preguntar acción (Ver perfil o Registrar)
    if "scan_accion" not in st.session_state:
        st.subheader("¿Qué deseas hacer?")
        c1, c2 = st.columns(2)
        if c1.button("Ver perfil", use_container_width=True):
            st.session_state["scan_accion"] = "ver"
            st.rerun()
        if c2.button("Registrar", type="primary", use_container_width=True):
            st.session_state["scan_accion"] = "registrar"
            st.rerun()
        return

    # 2. Si es Ver perfil
    if st.session_state["scan_accion"] == "ver":
        if st.button("← Volver", key="back_ver"):
            st.session_state.pop("scan_accion", None)
            st.rerun()
        _render_alumno_perfil(al, compact=False)
        return

    # 3. Si es Registrar -> Preguntar si es Incidencia o Decomiso
    if st.session_state["scan_accion"] == "registrar":
        if "scan_tipo" not in st.session_state:
            st.subheader("¿Qué deseas registrar?")
            c1, c2 = st.columns(2)
            if c1.button("Incidencia", type="primary", use_container_width=True):
                st.session_state["scan_tipo"] = "incidencia"
                st.rerun()
            if c2.button("Decomiso", type="primary", use_container_width=True):
                st.session_state["scan_tipo"] = "decomiso"
                st.rerun()
            if st.button("← Volver", key="back_reg"):
                st.session_state.pop("scan_accion", None)
                st.rerun()
            return

        # 3.1 Formulario de Incidencia
        if st.session_state["scan_tipo"] == "incidencia":
            st.subheader("Registrar Incidencia")
            if st.button("← Volver", key="back_inc"):
                st.session_state.pop("scan_tipo", None)
                st.rerun()
            
            with st.form("form_inc_scan"):
                c1, c2 = st.columns(2)
                with c1:
                    fecha = st.date_input("Fecha", value=ahora().date())
                    tipo_inc = st.selectbox("Gravedad", TIPOS_INCIDENCIA)
                with c2:
                    categoria = st.selectbox("Categoría", CATEGORIAS)
                    reportado = st.text_input("Reportado por", value=st.session_state["user"]["nombres"])
                
                descripcion = st.text_area("Descripción *")
                
                requiere_acta = st.checkbox("¿Requiere acta?")
                tipo_acta = None
                if requiere_acta:
                    tipo_acta = st.radio("Tipo de acta", ["alumno", "alumno_apoderado"], horizontal=True)
                
                sub = st.form_submit_button("Guardar Incidencia", type="primary")
                
                if sub:
                    if not descripcion.strip(): 
                        st.error("Descripción obligatoria.")
                    else:
                        ok, msg, inc_id = crear_incidencia(al["id"], fecha.strftime("%Y-%m-%d"), tipo_inc, categoria, descripcion.strip(), reportado.strip(), requiere_acta, tipo_acta, st.session_state["user"])
                        if ok:
                            # Se limpia todo para que puedas escanear otro o ver la incidencia
                            st.session_state.pop("scan_accion", None)
                            st.session_state.pop("scan_tipo", None)
                            guardar_toast(msg, "ok")
                            st.rerun()
                        else: 
                            st.error(msg)

        # 3.2 Formulario de Decomiso
        elif st.session_state["scan_tipo"] == "decomiso":
            st.subheader("Registrar Decomiso")
            if st.button("← Volver", key="back_dec"):
                st.session_state.pop("scan_tipo", None)
                st.rerun()
            
            with st.form("form_dec_scan"):
                st.markdown("**Objetos a decomisar**")
                objetos = []
                for i in range(3):
                    c1, c2, c3 = st.columns([3, 2, 4])
                    with c1: 
                        obj = st.text_input(f"Objeto {i+1}", key=f"scan_dec_obj_{i}", placeholder="Celular, cartera...")
                    with c2: 
                        f_lim = st.date_input(f"Fecha de devolución {i+1}", value=ahora().date() + timedelta(days=3), key=f"scan_dec_fl_{i}")
                    with c3: 
                        desc = st.text_input(f"Descripción {i+1}", key=f"scan_dec_desc_{i}", placeholder="Marca, color...")
                    if obj.strip():
                        objetos.append({"objeto": obj.strip(), "fecha_limite": f_lim.strftime("%Y-%m-%d"), "descripcion": desc.strip()})
                
                sub = st.form_submit_button("Guardar Decomisos", type="primary")
                if sub:
                    if not objetos: 
                        st.error("Agrega al menos un objeto.")
                    else:
                        n, errs = crear_decomisos_batch(al["id"], None, objetos, st.session_state["user"])
                        if n:
                            st.session_state.pop("scan_accion", None)
                            st.session_state.pop("scan_tipo", None)
                            guardar_toast(f"{n} decomiso(s) registrado(s).", "ok")
                            st.rerun()
                        for e in errs: 
                            st.warning(e)

# ==========================================
# PERFIL ALUMNO Y OTRAS VISTAS
# ==========================================
def _render_alumno_perfil(al, compact=False, key_scan=None):
    idal = al["id"]
    nombre = (al['apellido_paterno'] + " " + (al['apellido_materno'] or "") + ", " + al['nombres'])
    inicial = (al['apellido_paterno'] or al['nombres'] or "?")[0].upper()
    estado_txt = "ACTIVO" if al.get("activo", 1) else "INACTIVO"
    
    st.markdown(f"""
    <div class="alumno-hero">
        <div class="hero-avatar">{inicial}</div>
        <div class="hero-info">
            <div class="hero-nombre">{nombre}</div>
            <div class="hero-meta">
                {al['grado'] or ''} {al['seccion'] or ''} &nbsp;·&nbsp;
                Turno {al['turno'] or '-'} &nbsp;·&nbsp;
                DNI {mask_dni(al['dni'])}
            </div>
            <span class="hero-badge">{estado_txt}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if compact:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Ver perfil completo", type="primary", use_container_width=True, key="ver_full_perfil"):
                st.session_state["alumno_perfil_id"] = idal
                st.session_state["_ir_a_menu"] = "Alumnos"
                st.rerun()
        with c2:
            if st.button("Registrar incidencia", use_container_width=True, key="registrar_inc"):
                st.session_state["scan_accion"] = "registrar"
                st.session_state["scan_tipo"] = "incidencia"
                st.rerun()
        return

    incs = leer_df("""SELECT id, fecha, hora, tipo, categoria, estado,
                      requiere_acta, tipo_acta, descripcion, reportado_por
                      FROM incidencias WHERE alumno_id=?
                      ORDER BY fecha DESC, hora DESC""", (idal,))
    decomisos = listar_decomisos_alumno(idal)

    n_total = len(incs)
    n_abiertas = int((incs["estado"] == "Abierta").sum()) if not incs.empty else 0
    n_proceso = int((incs["estado"] == "En proceso").sum()) if not incs.empty else 0
    n_resueltas = int((incs["estado"] == "Resuelta").sum()) if not incs.empty else 0
    dec_activos = int((decomisos["estado"] != "Devuelto").sum()) if not decomisos.empty else 0

    st.markdown(f"""
    <div class="kpi-grid">
        <div class="kpi">
            <div class="kpi-num">{n_total}</div>
            <div class="kpi-lbl">Total incidencias</div>
        </div>
        <div class="kpi kpi-warn">
            <div class="kpi-num">{n_abiertas}</div>
            <div class="kpi-lbl">Abiertas</div>
        </div>
        <div class="kpi kpi-warn">
            <div class="kpi-num">{n_proceso}</div>
            <div class="kpi-lbl">En proceso</div>
        </div>
        <div class="kpi kpi-ok">
            <div class="kpi-num">{n_resueltas}</div>
            <div class="kpi-lbl">Resueltas</div>
        </div>
        <div class="kpi {'kpi-alerta' if dec_activos > 0 else ''}">
            <div class="kpi-num">{dec_activos}</div>
            <div class="kpi-lbl">Decomisos activos</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""
        <div class="card">
            <div class="card-title">Datos del alumno</div>
            <div class="info-line"><span class="info-label">Nombre</span>
                <span class="info-valor">{nombre}</span></div>
            <div class="info-line"><span class="info-label">DNI</span>
                <span class="info-valor">{mask_dni(al['dni'])}</span></div>
            <div class="info-line"><span class="info-label">Grado / Sección</span>
                <span class="info-valor">{al['grado'] or '-'} {al['seccion'] or ''}</span></div>
            <div class="info-line"><span class="info-label">Turno</span>
                <span class="info-valor">{al['turno'] or '-'}</span></div>
            <div class="info-line"><span class="info-label">F. nacimiento</span>
                <span class="info-valor">{al.get('fecha_nacimiento') or '-'}</span></div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="card">
            <div class="card-title">Apoderado</div>
            <div class="info-line"><span class="info-label">Nombre</span>
                <span class="info-valor">{al.get('nombre_apoderado') or '-'}</span></div>
            <div class="info-line"><span class="info-label">Teléfono</span>
                <span class="info-valor">{al.get('telefono_apoderado') or '-'}</span></div>
            <div class="info-line"><span class="info-label">Email</span>
                <span class="info-valor">{al.get('email_apoderado') or '-'}</span></div>
            <div class="info-line"><span class="info-label">Dirección</span>
                <span class="info-valor">{al.get('direccion') or '-'}</span></div>
        </div>
        """, unsafe_allow_html=True)

    tabs = st.tabs(["Incidencias", "Decomisos", "Editar datos"])

    with tabs[0]:
        if incs.empty:
            st.info("Sin incidencias registradas.")
        else:
            for _, r in incs.iterrows():
                tipo_cls = {"Leve": "leve", "Grave": "grave",
                            "Muy grave": "muy-grave"}.get(r["tipo"], "")
                estado_cls = {"Resuelta": "resuelta", "En proceso": "proceso",
                              "Archivada": "archivada"}.get(r["estado"], "")
                st.markdown(f"""
                <div class="inc-card {tipo_cls}">
                    <div class="inc-head">
                        <span class="inc-tipo">{r['tipo']} · {r['categoria'] or 'Sin categoría'}</span>
                        <span class="inc-estado {estado_cls}">{r['estado']}</span>
                    </div>
                    <div class="inc-meta">{r['fecha']} {r['hora']} — Reportado por {r['reportado_por']}</div>
                    <div class="inc-desc">{r['descripcion']}</div>
                </div>
                """, unsafe_allow_html=True)
                cc1, cc2 = st.columns([4, 1])
                with cc2:
                    if st.button("Ver detalle", key=f"ver_inc_perf_{r['id']}",
                                 use_container_width=True):
                        st.session_state["incidencia_ver_id"] = r["id"]; st.rerun()

    with tabs[1]:
        _render_decomisos_tab(decomisos, idal)

    with tabs[2]:
        _render_editar_alumno(al)


def _render_decomisos_tab(decomisos, idal):
    if decomisos.empty:
        st.info("Sin decomisos registrados para este alumno.")
        return
    usuario = st.session_state["user"]
    for _, d in decomisos.iterrows():
        estado = d["estado"]
        dias_ret = dias_desde(d["fecha_decomiso"])
        if d["fecha_limite"]:
            dias_lim = dias_hasta(d["fecha_limite"])
            if dias_lim < 0:
                contador_txt = f"🔴 PLAZO VENCIDO hace {abs(dias_lim)} día(s) — DEVOLVER OBJETO"
            elif dias_lim == 0:
                contador_txt = "🟠 Vence HOY — DEVOLVER OBJETO"
            elif dias_lim <= 2:
                contador_txt = f"🟡 Vence en {dias_lim} día(s) — preparar devolución"
            else:
                contador_txt = f"🟢 Fecha de devolución en {dias_lim} día(s)"
        else:
            contador_txt = "⚪ Sin fecha límite"
        cls = "devuelto" if estado == "Devuelto" else \
              ("vencido" if estado == "Vencido" else "")
        contador_html = (
            f'<div class="dec-contador dec-contador-alerta">{contador_txt}</div>'
            if "DEVOLVER" in contador_txt
            else f'<div class="dec-contador">{contador_txt}</div>'
        )
        st.markdown(f"""
        <div class="decomiso-card {cls}">
            <div class="dec-obj">{d['objeto']}</div>
            <div class="dec-meta">
                Retenido el {d['fecha_decomiso']} {d['hora_decomiso']}
                por {d['retenido_por']} — {dias_ret} día(s)
            </div>
            <div class="dec-meta">Estado: <b>{estado}</b>
                {('— Límite: ' + d['fecha_limite']) if d['fecha_limite'] else ''}
            </div>
            {contador_html}
            {('<div class="dec-meta">Descripción: ' + (d['descripcion'] or '') + '</div>') if d['descripcion'] else ''}
            {('<div class="dec-meta">Devuelto el ' + str(d['fecha_devolucion']) + ' a ' + str(d['devuelto_a'] or '-') + '</div>') if estado == "Devuelto" and d['fecha_devolucion'] else ''}
        </div>
        """, unsafe_allow_html=True)

        if estado != "Devuelto":
            with st.expander(f"Acciones decomiso #{d['id']} — {d['objeto']}"):
                c1, c2 = st.columns(2)
                with c1:
                    nuevo_estado = st.selectbox(
                        "Cambiar estado",
                        [e for e in ESTADOS_DECOMISO if e != "Devuelto"],
                        index=([e for e in ESTADOS_DECOMISO if e != "Devuelto"].index(estado)
                               if estado in [e for e in ESTADOS_DECOMISO if e != "Devuelto"] else 0),
                        key=f"dec_est_{d['id']}")
                    if st.button("Guardar estado", key=f"dec_est_btn_{d['id']}"):
                        cambiar_estado_decomiso(d["id"], nuevo_estado, usuario)
                        guardar_toast("Estado actualizado.")
                        st.rerun()
                with c2:
                    devuelto_a = st.text_input("Devuelto a",
                                               key=f"dec_da_{d['id']}")
                    obs_dev = st.text_input("Observaciones devolución",
                                            key=f"dec_obs_{d['id']}")
                    if st.button("Marcar como DEVUELTO",
                                 type="primary", key=f"dec_dev_{d['id']}"):
                        ok, msg = devolver_decomiso(d["id"], devuelto_a,
                                                    obs_dev, usuario)
                        if ok:
                            guardar_toast(msg)
                            st.rerun()
                        else:
                            st.error(msg)

def _render_editar_alumno(al):
    idal = al["id"]
    usuario = st.session_state["user"]
    with st.form("editar_al_perfil"):
        c1, c2 = st.columns(2)
        with c1:
            grado = st.text_input("Grado", value=al.get("grado") or "")
            seccion = st.text_input("Sección", value=al.get("seccion") or "")
            turno = st.selectbox("Turno", ["", "Mañana", "Tarde"],
                                 index=(["", "Mañana", "Tarde"].index(al["turno"])
                                        if al.get("turno") in ["", "Mañana", "Tarde"] else 0))
        with c2:
            apo_n = st.text_input("Apoderado",
                                  value=al.get("nombre_apoderado") or "")
            apo_t = st.text_input("Teléfono apoderado",
                                  value=al.get("telefono_apoderado") or "")
            email_apo = st.text_input("Email apoderado",
                                      value=al.get("email_apoderado") or "")
        direccion = st.text_input("Dirección", value=al.get("direccion") or "")
        fn = None
        if al.get("fecha_nacimiento"):
            try:
                fn = datetime.strptime(al["fecha_nacimiento"], "%Y-%m-%d").date()
            except Exception:
                fn = None
        fecha_nac = st.date_input("Fecha de nacimiento", value=fn)
        if st.form_submit_button("Guardar cambios", type="primary"):
            fn_s = fecha_nac.strftime("%Y-%m-%d") if fecha_nac else None
            editar_alumno(idal, grado, seccion, turno, apo_n, apo_t,
                          direccion, fn_s, email_apo, usuario)
            guardar_toast("Datos actualizados.")
            st.rerun()

    if usuario["rol"] in ("Admin", "Direccion"):
        st.markdown("---")
        st.markdown("**Zona crítica**")
        if al.get("activo", 1):
            if st.button("Desactivar alumno", key="desact_al"):
                retirar_alumno(idal, usuario)
                guardar_toast("Alumno desactivado.")
                st.rerun()
        else:
            if st.button("Reactivar alumno", key="react_al"):
                reactivar_alumno(idal, usuario)
                guardar_toast("Alumno reactivado.")
                st.rerun()

# VISTA ALUMNOS 
def vista_alumnos():
    mostrar_toast_pendiente()
    st.title("Alumnos")
    pid = st.session_state.get("alumno_perfil_id")
    if pid:
        al = _obtener_alumno(pid)
        if not al:
            st.warning("Alumno no encontrado.")
            st.session_state.pop("alumno_perfil_id", None); st.rerun()
        if st.button("← Volver a la lista", key="volver_perfil_al"):
            st.session_state.pop("alumno_perfil_id", None); st.rerun()
        _render_alumno_perfil(al)
        return

    if st.session_state.pop("_al_pendiente_ir_a_importar", False):
        st.session_state["al_vista_radio"] = "Importar Excel"

    if "al_vista_radio" not in st.session_state:
        st.session_state["al_vista_radio"] = "Buscar"

    opciones = ["Buscar", "Crear", "Importar Excel"]
    vista_sel = st.radio(
        "Vista",
        opciones,
        horizontal=True,
        key="al_vista_radio",
        label_visibility="collapsed"
    )

    if vista_sel == "Buscar":
        _al_buscar()
    elif vista_sel == "Crear":
        _al_crear()
    else:
        _al_importar()

def _al_buscar():
    st.subheader("Buscar alumno")
    c1, c2, c3 = st.columns([3, 1, 1])
    with c1:
        f_nombre = st.text_input("Nombre o apellido", key="al_f_nom")
    with c2:
        grados = obtener_grados()
        f_grado = st.selectbox("Grado", grados, key="al_f_grado")
    with c3:
        secciones = obtener_secciones(f_grado)
        f_seccion = st.selectbox("Sección", secciones, key="al_f_sec")
    if st.button("Buscar", type="primary", key="al_buscar_btn"):
        st.session_state["_al_buscar"] = True
    if st.session_state.get("_al_buscar"):
        df = buscar_alumnos(f_nombre, f_grado, f_seccion, "", limite=500)
        st.write(f"**{len(df)} resultados**")
        if df.empty:
            st.info("Sin resultados.")
        else:
            for _, al in df.iterrows():
                nombre = (al['apellido_paterno'] + " " +
                          (al['apellido_materno'] or "") + ", " + al['nombres'])
                c1, c2 = st.columns([5, 1])
                c1.markdown(
                    f"**{nombre}** &nbsp; — &nbsp; "
                    f"<span style='color:{COLOR_AZUL};font-weight:700;'>"
                    f"{al['grado'] or ''} {al['seccion'] or ''}</span> &nbsp;—&nbsp; "
                    f"DNI {mask_dni(al['dni'])}",
                    unsafe_allow_html=True)
                if c2.button("Ver perfil", key="ver_al_" + str(al['id'])):
                    st.session_state["alumno_perfil_id"] = al["id"]; st.rerun()

def _al_crear():
    st.subheader("Crear alumno")
    c1, c2 = st.columns(2)
    with c1:
        dni = st.text_input("DNI * (8 dígitos)", max_chars=8, key="nu_dni")
        nom = st.text_input("Nombres *", key="nu_nom")
        pat = st.text_input("Apellido Paterno *", key="nu_pat")
        mat = st.text_input("Apellido Materno", key="nu_mat")
    with c2:
        grado = st.text_input("Grado", key="nu_grado")
        seccion = st.text_input("Sección", key="nu_sec")
        turno = st.selectbox("Turno", ["", "Mañana", "Tarde"], key="nu_tur")
        fecha_nac = st.date_input("Fecha de nacimiento", value=None,
                                  key="nu_fnac")
    c3, c4 = st.columns(2)
    with c3:
        apo = st.text_input("Apoderado", key="nu_apo")
        tel = st.text_input("Teléfono apoderado", key="nu_tel")
    with c4:
        email_apo = st.text_input("Email apoderado", key="nu_email")
        direccion = st.text_input("Dirección", key="nu_dir")
    if st.button("Crear alumno", type="primary"):
        if not dni or not nom or not pat:
            st.error("Completa DNI, nombres y apellido paterno.")
        elif not re.fullmatch(r"\d{8}", dni.strip()):
            st.error("DNI inválido.")
        else:
            fn = fecha_nac.strftime("%Y-%m-%d") if fecha_nac else None
            ok, msg = crear_alumno(dni.strip(), nom.strip(), pat.strip(),
                                   mat.strip(), grado.strip(),
                                   seccion.strip(), turno,
                                   apo.strip(), tel.strip(),
                                   direccion.strip(), fn,
                                   email_apo.strip(),
                                   st.session_state["user"])
            if ok:
                st.session_state["al_vista_radio"] = "Crear"
                guardar_toast(msg)
                st.rerun()
            else:
                st.error(msg)

def _al_importar():
    st.subheader("Importar alumnos desde Excel")
    st.caption("Columnas: DNI, Nombres, Apellido Paterno, Apellido Materno, "
               "Grado, Sección, Turno, Apoderado, Teléfono.")
    arch = st.file_uploader("Sube el Excel", type=["xlsx", "xls"],
                            key="al_imp")
    if arch:
        df = pd.read_excel(arch)
        st.write(f"{len(df)} filas detectadas.")
        cols = list(df.columns)
        with st.form("mapeo_al"):
            c1, c2 = st.columns(2)
            with c1:
                m_dni = st.selectbox("DNI *", cols)
                m_nom = st.selectbox("Nombres *", cols)
                m_pat = st.selectbox("Apellido Paterno *", cols)
                m_mat = st.selectbox("Apellido Materno", [""] + cols)
            with c2:
                m_gra = st.selectbox("Grado", [""] + cols)
                m_sec = st.selectbox("Sección", [""] + cols)
                m_tur = st.selectbox("Turno", [""] + cols)
                m_apo = st.selectbox("Apoderado", [""] + cols)
                m_tel = st.selectbox("Teléfono", [""] + cols)
            validar = st.form_submit_button("Validar", type="primary")
        if validar:
            mapeo = {"dni": m_dni, "nombres": m_nom,
                     "apellido_paterno": m_pat,
                     "apellido_materno": m_mat, "grado": m_gra,
                     "seccion": m_sec, "turno": m_tur,
                     "apoderado_nombre": m_apo,
                     "apoderado_telefono": m_tel}
            val, errs, res = validar_importacion_alumnos(df, mapeo)
            st.session_state["_al_val"] = val
            st.session_state["_al_err"] = errs
            st.session_state["_al_res"] = res
        if "_al_res" in st.session_state:
            r = st.session_state["_al_res"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Total", r["total"])
            c2.metric("Válidas", r["validas"])
            c3.metric("Errores", r["errores"])
            if st.session_state["_al_err"]:
                with st.expander("Errores"):
                    st.dataframe(pd.DataFrame(st.session_state["_al_err"]),
                                 use_container_width=True)
                    if st.session_state["_al_val"]:
                        if confirmar_accion("al_imp", "Importar válidas",
                                    "¿Estás seguro de importar estos alumnos?"):
                            ins, reac, errs = insertar_alumnos_validos(
                        st.session_state["_al_val"])
                    for k in ["_al_val", "_al_err", "_al_res"]:
                        st.session_state.pop(k, None)
                    st.session_state["_al_pendiente_ir_a_importar"] = True
                    guardar_toast(f"{ins} nuevos, {reac} actualizados.")
                    st.rerun()
                    
def validar_importacion_alumnos(df, mapeo):
    errs, val = [], []
    vistos = set()
    for idx, fila in df.iterrows():
        nf = idx + 2
        try:
            def _l(v):
                if v is None: return ""
                if isinstance(v, float):
                    if pd.isna(v): return ""
                    if v == int(v): return str(int(v))
                    return str(v)
                s = str(v).strip()
                if s.endswith(".0") and s[:-2].isdigit(): s = s[:-2]
                return "" if s.lower() == "nan" else s
            dni = _l(fila[mapeo["dni"]])
            nom = _l(fila[mapeo["nombres"]])
            ap = _l(fila[mapeo["apellido_paterno"]])
            am = _l(fila[mapeo["apellido_materno"]]) if mapeo.get("apellido_materno") else ""
            gr = _l(fila[mapeo["grado"]]) if mapeo.get("grado") else ""
            sec = _l(fila[mapeo["seccion"]]) if mapeo.get("seccion") else ""
            tur = _l(fila[mapeo["turno"]]) if mapeo.get("turno") else ""
            an = _l(fila[mapeo["apoderado_nombre"]]) if mapeo.get("apoderado_nombre") else ""
            at = _l(fila[mapeo["apoderado_telefono"]]) if mapeo.get("apoderado_telefono") else ""

            if not dni or not re.fullmatch(r"\d{8}", dni):
                errs.append({"fila": nf, "motivo": "DNI invalido"}); continue
            if dni in vistos:
                errs.append({"fila": nf, "motivo": f"DNI {mask_dni(dni)} duplicado"}); continue
            if not nom or not ap:
                errs.append({"fila": nf, "motivo": "Faltan nombres"}); continue
            vistos.add(dni)
            val.append({"dni": dni, "nombres": nom, "apellido_paterno": ap,
                        "apellido_materno": am, "grado": gr, "seccion": sec,
                        "turno": tur, "apoderado_nombre": an,
                        "apoderado_telefono": at})
        except Exception as e:
            errs.append({"fila": nf, "motivo": str(e)})
    return val, errs, {"total": len(df), "validas": len(val), "errores": len(errs)}

def insertar_alumnos_validos(val):
    ins = reac = 0
    errs = []
    con = obtener_conexion()
    for d in val:
        try:
            cur = con.execute("SELECT id FROM alumnos WHERE dni=?", (d["dni"],))
            ex = cur.fetchone()
            if ex:
                con.execute("""UPDATE alumnos SET nombres=?,apellido_paterno=?,
                               apellido_materno=?,grado=?,seccion=?,turno=?,
                               nombre_apoderado=?,telefono_apoderado=?,activo=1
                               WHERE id=?""",
                            (d["nombres"], d["apellido_paterno"],
                             d["apellido_materno"] or None, d["grado"], d["seccion"],
                             d["turno"], d["apoderado_nombre"] or None,
                             d["apoderado_telefono"] or None, ex["id"]))
                reac += 1
            else:
                con.execute("""INSERT INTO alumnos(dni,nombres,apellido_paterno,
                               apellido_materno,grado,seccion,turno,
                               nombre_apoderado,telefono_apoderado,activo)
                               VALUES(?,?,?,?,?,?,?,?,?,1)""",
                            (d["dni"], d["nombres"], d["apellido_paterno"],
                             d["apellido_materno"] or None, d["grado"], d["seccion"],
                             d["turno"], d["apoderado_nombre"] or None,
                             d["apoderado_telefono"] or None))
                ins += 1
        except Exception as e:
            errs.append(f"{mask_dni(d['dni'])}: {e}")
    con.commit()
    return ins, reac, errs
#VISTA INCIDENCIAS 
def vista_incidencias():
    mostrar_toast_pendiente()
    st.title("Incidencias")
    pid = st.session_state.get("incidencia_ver_id")
    if pid:
        vista_detalle_incidencia(pid); return

    if "inc_vista_radio" not in st.session_state:
        st.session_state["inc_vista_radio"] = "Listar"

    opciones = ["Listar", "Crear"]
    vista_sel = st.radio(
        "Vista",
        opciones,
        horizontal=True,
        key="inc_vista_radio",
        label_visibility="collapsed"
    )

    if vista_sel == "Listar":
        _inc_listar()
    else:
        _inc_crear()

def _inc_listar():
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        filtro_estado = st.selectbox("Estado", ["Todos"] + ESTADOS,
                                     key="inc_f_estado")
    with c2:
        filtro_tipo = st.selectbox("Tipo", ["Todos"] + TIPOS_INCIDENCIA,
                                   key="inc_f_tipo")
    with c3:
        filtro_texto = st.text_input("Buscar alumno",
                                     key="inc_f_texto",
                                     placeholder="Nombre o DNI")
    q = """SELECT i.id, i.fecha, i.hora, i.tipo, i.categoria, i.estado,
           i.requiere_acta, i.tipo_acta, i.descripcion,
           al.id AS alumno_id,
           al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS alumno,
           al.grado, al.seccion
           FROM incidencias i JOIN alumnos al ON i.alumno_id=al.id WHERE 1=1"""
    p = []
    if filtro_estado != "Todos":
        q += " AND i.estado=?"; p.append(filtro_estado)
    if filtro_tipo != "Todos":
        q += " AND i.tipo=?"; p.append(filtro_tipo)
    if filtro_texto.strip():
        pat = f"%{_escape_like(filtro_texto.strip())}%"
        q += (" AND (al.nombres LIKE ? ESCAPE '\\' OR al.apellido_paterno LIKE ? ESCAPE '\\' "
              "OR al.dni LIKE ? ESCAPE '\\')")
        p += [pat, pat, pat]
    q += " ORDER BY i.fecha DESC, i.hora DESC LIMIT 500"
    df = leer_df(q, p)
    st.write(f"**{len(df)} incidencias**")
    if df.empty:
        st.info("Sin incidencias.")
    else:
        for _, r in df.iterrows():
            tipo_cls = {"Leve": "leve", "Grave": "grave",
                        "Muy grave": "muy-grave"}.get(r["tipo"], "")
            estado_cls = {"Resuelta": "resuelta", "En proceso": "proceso",
                          "Archivada": "archivada"}.get(r["estado"], "")
            st.markdown(f"""
            <div class="inc-card {tipo_cls}">
                <div class="inc-head">
                    <span class="inc-tipo">{r['alumno']}</span>
                    <span class="inc-estado {estado_cls}">{r['estado']}</span>
                </div>
                <div class="inc-meta">{r['fecha']} {r['hora']} — {r['grado'] or ''} {r['seccion'] or ''} — {r['tipo']} · {r['categoria'] or 'Sin categoría'}</div>
                <div class="inc-desc">{r['descripcion'][:180]}{'...' if len(r['descripcion']) > 180 else ''}</div>
            </div>
            """, unsafe_allow_html=True)
            cc1, cc2 = st.columns([4, 1])
            with cc2:
                if st.button("Ver detalle", key="ver_inc_" + str(r['id']),
                             use_container_width=True):
                    st.session_state["incidencia_ver_id"] = r["id"]; st.rerun()

def _parse_decomisos(texto):
    """
    Parsea el texto de decomisos.
    Formato esperado: objeto | fecha_límite (YYYY-MM-DD) | descripción
    Una línea por objeto.
    """
    lista = []
    errores = []
    for i, linea in enumerate(texto.strip().split("\n"), 1):
        linea = linea.strip()
        if not linea:
            continue
        partes = [p.strip() for p in linea.split("|")]
        if len(partes) < 2:
            errores.append(f"Línea {i}: formato inválido (falta la fecha)")
            continue
        objeto = partes[0]
        fecha_limite = partes[1]
        descripcion = partes[2] if len(partes) > 2 else ""
        if not objeto:
            errores.append(f"Línea {i}: objeto vacío")
            continue
        try:
            datetime.strptime(fecha_limite, "%Y-%m-%d")
        except ValueError:
            errores.append(f"Línea {i}: fecha '{fecha_limite}' inválida (usar YYYY-MM-DD)")
            continue
        lista.append({
            "objeto": objeto,
            "fecha_limite": fecha_limite,
            "descripcion": descripcion,
        })
    return lista, errores

def _inc_crear():
    st.subheader("Nueva incidencia")
    st.caption("Para escanear QR, ve a 'Escaner QR' en el menú lateral.")
    al = buscar_alumno_widget("inc_nueva")
    if not al:
        return
    st.markdown("---")
    st.markdown(f"""
    <div class="card">
        <div class="info-line"><span class="info-label">Alumno</span>
            <span class="info-valor">{al['nombres']} {al['apellido_paterno']} {al['apellido_materno'] or ''}</span></div>
        <div class="info-line"><span class="info-label">Grado/Sección</span>
            <span class="info-valor">{al['grado'] or ''} {al['seccion'] or ''}</span></div>
        <div class="info-line"><span class="info-label">DNI</span>
            <span class="info-valor">{mask_dni(al['dni'])}</span></div>
    </div>
    """, unsafe_allow_html=True)
    with st.form("form_inc"):
        c1, c2 = st.columns(2)
        with c1:
            fecha = st.date_input("Fecha", value=ahora().date(), key="inc_fecha")
            tipo = st.selectbox("Tipo", TIPOS_INCIDENCIA, key="inc_tipo")
        with c2:
            categoria = st.selectbox("Categoría", CATEGORIAS, key="inc_cat")
            reportado = st.text_input(
                "Reportado por",
                value=st.session_state["user"]["nombres"],
                key="inc_rep")
        descripcion = st.text_area("Descripción *", key="inc_desc",
                                   placeholder="Describe lo ocurrido")
        st.markdown("---")
        requiere_acta = st.checkbox("¿Requiere acta?", key="inc_req_acta")
        tipo_acta = None
        if requiere_acta:
            tipo_acta = st.radio(
                "Tipo de acta",
                ["alumno", "apoderado", "alumno_apoderado"],
                key="inc_tipo_acta", horizontal=True)
        requiere_decomiso = st.checkbox("¿Requiere decomiso?", key="inc_req_dec")
        decomisos_txt = ""
        if requiere_decomiso:
            st.caption("Escribe UN objeto por línea. Formato:")
            st.caption("**objeto | fecha_límite (YYYY-MM-DD) | descripción**")
            st.caption("Ejemplo: `Celular | 2026-01-20 | Samsung negro`")
            decomisos_txt = st.text_area("Objetos decomisados",
                                         key="inc_dec_txt", height=120)
        sub = st.form_submit_button("Registrar incidencia", type="primary")
    if sub:
        if not descripcion.strip():
            st.error("La descripción es obligatoria.")
        else:
            ok, msg, inc_id = crear_incidencia(
                al["id"], fecha.strftime("%Y-%m-%d"), tipo, categoria,
                descripcion.strip(), reportado.strip(),
                requiere_acta, tipo_acta, st.session_state["user"])
            if not ok:
                st.error(msg); return
            if requiere_decomiso and decomisos_txt.strip():
                lista, errores = _parse_decomisos(decomisos_txt)
                if errores:
                    for e in errores:
                        st.warning(e)
                if lista:
                    n, errs_batch = crear_decomisos_batch(al["id"], inc_id, lista,
                                                          st.session_state["user"])
                    if n:
                        msg += f" ({n} decomiso(s) registrado(s))"
                    for e in errs_batch:
                        st.warning(e)
            st.session_state["inc_vista_radio"] = "Crear"
            guardar_toast(msg)
            st.rerun()

def vista_detalle_incidencia(inc_id):
    mostrar_toast_pendiente()
    if st.button("← Volver a incidencias", key="volver_inc"):
        st.session_state.pop("incidencia_ver_id", None); st.rerun()
    r = _obtener_incidencia(inc_id)
    if not r:
        st.warning("Incidencia no encontrada.")
        st.session_state.pop("incidencia_ver_id", None); return
    al = _obtener_alumno(r["alumno_id"])
    if not al:
        st.warning("Alumno no encontrado.")
        st.session_state.pop("incidencia_ver_id", None); return
    nombre = (al['apellido_paterno'] + " " + (al['apellido_materno'] or "") +
              ", " + al['nombres'])
    st.subheader(nombre)
    st.write(f"**Grado y sección:** {al['grado'] or ''} {al['seccion'] or ''}")
    st.write(f"**DNI:** {mask_dni(al['dni'])}")
    st.write(f"**Tipo:** {r['tipo']} — **Estado:** {r['estado']}")
    st.markdown("---")
    st.subheader("Detalle de la incidencia")
    st.write(f"**Fecha:** {r['fecha']} {r['hora']}")
    st.write(f"**Categoría:** {r['categoria'] or '-'}")
    st.write(f"**Reportado por:** {r['reportado_por']}")
    st.write(f"**Descripción:** {r['descripcion']}")
    st.write(f"**Requiere acta:** "
             f"{'Sí (' + (r['tipo_acta'] or '') + ')' if r['requiere_acta'] else 'No'}")

    decs = leer_df("""SELECT id,objeto,descripcion,fecha_decomiso,hora_decomiso,
                      fecha_limite,estado,fecha_devolucion,devuelto_a,retenido_por
                      FROM decomisos WHERE incidencia_id=?""", (inc_id,))
    if not decs.empty:
        st.markdown("---")
        st.subheader("Decomisos asociados")
        _render_decomisos_tab(decs, al["id"])
    else:
        st.markdown("---")
        st.info("Sin decomisos asociados a esta incidencia.")

    st.markdown("---")
    st.subheader("Cambiar estado")
    nuevo = st.selectbox("Estado", ESTADOS,
                         index=ESTADOS.index(r["estado"]) if r["estado"] in ESTADOS else 0,
                         key="inc_nuevo_estado")
    if st.button("Actualizar estado", type="primary"):
        ok, msg = cambiar_estado_incidencia(inc_id, nuevo, st.session_state["user"])
        if ok:
            guardar_toast(msg)
            st.rerun()

        st.markdown("---")
    st.subheader("Eliminar incidencia")
    if confirmar_accion(f"elim_inc_{inc_id}", "Eliminar incidencia",
                        "¿Estás seguro de eliminar esta incidencia? Es irreversible."):
        ok, msg = eliminar_incidencia(inc_id, st.session_state["user"])
        st.session_state.pop("incidencia_ver_id", None)
        guardar_toast(msg)
        st.rerun()

    st.markdown("---")
    actas = actas_de_incidencia(inc_id)
    if r["requiere_acta"]:
        st.subheader("Actas firmadas")
        if actas.empty:
            st.warning("Falta firmar acta.")
        else:
            for _, act in actas.iterrows():
                st.write(f"**Acta #{act['id']}** — {act['tipo']} — "
                         f"Firmante: {act['firmante_nombre']} — "
                         f"{act['firmado_en']}")
                if act.get("nombre_alumno"):
                    st.caption(f"Alumno: {act['nombre_alumno']}")
                if act.get("nombre_apoderado"):
                    st.caption(f"Apoderado: {act['nombre_apoderado']}")
                pdf_b64 = act.get("pdf_base64")
                if pdf_b64:
                    try:
                        pdf_bytes = base64.b64decode(pdf_b64)
                        nombre_archivo = _nombre_archivo_acta(r, al)
                        st.download_button(
                            f"📄 Descargar PDF — Acta #{act['id']}",
                            pdf_bytes,
                            file_name=nombre_archivo,
                            mime="application/pdf",
                            key=f"pdf_det_{act['id']}")
                    except Exception:
                        st.warning("PDF no disponible.")
                else:
                    st.warning("PDF no disponible para esta acta.")
                st.markdown("---")
        st.subheader("Firmar nueva acta (alumno y apoderado)")
        st.caption("El acta se genera en PDF con las observaciones como contenido.")
        nombre_al_default = nombre
        nombre_alumno = st.text_input("Nombre del alumno firmante",
                                      value=nombre_al_default,
                                      key="det_nom_al")
        st.caption("Firma del alumno")
        firma_alumno = firma_widget(key=f"firma_det_al_{inc_id}")
        st.markdown("---")
        nombre_apoderado = st.text_input(
            "Nombre del apoderado firmante",
            value=al.get("nombre_apoderado") or "",
            key="det_nom_apo")
        st.caption("Firma del apoderado")
        firma_apoderado = firma_widget(key=f"firma_det_apo_{inc_id}")
        st.markdown("---")
        obs = st.text_area("Observaciones / Acuerdos", key="det_obs")
        if st.button("Guardar acta y generar PDF", type="primary",
                     key="det_guardar_acta"):
            firma_al_b64 = None
            if firma_alumno is not None and getattr(firma_alumno, "firma_data", None):
                firma_al_b64 = firma_alumno.firma_data
            else:
                firma_al_b64 = firma_guardada(f"firma_det_al_{inc_id}")
            firma_apo_b64 = None
            if firma_apoderado is not None and getattr(firma_apoderado, "firma_data", None):
                firma_apo_b64 = firma_apoderado.firma_data
            else:
                firma_apo_b64 = firma_guardada(f"firma_det_apo_{inc_id}")
            if not nombre_alumno.strip() or not nombre_apoderado.strip():
                st.error("Nombres de alumno y apoderado obligatorios.")
            elif not firma_al_b64 or not firma_apo_b64:
                st.error("Faltan firmas.")
            else:
                ok, msg = crear_acta_doble(
                    inc_id, f"{nombre_alumno} / {nombre_apoderado}",
                    firma_al_b64, firma_apo_b64, obs,
                    nombre_alumno.strip(), nombre_apoderado.strip(),
                    st.session_state["user"])
                if ok:
                    limpiar_firma(f"firma_det_al_{inc_id}")
                    limpiar_firma(f"firma_det_apo_{inc_id}")
                    guardar_toast(msg)
                    st.rerun()
                else:
                    st.error(msg)

# BUSCAR ALUMNO WIDGET 
def buscar_alumno_widget(clave):
    st.write("**Buscar alumno**")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        texto = st.text_input("Nombre", key=clave + "_buscar")
    with c2:
        dni = st.text_input("DNI", key=clave + "_dni")
    with c3:
        grados = obtener_grados()
        grado = st.selectbox("Grado", grados, key=clave + "_grado")
    with c4:
        secciones = obtener_secciones(grado)
        seccion = st.selectbox("Sección", secciones, key=clave + "_sec")
    df = buscar_alumnos(texto, grado, seccion, dni, limite=50)
    if df.empty:
        st.warning("Sin coincidencias."); return None
    ops = {}
    for _, r in df.iterrows():
        nombre = (r['apellido_paterno'] + " " + (r['apellido_materno'] or "") +
                  ", " + r['nombres'])
        et = f"{nombre} - {r['grado'] or ''} {r['seccion'] or ''} - DNI {mask_dni(r['dni'])}"
        ops[et] = r["id"]
    sel = st.selectbox("Alumno", list(ops.keys()), key=clave + "_sel")
    idal = ops[sel]
    return _obtener_alumno(idal)

# VISTA DECOMISOS
def vista_decomisos():
    mostrar_toast_pendiente()
    st.title("Decomisos")

    hoy = hoy_str()
    if st.session_state.get("_venc_actualizado") != hoy:
        actualizar_vencidos()
        st.session_state["_venc_actualizado"] = hoy

    usuario = st.session_state["user"]

    if "dec_vista_radio" not in st.session_state:
        st.session_state["dec_vista_radio"] = "Activos"

    opciones = ["Activos", "Todos", "Registrar nuevo"]
    vista_sel = st.radio(
        "Vista",
        opciones,
        horizontal=True,
        key="dec_vista_radio",
        label_visibility="collapsed"
    )

    if vista_sel == "Activos":
        _dec_activos(usuario)
    elif vista_sel == "Todos":
        _dec_todos()
    else:
        _dec_registrar(usuario)

def _dec_activos(usuario):
    st.subheader("Decomisos activos")
    df = listar_decomisos_activos()
    if df.empty:
        st.success("No hay decomisos activos.")
    else:
        st.write(f"**{len(df)} decomiso(s) activo(s).**")
        for _, d in df.iterrows():
            dias_ret = dias_desde(d["fecha_decomiso"])
            if d["fecha_limite"]:
                dias_lim = dias_hasta(d["fecha_limite"])
                if dias_lim < 0:
                    cont_txt = f"🔴 PLAZO VENCIDO hace {abs(dias_lim)} día(s) — DEVOLVER OBJETO"
                elif dias_lim == 0:
                    cont_txt = "🟠 Vence HOY — DEVOLVER OBJETO"
                elif dias_lim <= 2:
                    cont_txt = f"🟡 Vence en {dias_lim} día(s) — preparar devolución"
                else:
                    cont_txt = f"🟢 Fecha de devolución en {dias_lim} día(s)"
            else:
                cont_txt = "⚪ Sin fecha límite"
            cls = "vencido" if d["estado"] == "Vencido" else ""
            st.markdown(f"""
            <div class="decomiso-card {cls}">
                <div class="dec-obj">{d['objeto']}</div>
                <div class="dec-meta">{d['alumno']} — {d['grado'] or ''} {d['seccion'] or ''}</div>
                <div class="dec-meta">Retenido el {d['fecha_decomiso']} — {dias_ret} día(s) — Estado: <b>{d['estado']}</b></div>
                <div class="dec-contador">{cont_txt}</div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"Acciones decomiso #{d['id']}"):
                c1, c2 = st.columns(2)
                with c1:
                    nuevo_estado = st.selectbox(
                        "Cambiar estado",
                        [e for e in ESTADOS_DECOMISO if e != "Devuelto"],
                        index=0, key=f"dec_est_g_{d['id']}")
                    if st.button("Guardar estado", key=f"dec_est_g_btn_{d['id']}"):
                        cambiar_estado_decomiso(d["id"], nuevo_estado, usuario)
                        guardar_toast("Estado actualizado.")
                        st.rerun()
                with c2:
                    devuelto_a = st.text_input("Devuelto a",
                                               key=f"dec_da_g_{d['id']}")
                    obs_dev = st.text_input("Observaciones",
                                            key=f"dec_obs_g_{d['id']}")
                    if st.button("Marcar DEVUELTO", type="primary",
                                 key=f"dec_dev_g_{d['id']}"):
                        ok, msg = devolver_decomiso(d["id"], devuelto_a,
                                                    obs_dev, usuario)
                        if ok:
                            guardar_toast(msg)
                            st.rerun()
                        else:
                            st.error(msg)

def _dec_todos():
    st.subheader("Todos los decomisos")
    df = listar_decomisos_todos()
    if df.empty:
        st.info("Sin decomisos registrados.")
    else:
        df_show = df.copy()
        st.write(f"**{len(df)} decomiso(s).**")
        st.dataframe(df_show, use_container_width=True, hide_index=True)

def _dec_registrar(usuario):
    st.subheader("Registrar decomiso manualmente")
    st.caption("Selecciona un alumno y agrega uno o varios objetos.")
    al = buscar_alumno_widget("dec_nuevo")
    if not al:
        return
    st.markdown("---")
    st.markdown(f"**{al['nombres']} {al['apellido_paterno']}** — "
                f"{al['grado'] or ''} {al['seccion'] or ''} — "
                f"DNI {mask_dni(al['dni'])}")

    with st.form("form_decomiso"):
        st.markdown("**Objetos a decomisar**")
        st.caption("Agrega hasta 5 objetos por registro.")
        objetos = []
        for i in range(5):
            c1, c2, c3 = st.columns([3, 2, 4])
            with c1:
                obj = st.text_input(f"Objeto {i+1}",
                                    key=f"dec_obj_{i}",
                                    placeholder="Celular, cartera...")
            with c2:
                f_lim = st.date_input(f"Fecha de devolución {i+1}",
                                      value=ahora().date() + timedelta(days=3),
                                      key=f"dec_fl_{i}")
            with c3:
                desc = st.text_input(f"Descripción {i+1}",
                                     key=f"dec_desc_{i}",
                                     placeholder="Marca, color, etc.")
            if obj.strip():
                objetos.append({
                    "objeto": obj.strip(),
                    "fecha_limite": f_lim.strftime("%Y-%m-%d"),
                    "descripcion": desc.strip(),
                })
        sub = st.form_submit_button("Registrar decomisos", type="primary")

    if sub:
        if not objetos:
            st.error("Agrega al menos un objeto.")
        else:
            n, errs_batch = crear_decomisos_batch(al["id"], None, objetos,
                                                  usuario)
            if n:
                st.session_state["dec_vista_radio"] = "Registrar nuevo"
                guardar_toast(f"{n} decomiso(s) registrado(s).")
                st.rerun()
            for e in errs_batch:
                st.warning(e)
#  ACTAS 
def vista_actas():
    mostrar_toast_pendiente()
    st.title("Actas firmadas")
    df = leer_df("""
        SELECT a.id AS incidencia_id, a.fecha, a.tipo, a.categoria,
        al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS alumno,
        al.grado, al.seccion,
        (SELECT COUNT(*) FROM actas WHERE incidencia_id=a.id) AS n_actas
        FROM incidencias a JOIN alumnos al ON a.alumno_id=al.id
        WHERE a.requiere_acta=1
        ORDER BY a.fecha DESC LIMIT 200
    """)
    if df.empty:
        st.info("No hay incidencias con acta requerida.")
        return
    st.write(f"**{len(df)} incidencias con acta.**")
    for _, r in df.iterrows():
        with st.expander(f"{r['fecha']} - {r['alumno']} - "
                         f"{r['tipo']} ({r['n_actas']} acta(s))"):
            actas = actas_de_incidencia(r["incidencia_id"])
            inc_full = _obtener_incidencia(r["incidencia_id"])
            al_full = _obtener_alumno(inc_full["alumno_id"]) if inc_full else {}
            if actas.empty:
                st.warning("Esta incidencia requiere acta pero aún no está firmada.")
                nombre_al_default = (f"{al_full['apellido_paterno']} "
                                     f"{al_full['apellido_materno'] or ''}, "
                                     f"{al_full['nombres']}")
                st.write(f"**Alumno:** {nombre_al_default}")
                st.write(f"**Apoderado:** {al_full.get('nombre_apoderado') or '-'}")
                st.markdown("---")

                nombre_alumno = st.text_input(
                    "Nombre del alumno firmante",
                    value=nombre_al_default,
                    key=f"nom_al_{r['incidencia_id']}")
                st.caption("Firma del alumno")
                firma_alumno = firma_widget(key=f"firma_al_{r['incidencia_id']}")
                st.markdown("---")

                nombre_apoderado = st.text_input(
                    "Nombre del apoderado firmante",
                    value=al_full.get("nombre_apoderado") or "",
                    key=f"nom_apo_{r['incidencia_id']}")
                st.caption("Firma del apoderado")
                firma_apoderado = firma_widget(key=f"firma_apo_{r['incidencia_id']}")
                st.markdown("---")

                obs = st.text_area(
                    "Observaciones / Acuerdos (esto va dentro del PDF)",
                    key=f"obs_{r['incidencia_id']}")

                if st.button("Guardar acta y generar PDF", type="primary",
                             key=f"guardar_acta_{r['incidencia_id']}"):
                    firma_al_b64 = None
                    if firma_alumno is not None and getattr(firma_alumno, "firma_data", None):
                        firma_al_b64 = firma_alumno.firma_data
                    else:
                        firma_al_b64 = firma_guardada(f"firma_al_{r['incidencia_id']}")
                    firma_apo_b64 = None
                    if firma_apoderado is not None and getattr(firma_apoderado, "firma_data", None):
                        firma_apo_b64 = firma_apoderado.firma_data
                    else:
                        firma_apo_b64 = firma_guardada(f"firma_apo_{r['incidencia_id']}")
                    if not nombre_alumno.strip() or not nombre_apoderado.strip():
                        st.error("Nombres de alumno y apoderado obligatorios.")
                    elif not firma_al_b64 or not firma_apo_b64:
                        st.error("Faltan firmas. Firma ambos recuadros.")
                    else:
                        ok, msg = crear_acta_doble(
                            r["incidencia_id"], f"{nombre_alumno} / {nombre_apoderado}",
                            firma_al_b64, firma_apo_b64, obs,
                            nombre_alumno.strip(), nombre_apoderado.strip(),
                            st.session_state["user"])
                        if ok:
                            limpiar_firma(f"firma_al_{r['incidencia_id']}")
                            limpiar_firma(f"firma_apo_{r['incidencia_id']}")
                            guardar_toast(msg)
                            st.rerun()
                        else:
                            st.error(msg)
            else:
                for _, act in actas.iterrows():
                    st.markdown(f"**Acta #{act['id']}** — "
                                f"Firmante: {act['firmante_nombre']} — "
                                f"Fecha: {act['firmado_en']}")
                    if act['observaciones']:
                        st.caption(f"Obs: {act['observaciones']}")
                    if act.get("nombre_alumno"):
                        st.caption(f"Alumno: {act['nombre_alumno']}")
                    if act.get("nombre_apoderado"):
                        st.caption(f"Apoderado: {act['nombre_apoderado']}")
                    pdf_b64 = act.get("pdf_base64")
                    if pdf_b64:
                        try:
                            pdf_bytes = base64.b64decode(pdf_b64)
                            nombre_archivo = _nombre_archivo_acta(inc_full, al_full)
                            st.download_button(
                                f"📄 Descargar PDF — Acta #{act['id']}",
                                pdf_bytes,
                                file_name=nombre_archivo,
                                mime="application/pdf",
                                key=f"pdf_acta_{act['id']}")
                        except Exception as e:
                            st.warning(f"No se pudo cargar el PDF: {e}")
                    else:
                        st.warning("PDF no disponible para esta acta.")
                    st.markdown("---")
# REPORTES 
def reporte_diario_incidencias(fecha):
    return leer_df("""
        SELECT i.id, i.fecha, i.hora, i.tipo, i.categoria, i.estado,
        al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS Alumno,
        al.grado AS Grado, al.seccion AS Seccion,
        al.dni AS DNI, i.descripcion AS Descripcion,
        i.reportado_por AS "Reportado por",
        CASE WHEN i.requiere_acta=1 THEN 'Si ('||COALESCE(i.tipo_acta,'')||')' ELSE 'No' END AS "Requiere acta"
        FROM incidencias i JOIN alumnos al ON i.alumno_id=al.id
        WHERE i.fecha=?
        ORDER BY i.hora DESC
    """, (fecha,))

def reporte_mensual_incidencias(anio, mes):
    ini = f"{anio:04d}-{mes:02d}-01"
    if mes == 12:
        fin = f"{anio+1:04d}-01-01"
    else:
        fin = f"{anio:04d}-{mes+1:02d}-01"
    return leer_df("""
        SELECT i.id, i.fecha, i.hora, i.tipo, i.categoria, i.estado,
        al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS Alumno,
        al.grado AS Grado, al.seccion AS Seccion,
        al.dni AS DNI, i.descripcion AS Descripcion,
        i.reportado_por AS "Reportado por",
        CASE WHEN i.requiere_acta=1 THEN 'Si ('||COALESCE(i.tipo_acta,'')||')' ELSE 'No' END AS "Requiere acta"
        FROM incidencias i JOIN alumnos al ON i.alumno_id=al.id
        WHERE i.fecha >= ? AND i.fecha < ?
        ORDER BY i.fecha DESC, i.hora DESC
    """, (ini, fin))

def vista_reportes():
    mostrar_toast_pendiente()
    st.title("Reportes")
    tabs = st.tabs(["Diario", "Mensual", "Por alumno", "Por tipo", "Decomisos"])

    with tabs[0]:
        st.subheader("Reporte diario de incidencias")
        fecha = st.date_input("Fecha", value=ahora().date(), key="rep_fecha")
        df = reporte_diario_incidencias(fecha.strftime("%Y-%m-%d"))
        if df.empty:
            st.info("Sin incidencias ese día.")
        else:
            df_show = df.copy()
            if "DNI" in df_show.columns:
                df_show["DNI"] = df_show["DNI"].apply(mask_dni)
            st.write(f"**{len(df)} incidencias**")
            st.dataframe(df_show, use_container_width=True, hide_index=True)
            c1, c2 = st.columns(2)
            with c1:
                buf = BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as w:
                    df.to_excel(w, index=False, sheet_name="Incidencias")
                buf.seek(0)
                st.download_button("Descargar Excel", buf.getvalue(),
                                   f"incidencias_{fecha}.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True)
            with c2:
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button("Descargar CSV", csv,
                                   f"incidencias_{fecha}.csv", "text/csv",
                                   use_container_width=True)

    with tabs[1]:
        st.subheader("Reporte mensual de incidencias")
        c1, c2 = st.columns(2)
        with c1:
            anio = st.number_input("Año", min_value=2020, max_value=2100,
                                   value=ahora().year, step=1, key="rep_anio")
        with c2:
            mes = st.selectbox("Mes", list(range(1, 13)),
                               index=ahora().month - 1, key="rep_mes")
        df = reporte_mensual_incidencias(int(anio), int(mes))
        if df.empty:
            st.info("Sin incidencias ese mes.")
        else:
            df_show = df.copy()
            if "DNI" in df_show.columns:
                df_show["DNI"] = df_show["DNI"].apply(mask_dni)
            st.write(f"**{len(df)} incidencias en el mes**")
            st.markdown("**Resumen por tipo**")
            resumen = df.groupby("tipo").size().reset_index(name="Total")
            st.dataframe(resumen, use_container_width=True, hide_index=True)
            st.markdown("**Resumen por estado**")
            resumen_e = df.groupby("estado").size().reset_index(name="Total")
            st.dataframe(resumen_e, use_container_width=True, hide_index=True)
            st.dataframe(df_show, use_container_width=True, hide_index=True)
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Mensual")
                resumen.to_excel(w, index=False, sheet_name="Por tipo")
                resumen_e.to_excel(w, index=False, sheet_name="Por estado")
            buf.seek(0)
            st.download_button("Descargar Excel",
                               buf.getvalue(),
                               f"incidencias_{anio}_{mes:02d}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tabs[2]:
        st.subheader("Incidencias por alumno")
        df = leer_df("""
            SELECT al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS Alumno,
            al.grado AS Grado, al.seccion AS Seccion,
            COUNT(*) AS Total,
            SUM(CASE WHEN i.tipo='Leve' THEN 1 ELSE 0 END) AS Leves,
            SUM(CASE WHEN i.tipo='Grave' THEN 1 ELSE 0 END) AS Graves,
            SUM(CASE WHEN i.tipo='Muy grave' THEN 1 ELSE 0 END) AS "Muy graves"
            FROM incidencias i JOIN alumnos al ON i.alumno_id=al.id
            GROUP BY al.id ORDER BY Total DESC
        """)
        if df.empty:
            st.info("Sin datos.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Por alumno")
            buf.seek(0)
            st.download_button("Descargar Excel", buf.getvalue(),
                               "incidencias_por_alumno.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tabs[3]:
        st.subheader("Incidencias por tipo")
        df = leer_df("""
            SELECT tipo AS Tipo, categoria AS Categoria, COUNT(*) AS Total
            FROM incidencias GROUP BY tipo, categoria ORDER BY tipo, Total DESC
        """)
        if df.empty:
            st.info("Sin datos.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Por tipo")
            buf.seek(0)
            st.download_button("Descargar Excel", buf.getvalue(),
                               "incidencias_por_tipo.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tabs[4]:
        st.subheader("Reporte de decomisos")
        c1, c2 = st.columns(2)
        with c1:
            filtro = st.selectbox("Filtro",
                                  ["Todos", "Activos", "Devueltos", "Vencidos"],
                                  key="rep_dec_fil")
        with c2:
            anio_d = st.number_input("Año", min_value=2020, max_value=2100,
                                     value=ahora().year, step=1, key="rep_dec_anio")
        q = """SELECT d.id, d.fecha_decomiso, d.hora_decomiso, d.objeto,
               d.descripcion, d.fecha_limite, d.estado, d.fecha_devolucion,
               d.devuelto_a, d.retenido_por,
               al.apellido_paterno||' '||COALESCE(al.apellido_materno,'')||', '||al.nombres AS Alumno,
               al.grado AS Grado, al.seccion AS Seccion
               FROM decomisos d JOIN alumnos al ON d.alumno_id=al.id
               WHERE strftime('%Y', d.fecha_decomiso)=?"""
        p = [str(int(anio_d))]
        if filtro == "Activos":
            q += " AND d.estado != 'Devuelto'"
        elif filtro == "Devueltos":
            q += " AND d.estado = 'Devuelto'"
        elif filtro == "Vencidos":
            q += " AND d.estado = 'Vencido'"
        q += " ORDER BY d.fecha_decomiso DESC"
        df = leer_df(q, p)
        if df.empty:
            st.info("Sin decomisos con esos filtros.")
        else:
            st.write(f"**{len(df)} decomisos**")
            st.dataframe(df, use_container_width=True, hide_index=True)
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="Decomisos")
            buf.seek(0)
            st.download_button("Descargar Excel", buf.getvalue(),
                               f"decomisos_{anio_d}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
#  USUARIOS 
def _obtener_usuario(idu):
    con = obtener_conexion()
    cur = con.execute("SELECT * FROM usuarios WHERE id=?", (idu,))
    f = cur.fetchone()
    return dict(f) if f else None

def vista_usuarios():
    mostrar_toast_pendiente()
    st.title("Usuarios")
    u = st.session_state["user"]
    soy_principal = (u["usuario"] == "admin")
    tabs = st.tabs(["Listar", "Crear", "Editar"])

    with tabs[0]:
        df = leer_df("SELECT id,usuario,rol,nombres,activo,ultimo_login "
                     "FROM usuarios ORDER BY usuario")
        if df.empty:
            st.info("Sin usuarios.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("Crear usuario")
        c1, c2 = st.columns(2)
        with c1:
            nu = st.text_input("Usuario", key="cr_u")
            np = st.text_input("Contraseña", type="password", key="cr_p")
        with c2:
            nn = st.text_input("Nombres", key="cr_n")
            roles = (["Admin", "Direccion", "Auxiliar"]
                     if soy_principal else ["Direccion", "Auxiliar"])
            nr = st.selectbox("Rol", roles, key="cr_r")

        if st.button("Crear", type="primary", key="crear_u_btn"):
            nu_norm = (nu or "").strip().lower()
            if not nu_norm or not np or not nn.strip():
                st.error("Completa usuario, contraseña y nombres.")
            elif len(np) < 6:
                st.error("La contraseña debe tener mínimo 6 caracteres.")
            elif not re.fullmatch(r"[a-z0-9_.]+", nu_norm):
                st.error("El usuario solo puede tener letras minúsculas, "
                         "números, punto y guion bajo.")
            else:
                con = obtener_conexion()
                cur = con.execute(
                    "SELECT id FROM usuarios WHERE LOWER(usuario)=?",
                    (nu_norm,))
                if cur.fetchone():
                    st.error(f"El usuario **{nu_norm}** ya existe. Elige otro.")
                else:
                    try:
                        escribir(
                            "INSERT INTO usuarios(usuario,password,rol,nombres) "
                            "VALUES(?,?,?,?)",
                            (nu_norm, hashear_password(np), nr, nn.strip()))
                        auditar(u["usuario"], f"Creo usuario {nu_norm}")
                        for k in ["cr_u", "cr_p", "cr_n"]:
                            st.session_state.pop(k, None)
                        guardar_toast(f"Usuario '{nu_norm}' creado correctamente.")
                        st.rerun()
                    except Exception as e:
                        if "unique" in str(e).lower():
                            st.error(f"El usuario **{nu_norm}** ya existe.")
                        else:
                            log.error("crear_usuario: %s", e)
                            st.error("No se pudo crear el usuario.")

    with tabs[2]:
        df = leer_df("SELECT id,usuario,rol,nombres,activo FROM usuarios "
                     "WHERE usuario!='admin'")
        if df.empty:
            st.info("Sin usuarios editables.")
        else:
            ops = {f"{r['usuario']} ({r['rol']})": r["id"]
                   for _, r in df.iterrows()}
            sel = st.selectbox("Usuario", list(ops.keys()), key="ed_u_sel")
            idu = ops[sel]
            d = _obtener_usuario(idu)
            with st.form("ed_u"):
                nusu = st.text_input("Usuario", value=d["usuario"])
                nnom = st.text_input("Nombres", value=d["nombres"])
                npass = st.text_input("Nueva contraseña (opcional)",
                                      type="password")
                roles = (["Admin", "Direccion", "Auxiliar"]
                         if soy_principal else ["Direccion", "Auxiliar"])
                idx_rol = roles.index(d["rol"]) if d["rol"] in roles else 0
                nrol = st.selectbox("Rol", roles, index=idx_rol)
                act = st.checkbox("Activo", value=bool(d["activo"]))
                if st.form_submit_button("Guardar", type="primary"):
                    nusu_norm = nusu.strip().lower()
                    con = obtener_conexion()
                    cur = con.execute(
                        "SELECT id FROM usuarios "
                        "WHERE LOWER(usuario)=? AND id!=?",
                        (nusu_norm, idu))
                    if cur.fetchone():
                        st.error(f"El usuario **{nusu_norm}** ya existe.")
                    else:
                        if npass:
                            escribir("""UPDATE usuarios SET usuario=?,nombres=?,
                                        rol=?,password=?,activo=? WHERE id=?""",
                                     (nusu_norm, nnom, nrol,
                                      hashear_password(npass),
                                      1 if act else 0, idu))
                        else:
                            escribir("""UPDATE usuarios SET usuario=?,nombres=?,
                                        rol=?,activo=? WHERE id=?""",
                                     (nusu_norm, nnom, nrol,
                                      1 if act else 0, idu))
                        auditar(u["usuario"], f"Edito usuario {nusu_norm}")
                        guardar_toast("Usuario editado correctamente.")
                        st.rerun()

#auditoria
def vista_auditoria():
    mostrar_toast_pendiente()
    st.title("Auditoría")
    df = leer_df("SELECT id,usuario,accion,fecha,tabla_afectada,registro_id "
                 "FROM auditoria ORDER BY id DESC LIMIT 500")
    st.write(f"**{len(df)} registros**")
    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════
# ENRUTADOR PARA INCIDENCIAS
# ═══════════════════════════════════════════════════════════════════
def enrutar(opcion):
    from asistencia import aplicar_estilos
    aplicar_estilos()
    if opcion == "Escaner QR":
        vista_escaner()
    elif opcion == "Incidencias":
        vista_incidencias()
    elif opcion == "Decomisos":
        vista_decomisos()
    elif opcion == "Actas":
        vista_actas()
    elif opcion == "Reportes":
        vista_reportes()
    elif opcion == "Alumnos":
        vista_alumnos()
    elif opcion == "Usuarios":
        vista_usuarios()
    elif opcion == "Auditoria":
        vista_auditoria()