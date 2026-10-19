"""Dashboard de filmes para el reto de Streamlit y Cloud Firestore."""

import hashlib
import json

import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore


CAMPOS = ("name", "company", "director", "genre")
COLECCION = "movies"

st.set_page_config(
    page_title="Dashboard de filmes",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


def id_filme(datos):
    """Construye un ID estable; una importación repetida no duplica registros."""
    campos = [" ".join(str(datos[c]).strip().split()).casefold() for c in CAMPOS]
    cadena = json.dumps(campos, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(cadena.encode("utf-8")).hexdigest()[:32]


@st.cache_resource
def obtener_firestore():
    """Abre Firestore con credenciales guardadas en Secrets de Streamlit."""
    try:
        clave = st.secrets["FIREBASE_CREDENTIALS_JSON"]
    except (KeyError, FileNotFoundError) as exc:
        raise RuntimeError(
            "Falta FIREBASE_CREDENTIALS_JSON en los Secrets de Streamlit."
        ) from exc

    info = json.loads(clave)
    try:
        app = firebase_admin.get_app("dashboard-filmes")
    except ValueError:
        app = firebase_admin.initialize_app(
            credentials.Certificate(info), name="dashboard-filmes"
        )
    return firestore.client(app=app)


@st.cache_data(ttl=120, show_spinner="Cargando películas desde Firestore...")
def cargar_filmes():
    """Lee toda la colección al iniciar y la convierte en un DataFrame."""
    db = obtener_firestore()
    registros = []
    for documento in db.collection(COLECCION).stream():
        datos = documento.to_dict() or {}
        registros.append({campo: datos.get(campo, "") for campo in CAMPOS})
    return pd.DataFrame(registros, columns=CAMPOS).fillna("")


def buscar_titulo(datos, texto):
    """Busca coincidencias parciales sin distinguir mayúsculas ni minúsculas."""
    return datos[
        datos["name"].astype(str).str.contains(
            texto.strip(), case=False, regex=False, na=False
        )
    ]


def filtrar_director(datos, director):
    """Filtra películas del director elegido."""
    return datos[
        datos["director"].astype(str).str.casefold() == director.casefold()
    ]


def mostrar_todos_cambio():
    if st.session_state.mostrar_todos:
        st.session_state.modo = "todos"


def ejecutar_busqueda():
    st.session_state.modo = "titulo"
    st.session_state.criterio = st.session_state.texto_titulo.strip()
    st.session_state.mostrar_todos = False


def ejecutar_filtro():
    st.session_state.modo = "director"
    st.session_state.criterio = st.session_state.director_elegido
    st.session_state.mostrar_todos = False


st.title("🎬 Dashboard de filmes")
st.caption("Catálogo interactivo conectado a Cloud Firestore")

try:
    filmes = cargar_filmes()
except Exception as exc:
    st.error("No se pudo conectar a Firestore. Revisa los Secrets y el proyecto Firebase.")
    st.caption(f"Detalle técnico: {exc}")
    st.stop()

if "modo" not in st.session_state:
    st.session_state.modo = "todos"
if "criterio" not in st.session_state:
    st.session_state.criterio = ""
if "mostrar_todos" not in st.session_state:
    st.session_state.mostrar_todos = True
if st.session_state.pop("volver_a_todos", False):
    st.session_state.modo = "todos"
    st.session_state.mostrar_todos = True
if st.session_state.get("registro_creado"):
    st.success(st.session_state.pop("registro_creado"))

# Catálogos derivados del DataFrame leído al inicio.
directores = sorted(filmes["director"].astype(str).loc[lambda x: x.ne("")].unique())
companias = sorted(filmes["company"].astype(str).loc[lambda x: x.ne("")].unique())
generos = sorted(filmes["genre"].astype(str).loc[lambda x: x.ne("")].unique())

with st.sidebar:
    st.header("Explorar catálogo")
    st.checkbox(
        "Mostrar todos los filmes",
        key="mostrar_todos",
        on_change=mostrar_todos_cambio,
    )

    st.subheader("Buscar por título")
    st.text_input("Título del filme", key="texto_titulo", placeholder="Ej. love")
    st.button(
        "Buscar filmes",
        on_click=ejecutar_busqueda,
        use_container_width=True,
    )

    st.subheader("Filtrar por director")
    if directores:
        st.selectbox("Selecciona un director", directores, key="director_elegido")
        st.button(
            "Filtrar director",
            on_click=ejecutar_filtro,
            use_container_width=True,
        )
    else:
        st.info("Todavía no hay directores en la colección.")

    st.divider()
    st.subheader("Nuevo filme")
    with st.form("nuevo_filme", clear_on_submit=True):
        nombre_nuevo = st.text_input("Nombre del filme *")
        compania_nueva = st.selectbox("Compañía", companias or ["Sin compañía"])
        director_nuevo = st.selectbox("Director", directores or ["Sin director"])
        genero_nuevo = st.selectbox("Género", generos or ["Sin género"])
        insertar = st.form_submit_button("Crear nuevo filme", use_container_width=True)

    if insertar:
        if not nombre_nuevo.strip():
            st.warning("Escribe el título antes de guardar.")
        else:
            nuevo = {
                "name": nombre_nuevo.strip(),
                "company": compania_nueva,
                "director": director_nuevo,
                "genre": genero_nuevo,
            }
            try:
                referencia = obtener_firestore().collection(COLECCION).document(id_filme(nuevo))
                if referencia.get().exists:
                    st.warning("Esta película ya existe con los mismos datos.")
                else:
                    referencia.set(nuevo)
                    cargar_filmes.clear()
                    st.session_state["registro_creado"] = "Película guardada correctamente en Firestore."
                    st.session_state["volver_a_todos"] = True
                    st.rerun()
            except Exception as exc:
                st.error(f"No se pudo guardar la película: {exc}")

if filmes.empty:
    st.warning("La colección 'movies' está vacía. Ejecuta primero la migración en Colab.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Películas", len(filmes))
col2.metric("Directores", filmes["director"].nunique())
col3.metric("Géneros", filmes["genre"].nunique())

if st.session_state.modo == "titulo":
    consulta = st.session_state.criterio
    if consulta:
        resultado = buscar_titulo(filmes, consulta)
        titulo_seccion = f'Resultados para "{consulta}"'
    else:
        resultado = filmes.iloc[0:0]
        titulo_seccion = "Escribe un título para buscar"
elif st.session_state.modo == "director":
    elegido = st.session_state.criterio
    resultado = filtrar_director(filmes, elegido)
    titulo_seccion = f"Películas de {elegido}"
else:
    resultado = filmes
    titulo_seccion = "Todos los filmes"

st.header(titulo_seccion)
st.write(f"Total de filmes encontrados: **{len(resultado):,}**")

if resultado.empty:
    st.info("No hay películas que coincidan con la búsqueda.")
else:
    st.dataframe(
        resultado.loc[:, list(CAMPOS)].sort_values("name", key=lambda x: x.str.casefold()),
        hide_index=True,
        use_container_width=True,
        height=460,
        column_config={
            "name": "Título",
            "company": "Compañía",
            "director": "Director",
            "genre": "Género",
        },
    )

if st.session_state.modo == "todos" and not filmes.empty:
    st.subheader("Distribución por género")
    conteo_generos = filmes["genre"].value_counts().rename_axis("Género").rename("Películas")
    st.bar_chart(conteo_generos)

st.caption("Ejercicio académico. Antes de permitir escrituras públicas de forma permanente, agrega autenticación y controles de acceso.")
