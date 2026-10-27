# app.py
import streamlit as st
from db import leer_df, obtener_conexion
from utils import verificar_password
from modulos import asistencia, incidencias

# ═══════════════════════════════════════════════════════════════════
# LOGIN
# ═══════════════════════════════════════════════════════════════════
def vista_login():
    st.title("Iniciar Sesión")
    with st.form("login"):
        u = st.text_input("Usuario").strip().lower()
        p = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            user = leer_df("SELECT * FROM usuarios WHERE usuario=? AND activo=1", (u,))
            if not user.empty and verificar_password(p, user.iloc[0]["password"]):
                st.session_state["user"] = user.iloc[0].to_dict()
                st.rerun()
            else:
                st.error("Credenciales incorrectas")

# ═══════════════════════════════════════════════════════════════════
# MENÚ POR ROL
# ═══════════════════════════════════════════════════════════════════
def menu_por_rol(rol):
    if rol == "Admin":
        return ["Puerta", "Panel Direccion", "Alumnos", "Carnets",
                "Escaner QR", "Incidencias", "Decomisos", "Actas",
                "Reportes", "Bloqueados", "Dias especiales", "Ventanas",
                "Usuarios", "Auditoria", "Periodos", "Mantenimiento", "Mi cuenta"]
    elif rol == "Direccion":
        return ["Panel Direccion", "Escaner QR", "Incidencias",
                "Decomisos", "Reportes", "Bloqueados", "Dias especiales",
                "Mantenimiento", "Mi cuenta"]
    elif rol == "Coordinador":
        return ["Reportes", "Alumnos", "Incidencias", "Mi cuenta"]
    elif rol == "Auxiliar":
        return ["Puerta", "Escaner QR", "Reportes", "Bloqueados", "Mi cuenta"]
    elif rol == "Docente":
        return ["Escaner QR", "Incidencias", "Mi cuenta"]
    return []

# ═══════════════════════════════════════════════════════════════════
# CARGAR MÓDULO
# ═══════════════════════════════════════════════════════════════════
def cargar_modulo(opcion):
    # Opciones de Asistencia
    if opcion in ["Puerta", "Alumnos", "Panel Direccion", "Carnets",
                  "Justificaciones", "Bloqueados", "Dias especiales",
                  "Ventanas", "Periodos", "Mantenimiento"]:
        asistencia.enrutar(opcion)
    
    # Opciones de Incidencias
    elif opcion in ["Escaner QR", "Incidencias", "Decomisos", "Actas"]:
        incidencias.enrutar(opcion)
    
    # Opciones compartidas
    elif opcion == "Reportes":
        st.title("Reportes")
        tabs = st.tabs(["Asistencia", "Incidencias"])
        with tabs[0]:
            asistencia.enrutar("Reportes")
        with tabs[1]:
            incidencias.enrutar("Reportes")
            
    elif opcion == "Usuarios":
        asistencia.enrutar("Usuarios")
    elif opcion == "Auditoria":
        asistencia.enrutar("Auditoria")
    elif opcion == "Mi cuenta":
        asistencia.enrutar("Mi cuenta")

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════
def main():
    st.set_page_config(page_title="I.E. Yarinacocha", page_icon="🏫", layout="wide")

    if "user" not in st.session_state:
        vista_login()
        return

    usuario = st.session_state["user"]
    opciones = menu_por_rol(usuario["rol"])

    with st.sidebar:
        st.markdown(f"### 👤 {usuario['nombres']}")
        st.caption(f"Rol: {usuario['rol']}")
        opcion = st.radio("Menú", opciones)
        if st.button("Cerrar Sesión"):
            del st.session_state["user"]
            st.rerun()

    cargar_modulo(opcion)

if __name__ == "__main__":
    main()