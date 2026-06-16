from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

URL_BASE_DATOS = os.getenv("DATABASE_URL")

engine = create_engine(URL_BASE_DATOS)

# Creamos una fábrica de sesiones para interactuar con la base de datos
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependencia que usará FastAPI para abrir y cerrar la conexión automáticamente
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Prueba rápida de conexión
try:
    with engine.connect() as connection:
        print("¡Conexión a la base de datos en Neon exitosa!")
except Exception as e:
    print(f"Error al conectar: {e}")