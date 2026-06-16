from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import List, Optional
from dotenv import load_dotenv
import jwt
import os
import shutil
import cloudinary
import cloudinary.uploader
from fastapi.middleware.cors import CORSMiddleware

import models
import schemas
from database import engine, get_db

# Cargamos las variables del .env
load_dotenv()

# --- CONFIGURACIÓN DE CLOUDINARY ---
cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
    secure = True
)

# Crea las tablas si no existen
models.Base.metadata.create_all(bind=engine)

app = FastAPI()




# ... (acá está tu app = FastAPI() ) ...

# Le abrimos la puerta al frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # El "*" permite que cualquier página consulte tu API (Ideal para el MVP)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DE RUTAS ABSOLUTAS (Asegura compatibilidad con Render) ---
# 1. Obtenemos la ruta exacta de la carpeta donde está tu main.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Armamos la ruta completa y segura hacia 'static/uploads'
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")

# 3. Creamos las carpetas usando esa ruta exacta antes de montar
os.makedirs(UPLOADS_DIR, exist_ok=True)

# 4. Montamos FastAPI usando la ruta absoluta segura
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Configuración de encriptación y JWT
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "clave_de_respaldo")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # El token dura 7 días

# Le indicamos a FastAPI dónde tiene que ir el usuario a buscar su token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Dependencia para obtener el usuario actual mediante el Token
def obtener_usuario_actual(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credenciales_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credenciales_exception
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="El token ha expirado")
    except jwt.InvalidTokenError:
        raise credenciales_exception
    
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credenciales_exception
    return user

# Función auxiliar para generar el token JWT
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

@app.post("/login/")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = crear_token_acceso(data={"sub": user.email, "id": user.id, "rol": user.rol})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/prestadores/")
def crear_perfil_prestador(
    perfil: schemas.ProviderCreate, 
    db: Session = Depends(get_db), 
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    perfil_existente = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if perfil_existente:
        raise HTTPException(status_code=400, detail="Este usuario ya tiene un perfil de prestador")
    
    nuevo_prestador = models.Provider(
        user_id=usuario_actual.id,
        dni=perfil.dni,
        ciudad=perfil.ciudad,
        provincia=perfil.provincia,
        descripcion=perfil.descripcion,
        experiencia=perfil.experiencia,
        whatsapp=perfil.whatsapp
    )
    
    categorias = db.query(models.Category).filter(models.Category.id.in_(perfil.categorias_ids)).all()
    nuevo_prestador.categories.extend(categorias)
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
    query = db.query(models.Provider)
    if ciudad:
        query = query.filter(models.Provider.ciudad.ilike(f"%{ciudad}%"))
    if categoria_id:
        query = query.filter(models.Provider.categories.any(id=categoria_id))
        
    prestadores = query.all()
    resultados = []

    for prestador in prestadores:
        total_resenas = len(prestador.reviews)
        promedio = sum([r.calidad for r in prestador.reviews]) / total_resenas if total_resenas > 0 else 0

        pts_calificacion = (promedio / 5.0) * 40
        pts_resenas = min(total_resenas, 20)
        pts_verificado = 15 if prestador.verificado else 0
        pts_actividad = 15 
        
        pts_completitud = 0
        if prestador.foto_perfil: pts_completitud += 5
        if prestador.descripcion and len(prestador.descripcion) > 20: pts_completitud += 5

        score_final = pts_calificacion + pts_resenas + pts_verificado + pts_actividad + pts_completitud

        if prestador.destacado:
            score_final += 1000 

        prestador_dict = prestador.__dict__.copy()
        prestador_dict['score'] = round(score_final, 2)
        prestador_dict['categories'] = prestador.categories
        
        resultados.append(prestador_dict)

    resultados.sort(key=lambda x: x['score'], reverse=True)
    return resultados

@app.post("/prestadores/{prestador_id}/resenas/")
def crear_resena(
    prestador_id: int,
    resena: schemas.ReviewCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="El prestador no existe")
        
    if prestador.user_id == usuario_actual.id:
        raise HTTPException(status_code=400, detail="No podés calificarte a vos mismo")
        
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

@app.post("/solicitudes/", response_model=schemas.JobRequestOut)
def crear_solicitud(
    solicitud: schemas.JobRequestCreate,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    nueva_solicitud = models.JobRequest(
        client_id=usuario_actual.id,
        categoria=solicitud.categoria,
        ciudad=solicitud.ciudad,
        descripcion=solicitud.descripcion,
        presupuesto=solicitud.presupuesto,
        estado="abierta"
    )
    
    db.add(nueva_solicitud)
    db.commit()
    db.refresh(nueva_solicitud)
    return nueva_solicitud

@app.get("/solicitudes/", response_model=List[schemas.JobRequestOut])
def ver_solicitudes_abiertas(
    ciudad: Optional[str] = None,
    categoria: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.JobRequest).filter(models.JobRequest.estado == "abierta")
    if ciudad:
        query = query.filter(models.JobRequest.ciudad.ilike(f"%{ciudad}%"))
    if categoria:
        query = query.filter(models.JobRequest.categoria.ilike(f"%{categoria}%"))
        
    return query.all()

@app.post("/upload/")
def subir_imagen(file: UploadFile = File(...)):
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    nombre_seguro = f"{timestamp}_{file.filename.replace(' ', '_')}"
    
    ruta_guardado = os.path.join(UPLOADS_DIR, nombre_seguro)
    
    with open(ruta_guardado, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    url_imagen = f"https://api-oficiosya.onrender.com/static/uploads/{nombre_seguro}" if os.getenv("DATABASE_URL") else f"http://127.0.0.1:8000/static/uploads/{nombre_seguro}"
    return {"mensaje": "Imagen subida con éxito", "url": url_imagen}

@app.put("/admin/prestadores/{prestador_id}/verificar/")
def verificar_prestador(
    prestador_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    if usuario_actual.rol != "admin":
        raise HTTPException(status_code=403, detail="Acceso denegado. Se requieren permisos de administrador.")
        
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
        
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
        
    prestador.destacado = True
    db.commit()
    return {"mensaje": f"Suscripción activada. El prestador {prestador_id} ahora aparecerá primero en las búsquedas."}

@app.post("/prestadores/me/portfolio/", response_model=schemas.PortfolioItemOut)
def subir_foto_portafolio(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    prestador = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if not prestador:
        raise HTTPException(status_code=400, detail="Primero debes crear tu perfil de prestador.")

    limite_fotos = 10 if prestador.destacado else 2
    fotos_actuales = db.query(models.PortfolioItem).filter(models.PortfolioItem.provider_id == prestador.id).count()

    if fotos_actuales >= limite_fotos:
        raise HTTPException(
            status_code=400, 
            detail=f"Alcanzaste el límite de tu plan ({limite_fotos} fotos). Pasate a Premium para subir más."
        )
    
    try:
        resultado = cloudinary.uploader.upload(file.file, folder="portfolio")
        url_publica = resultado.get("secure_url")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir la imagen: {e}")

    nuevo_item = models.PortfolioItem(provider_id=prestador.id, url_foto=url_publica)
    db.add(nuevo_item)
    db.commit()
    db.refresh(nuevo_item)

    return nuevo_item