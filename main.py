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

# --- CONFIGURACIÓN CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DE RUTAS ABSOLUTAS ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Configuración de encriptación y JWT
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "clave_de_respaldo")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # El token dura 7 días

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

@app.get("/prestadores/buscar/")
def buscar_prestadores(
    ciudad: Optional[str] = None,
    categoria_id: Optional[int] = None,
    admin_mode: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(models.Provider)
    
    if not admin_mode:
        query = query.filter(models.Provider.activo == True)
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

        # Construcción manual y robusta del diccionario de salida para evitar fallos de mapeo
        prestador_dict = {
            "id": prestador.id,
            "user_id": prestador.user_id,
            "nombre": prestador.user.nombre, # Enlazado para mostrar en Home.jsx
            "dni": prestador.dni,
            "ciudad": prestador.ciudad,
            "provincia": prestador.provincia,
            "descripcion": prestador.descripcion,
            "experiencia": prestador.experiencia,
            "whatsapp": prestador.whatsapp,
            "foto_perfil": prestador.foto_perfil, # Enlazado para mostrar en Home.jsx
            "verificado": prestador.verificado,
            "destacado": prestador.destacado,
            "activo": getattr(prestador, 'activo', True),
            "score": round(score_final, 2),
            "categorias": [{"id": c.id, "nombre": c.nombre} for c in prestador.categories] # Unificado al español
        }
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

@app.post("/upload/")
def subir_imagen(file: UploadFile = File(...)):
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
        
    prestador.verificado = not prestador.verificado
    db.commit()
    return {"mensaje": f"Estado de verificación actualizado a: {prestador.verificado}"}

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
        
    prestador.destacado = not prestador.destacado
    db.commit()
    return {"mensaje": f"Estado premium actualizado a: {prestador.destacado}"}

@app.put("/admin/prestadores/{prestador_id}/toggle_activo/")
def toggle_activo_prestador(
    prestador_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    if usuario_actual.rol != "admin":
        raise HTTPException(status_code=403, detail="Acceso denegado.")
        
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
        
    prestador.activo = not getattr(prestador, 'activo', True)
    db.commit()
    estado_str = "Habilitado" if prestador.activo else "Deshabilitado/Bloqueado"
    return {"mensaje": f"El prestador ahora está: {estado_str}"}

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

@app.get("/prestadores/detalle/{prestador_id}")
def ver_detalle_prestador(prestador_id: int, db: Session = Depends(get_db)):
    prestador = db.query(models.Provider).filter(models.Provider.id == prestador_id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Prestador no encontrado")
    
    return {
        "id": prestador.id,
        "nombre": prestador.user.nombre,
        "ciudad": prestador.ciudad,
        "descripcion": prestador.descripcion,
        "experiencia": prestador.experiencia,
        "whatsapp": prestador.whatsapp,
        "foto_perfil": prestador.foto_perfil, # Entregado correctamente a PerfilDetalle.jsx
        "verificado": prestador.verificado,
        "destacado": prestador.destacado,
        "categorias": [{"id": c.id, "nombre": c.nombre} for c in prestador.categories],
        "portfolio": [{"id": p.id, "url_foto": p.url_foto} for p in prestador.portfolio],
        "reviews": [
            {
                "id": r.id, 
                "comentario": r.comentario, 
                "calidad": r.calidad,
                "fecha": r.created_at.strftime("%d/%m/%Y")
            } for r in prestador.reviews
        ]
    }

@app.get("/categorias/")
def obtener_todas_las_categorias(db: Session = Depends(get_db)):
    """Devuelve la lista completa de oficios para el frontend"""
    return db.query(models.Category).all()

@app.get("/prestadores/me")
def obtener_mi_perfil(
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    """Busca si el usuario logueado ya tiene un perfil creado"""
    prestador = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if not prestador:
        return {"tiene_perfil": False}
    
    return {
        "tiene_perfil": True,
        "id": prestador.id,
        "dni": prestador.dni,
        "ciudad": prestador.ciudad,
        "provincia": prestador.provincia,
        "descripcion": prestador.descripcion,
        "experiencia": prestador.experiencia,
        "whatsapp": prestador.whatsapp,
        "foto_perfil": prestador.foto_perfil,
        "verificado": prestador.verificado,
        "destacado": prestador.destacado,
        "categorias": [{"id": c.id, "nombre": c.nombre} for c in prestador.categories],
        "portfolio": [{"id": p.id, "url_foto": p.url_foto} for p in prestador.portfolio] # Entregado correctamente a Dashboard.jsx
    }

@app.put("/prestadores/me")
def actualizar_mi_perfil(
    datos: dict, 
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    """Modifica el perfil existente del trabajador"""
    prestador = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    prestador.dni = datos.get("dni", prestador.dni)
    prestador.provincia = datos.get("provincia", prestador.provincia)
    prestador.ciudad = datos.get("ciudad", prestador.ciudad)
    prestador.descripcion = datos.get("descripcion", prestador.descripcion)
    prestador.experiencia = datos.get("experiencia", prestador.experiencia)
    prestador.whatsapp = datos.get("whatsapp", prestador.whatsapp)
    
    if "categorias_ids" in datos and datos["categorias_ids"]:
        nuevas_cats = db.query(models.Category).filter(models.Category.id.in_(datos["categorias_ids"])).all()
        prestador.categories = nuevas_cats

    db.commit()
    return {"mensaje": "Perfil actualizado con éxito"}

@app.post("/prestadores/me/foto-perfil")
async def subir_foto_perfil(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    """Sube la foto del avatar principal a Cloudinary y guarda la URL"""
    prestador = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Primero debés crear tu perfil básico")
    
    try:
        resultado = cloudinary.uploader.upload(file.file, folder="avatars")
        url_foto = resultado.get("secure_url")
        
        prestador.foto_perfil = url_foto
        db.commit()
        
        return {"mensaje": "Foto de perfil actualizada", "url_foto": url_foto}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir a Cloudinary: {str(e)}")
    
@app.delete("/prestadores/me/portfolio/{foto_id}")
def eliminar_foto_portfolio(
    foto_id: int,
    db: Session = Depends(get_db),
    usuario_actual: models.User = Depends(obtener_usuario_actual)
):
    """Elimina una foto específica del portafolio del usuario"""
    prestador = db.query(models.Provider).filter(models.Provider.user_id == usuario_actual.id).first()
    if not prestador:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    
    foto = db.query(models.PortfolioItem).filter(models.PortfolioItem.id == foto_id, models.PortfolioItem.provider_id == prestador.id).first()
    if not foto:
        raise HTTPException(status_code=404, detail="Foto no encontrada o no te pertenece")
    
    db.delete(foto)
    db.commit()
    return {"mensaje": "Foto eliminada con éxito"}