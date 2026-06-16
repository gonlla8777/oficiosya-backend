from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import jwt
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from fastapi.security import OAuth2PasswordBearer
from fastapi import status 
from typing import List, Optional
import models
import schemas
from database import engine, get_db
from fastapi import File, UploadFile
from fastapi.staticfiles import StaticFiles
import shutil
import os
from fastapi.staticfiles import StaticFiles
import os


# Cargamos las variables del .env
load_dotenv()

# Crea las tablas si no existen
models.Base.metadata.create_all(bind=engine)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- NUEVAS LÍNEAS: Crea las carpetas si no existen en el servidor ---
os.makedirs("static/uploads", exist_ok=True)

# Mapea la carpeta física 'static' a la dirección web '/static'
app.mount("/static", StaticFiles(directory="static"), name="static")


# Configuración de encriptación y JWT
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "clave_de_respaldo")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # El token dura 7 días

# Le indicamos a FastAPI dónde tiene que ir el usuario a buscar su token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Esta función actúa como el "patovica" de la puerta
def obtener_usuario_actual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credenciales_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Intentamos decodificar el token con nuestra clave secreta
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credenciales_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado")
    except jwt.InvalidTokenError:
        raise credenciales_exception
    
    # Buscamos al usuario en la base de datos
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credenciales_exception
    return user

# Función auxiliar para generar el pase VIP (Token)
def crear_token_acceso(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

@app.get("/")
def leer_raiz():
    return {"mensaje": "Backend de OficiosYa funcionando correctamente"}

@app.post("/usuarios/")
def crear_usuario(usuario: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.email == usuario.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="El email ya está registrado")
    
    hashed_password = pwd_context.hash(usuario.password)
    nuevo_usuario = models.User(
        nombre=usuario.nombre, email=usuario.email,
        password_hash=hashed_password, telefono=usuario.telefono, rol=usuario.rol
    )
    
    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)
    return {"mensaje": "Usuario creado con éxito", "usuario_id": nuevo_usuario.id}

# --- NUEVO ENDPOINT: INICIO DE SESIÓN ---
@app.post("/login/")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. Buscamos al usuario por su email
    # (FastAPI usa el campo 'username' por defecto en sus formularios, pero nosotros le pasaremos el email)
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    
    # 2. Verificamos que exista y que la contraseña coincida con la encriptada
    if not user or not pwd_context.verify(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 3. Generamos el token con sus datos clave adentro
    access_token = crear_token_acceso(data={"sub": user.email, "id": user.id, "rol": user.rol})
    
    # 4. Le entregamos la llave al usuario
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/prestadores/")
def crear_perfil_prestador(
    perfil: schemas.ProviderCreate, 
    db: Session = Depends(get_db), 
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    # Verificamos que no tenga un perfil ya creado
    perfil_existente = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if perfil_existente:
        raise HTTPException(status_code=400, detail="Este usuario ya tiene un perfil de prestador")
    
    # Creamos el perfil
    nuevo_prestador = models.Provider(
        user_id=usuario_actual.id,
        dni=perfil.dni,
        ciudad=perfil.ciudad,
        provincia=perfil.provincia,
        descripcion=perfil.descripcion,
        experiencia=perfil.experiencia,
        whatsapp=perfil.whatsapp
    )
    
    # Buscamos las categorías que seleccionó y se las asignamos
    categorias = db.query(models.Category).filter(models.Category.id.in_(perfil.categorias_ids)).all()
    nuevo_prestador.categories.extend(categorias)
    
    # También le actualizamos el rol al usuario
    usuario_actual.rol = "prestador"
    
    db.add(nuevo_prestador)
    db.commit()
    db.refresh(nuevo_prestador)
    
    return {"mensaje": "Perfil de prestador creado con éxito", "prestador_id": nuevo_prestador.id}

@app.get("/prestadores/buscar/", response_model=List[schemas.ProviderOut])
def buscar_prestadores(
    ciudad: Optional[str] = None,
    categoria_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    # 1. Filtros base (SQL puro)
    query = db.query(models.Provider)
    if ciudad:
        query = query.filter(models.Provider.ciudad.ilike(f"%{ciudad}%"))
    if categoria_id:
        query = query.filter(models.Provider.categories.any(id=categoria_id))
        
    prestadores = query.all()
    resultados = []

    # 2. El Motor Analítico: Calculamos el score dinámico para cada prestador
    for prestador in prestadores:
        # Extraemos los datos brutos
        total_resenas = len(prestador.reviews)
        promedio = sum([r.calidad for r in prestador.reviews]) / total_resenas if total_resenas > 0 else 0

        # NORMALIZACIÓN (Escala ideal de 100 puntos máximos)
        
        # A. Calificación (40%): 5 estrellas = 40 pts
        pts_calificacion = (promedio / 5.0) * 40
        
        # B. Cantidad de Reseñas (20%): Topeamos en 20 reseñas (1 pt por reseña)
        pts_resenas = min(total_resenas, 20)
        
        # C. Verificado (15%): Booleano directo
        pts_verificado = 15 if prestador.verificado else 0
        
        # D. Actividad Reciente (15%): En el MVP le damos puntaje completo. 
        # (A futuro, si último_login < 7 días = 15, sino 0)
        pts_actividad = 15 
        
        # E. Completitud (10%): Validamos campos clave
        pts_completitud = 0
        if prestador.foto_perfil: pts_completitud += 5
        if prestador.descripcion and len(prestador.descripcion) > 20: pts_completitud += 5

        # 3. Sumatoria Final
        score_final = pts_calificacion + pts_resenas + pts_verificado + pts_actividad + pts_completitud

        # 4. Regla de Negocio (Monetización): Los perfiles Premium rompen la escala para salir primeros
        if prestador.destacado:
            score_final += 1000 

        # Empaquetamos los datos para enviarlos al cliente
        prestador_dict = prestador.__dict__.copy()
        prestador_dict['score'] = round(score_final, 2)
        prestador_dict['categories'] = prestador.categories
        
        resultados.append(prestador_dict)

    # 5. Ordenamiento final: De mayor a menor Score
    resultados.sort(key=lambda x: x['score'], reverse=True)

    return resultados

@app.post("/prestadores/{prestador_id}/resenas/")
def crear_resena(
    prestador_id: int,
    resena: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual) # Candado: debe estar logueado
):
    # 1. Verificamos que el prestador que quieren calificar realmente exista
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="El prestador no existe")
        
    # 2. Regla antifraude: Un prestador no puede auto-calificarse
    if prestador.user_id == usuario_actual.id:
        raise HTTPException(status_code=400, detail="No podés calificarte a vos mismo")
        
    # 3. Armamos la reseña vinculando al prestador y al cliente que la escribe
    nueva_resena = models.Review(
        provider_id=prestador_id,
        client_id=usuario_actual.id,
        calidad=resena.calidad,
        puntualidad=resena.puntualidad,
        precio=resena.precio,
        trato=resena.trato,
        comentario=resena.comentario
    )
    
    db.add(nueva_resena)
    db.commit()
    
    return {"mensaje": "¡Reseña guardada exitosamente!"}

# --- NUEVO ENDPOINT: PUBLICAR SOLICITUD DE TRABAJO ---
@app.post("/solicitudes/", response_model=schemas.JobRequestOut)
def crear_solicitud(
    solicitud: schemas.JobRequestCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual) # Candado: debe estar logueado
):
    nueva_solicitud = models.JobRequest(
        client_id=usuario_actual.id,
        categoria=solicitud.categoria,
        ciudad=solicitud.ciudad,
        descripcion=solicitud.descripcion,
        presupuesto=solicitud.presupuesto,
        estado="abierta" # Todas nacen abiertas
    )
    
    db.add(nueva_solicitud)
    db.commit()
    db.refresh(nueva_solicitud)
    
    return nueva_solicitud

# --- NUEVO ENDPOINT: VER CARTELERA DE TRABAJOS ---
@app.get("/solicitudes/", response_model=List[schemas.JobRequestOut])
def ver_solicitudes_abiertas(
    ciudad: Optional[str] = None,
    categoria: Optional[str] = None,
    db: Session = Depends(get_db)
):
    # Traemos solo las que están "abiertas"
    query = db.query(models.JobRequest).filter(models.JobRequest.estado == "abierta")
    
    # Filtro opcional por ciudad
    if ciudad:
        query = query.filter(models.JobRequest.ciudad.ilike(f"%{ciudad}%"))
        
    # Filtro opcional por categoría
    if categoria:
        query = query.filter(models.JobRequest.categoria.ilike(f"%{categoria}%"))
        
    return query.all()

# --- NUEVO ENDPOINT: SUBIR IMAGEN ---
@app.post("/upload/")
def subir_imagen(file: UploadFile = File(...)):
    # 1. Creamos un nombre único usando la fecha y hora actual para evitar nombres duplicados
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    nombre_seguro = f"{timestamp}_{file.filename.replace(' ', '_')}"
    
    # 2. Definimos la ruta física donde se guardará en la computadora/servidor
    ruta_guardado = os.path.join("static", "uploads", nombre_seguro)
    
    # 3. Guardamos el archivo físicamente
    with open(ruta_guardado, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 4. Generamos la URL web para que el frontend o la base de datos puedan acceder a ella
    url_imagen = f"http://127.0.0.1:8000/static/uploads/{nombre_seguro}"
    
    return {"mensaje": "Imagen subida con éxito", "url": url_imagen}

# --- ENDPOINTS DE ADMINISTRACIÓN (PANEL DE CONTROL) ---

@app.put("/admin/prestadores/{prestador_id}/verificar/")
def verificar_prestador(
    prestador_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    # 1. Validamos que el usuario logueado sea el dueño/administrador
    if usuario_actual.rol != "admin":
        raise HTTPException(status_code=403, detail="Acceso denegado. Se requieren permisos de administrador.")
        
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
        
    # 2. Le otorgamos la insignia de confianza
    prestador.verificado = True
    db.commit()
    
    return {"mensaje": f"Identidad verificada. El score del prestador {prestador_id} va a subir 15 puntos."}

@app.put("/admin/prestadores/{prestador_id}/destacar/")
def destacar_prestador(
    prestador_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    if usuario_actual.rol != "admin":
        raise HTTPException(status_code=403, detail="Acceso denegado. Se requieren permisos de administrador.")
        
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
        
    # 3. Activamos el modelo de monetización (Premium)
    prestador.destacado = True
    db.commit()
    
    return {"mensaje": f"Suscripción activada. El prestador {prestador_id} ahora aparecerá primero en las búsquedas."}