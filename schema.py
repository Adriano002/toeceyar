# schema.py
import logging

log = logging.getLogger("schema")

TABLAS = [
    """CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE NOT NULL, password TEXT NOT NULL, rol TEXT NOT NULL CHECK(rol IN ('Admin','Direccion','Coordinador','Auxiliar','Docente')), nombres TEXT NOT NULL, turno_asignado INTEGER, activo INTEGER DEFAULT 1, intentos_fallidos INTEGER DEFAULT 0, bloqueado_hasta TEXT, debe_cambiar_password INTEGER DEFAULT 0, ultimo_login TEXT, ultimo_ip TEXT, es_principal INTEGER DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS auditoria (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, fecha TEXT, valor_anterior TEXT, valor_nuevo TEXT, tabla_afectada TEXT, registro_id INTEGER, ip TEXT)""",
    """CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY AUTOINCREMENT, clave TEXT UNIQUE NOT NULL, valor TEXT)""",
    """CREATE TABLE IF NOT EXISTS periodos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, fecha_inicio TEXT, fecha_fin TEXT, activo INTEGER DEFAULT 0, fecha_cierre TEXT, cerrado INTEGER DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS turnos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, hora_entrada TEXT, hora_salida TEXT, tolerancia_min INTEGER DEFAULT 10)""",
    """CREATE TABLE IF NOT EXISTS grados (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE)""",
    """CREATE TABLE IF NOT EXISTS secciones (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, grado_id INTEGER REFERENCES grados(id), turno_id INTEGER REFERENCES turnos(id), UNIQUE(nombre, grado_id, turno_id))""",
    """CREATE TABLE IF NOT EXISTS apoderados (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, telefono TEXT)""",
    """CREATE TABLE IF NOT EXISTS alumnos (id INTEGER PRIMARY KEY AUTOINCREMENT, dni TEXT UNIQUE NOT NULL, nombres TEXT NOT NULL, apellido_paterno TEXT NOT NULL, apellido_materno TEXT, seccion_id INTEGER REFERENCES secciones(id), apoderado_id INTEGER REFERENCES apoderados(id), nombre_apoderado TEXT, telefono_apoderado TEXT, periodo_id INTEGER, activo INTEGER DEFAULT 1, retirado_en TEXT)""",
    """CREATE TABLE IF NOT EXISTS ventanas (id INTEGER PRIMARY KEY AUTOINCREMENT, turno_id INTEGER NOT NULL REFERENCES turnos(id), tipo TEXT NOT NULL CHECK(tipo IN ('clases','reforzamiento')), nombre TEXT NOT NULL, hora_apertura TEXT NOT NULL, hora_limite_puntual TEXT, hora_cierre TEXT NOT NULL, tolerancia_min INTEGER DEFAULT 0, orden INTEGER DEFAULT 0, activo INTEGER DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS asistencias (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha TEXT NOT NULL, ventana_id INTEGER REFERENCES ventanas(id), tipo TEXT NOT NULL DEFAULT 'clases', hora TEXT, estado TEXT NOT NULL, justificada INTEGER DEFAULT 0, observacion TEXT, origen TEXT DEFAULT 'qr', justificado_por TEXT, justificado_en TEXT, periodo_id INTEGER, dia_especial_id INTEGER, UNIQUE(alumno_id, fecha, tipo))""",
    """CREATE TABLE IF NOT EXISTS tardanzas (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha TEXT NOT NULL, hora TEXT NOT NULL, numero INTEGER NOT NULL, accion TEXT NOT NULL, observacion TEXT, justificada INTEGER DEFAULT 0, origen TEXT DEFAULT 'qr', registrado_por TEXT, timestamp TEXT NOT NULL, periodo_id INTEGER, UNIQUE(alumno_id, fecha))""",
    """CREATE TABLE IF NOT EXISTS bloqueos (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), motivo TEXT, activo INTEGER DEFAULT 1, fecha_inicio TEXT NOT NULL, fecha_fin TEXT, liberado_por TEXT, creado_por TEXT, origen TEXT DEFAULT 'automatico')""",
    """CREATE TABLE IF NOT EXISTS permisos (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha_inicio TEXT NOT NULL, fecha_fin TEXT NOT NULL, motivo TEXT, tipo TEXT NOT NULL DEFAULT 'permiso', creado_por TEXT, timestamp TEXT NOT NULL, activo INTEGER DEFAULT 1, periodo_id INTEGER)""",
    """CREATE TABLE IF NOT EXISTS dias_especiales (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, descripcion TEXT, turno_id INTEGER, hora_entrada TEXT, activo INTEGER DEFAULT 1, tipo TEXT DEFAULT 'evento' CHECK(tipo IN ('evento','feriado')), periodo_id INTEGER, contar_como_clases INTEGER DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS dias_especiales_secciones (id INTEGER PRIMARY KEY AUTOINCREMENT, dia_especial_id INTEGER NOT NULL REFERENCES dias_especiales(id) ON DELETE CASCADE, seccion_id INTEGER NOT NULL REFERENCES secciones(id), UNIQUE(dia_especial_id, seccion_id))""",
    """CREATE TABLE IF NOT EXISTS auxiliar_secciones (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE, seccion_id INTEGER NOT NULL REFERENCES secciones(id) ON DELETE CASCADE, UNIQUE(seccion_id))""",
    """CREATE TABLE IF NOT EXISTS cierres_anuales (id INTEGER PRIMARY KEY AUTOINCREMENT, periodo_id INTEGER NOT NULL REFERENCES periodos(id), fecha_cierre TEXT NOT NULL, generado_por TEXT, reporte_json TEXT)""",
    """CREATE TABLE IF NOT EXISTS incidencias (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha TEXT NOT NULL, hora TEXT NOT NULL, tipo TEXT NOT NULL, categoria TEXT, descripcion TEXT NOT NULL, reportado_por TEXT NOT NULL, estado TEXT DEFAULT 'Abierta', requiere_acta INTEGER DEFAULT 0, tipo_acta TEXT, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS actas (id INTEGER PRIMARY KEY AUTOINCREMENT, incidencia_id INTEGER NOT NULL REFERENCES incidencias(id), tipo TEXT NOT NULL, firmante_nombre TEXT, firma_base64 TEXT, firmado_en TEXT NOT NULL, observaciones TEXT, firma_alumno_base64 TEXT, firma_apoderado_base64 TEXT, nombre_alumno TEXT, nombre_apoderado TEXT, pdf_base64 TEXT)""",
    """CREATE TABLE IF NOT EXISTS decomisos (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), incidencia_id INTEGER, fecha_decomiso TEXT NOT NULL, hora_decomiso TEXT NOT NULL, objeto TEXT NOT NULL, descripcion TEXT, retenido_por TEXT NOT NULL, fecha_limite TEXT, estado TEXT DEFAULT 'Retenido', fecha_devolucion TEXT, devuelto_a TEXT, observaciones TEXT, created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS observados (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha_ingreso TEXT NOT NULL, motivo TEXT, activo INTEGER DEFAULT 1, fecha_salida TEXT, observacion_cierre TEXT, periodo_id INTEGER)""",
    """CREATE TABLE IF NOT EXISTS justificaciones_previas (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha_objetivo TEXT NOT NULL, tipo TEXT NOT NULL CHECK(tipo IN ('Falta','Tardanza')), motivo TEXT, creado_por TEXT, timestamp TEXT NOT NULL, aplicada INTEGER DEFAULT 0, UNIQUE(alumno_id, fecha_objetivo, tipo))""",
    """CREATE TABLE IF NOT EXISTS actas_compromiso (id INTEGER PRIMARY KEY AUTOINCREMENT, alumno_id INTEGER NOT NULL REFERENCES alumnos(id), fecha TEXT NOT NULL, motivo TEXT, observacion TEXT, registrado_por TEXT, timestamp TEXT NOT NULL, periodo_id INTEGER)"""
]

INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_ast_f ON asistencias(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_ast_a ON asistencias(alumno_id)",
    "CREATE INDEX IF NOT EXISTS idx_tard_a ON tardanzas(alumno_id)",
    "CREATE INDEX IF NOT EXISTS idx_al_dni ON alumnos(dni)",
    "CREATE INDEX IF NOT EXISTS idx_bloq_a ON bloqueos(alumno_id, activo)",
    "CREATE INDEX IF NOT EXISTS idx_aud_f ON auditoria(fecha)",
    "CREATE INDEX IF NOT EXISTS idx_inc_alumno ON incidencias(alumno_id)",
    "CREATE INDEX IF NOT EXISTS idx_dec_alumno ON decomisos(alumno_id)"
]


def aplicar_schema(cur):
    for sql in TABLAS:
        cur.execute(sql)
    for sql in INDICES:
        cur.execute(sql)
    log.info("Schema aplicado.")
