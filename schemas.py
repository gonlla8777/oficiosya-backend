from pydantic import BaseModel, EmailStr
from typing import Optional
from typing import List
from pydantic import BaseModel, EmailStr, Field

# Esquema para validar los datos que envía el usuario al registrarse
class UserCreate(BaseModel):
    nombre: str
    email: EmailStr
    password: str
    telefono: Optional[str] = None
    rol: str = "cliente" # Por defecto, todos nacen como clientes]

class ProviderCreate(BaseModel):
    dni: str
    ciudad: str
    provincia: str
    descripcion: str
    experiencia: str
    whatsapp: str
    categorias_ids: List[int] # Una lista con los IDs de los oficios que hace (ej. [8] para Mecánico)

# ... (tu código anterior) ...

# Esquema para mostrar la categoría dentro del perfil
class CategoryOut(BaseModel):
    id: int
    nombre: str

    class Config:
        from_attributes = True

# Esquema público del Prestador (Lo que verá el cliente)
class ProviderOut(BaseModel):
    id: int
    ciudad: str
    provincia: str
    descripcion: str
    experiencia: str
    whatsapp: str
    verificado: bool
    destacado: bool
    categories: List[CategoryOut] = []
    score: float = 0.0 # NUEVO: La métrica del ranking

    class Config:
        from_attributes = True

class ReviewCreate(BaseModel):
    # Field(ge=1, le=5) obliga a que el número sea Mayor o Igual a 1, y Menor o Igual a 5
    calidad: int = Field(..., ge=1, le=5)
    puntualidad: int = Field(..., ge=1, le=5)
    precio: int = Field(..., ge=1, le=5)
    trato: int = Field(..., ge=1, le=5)
    comentario: Optional[str] = None

# Esquema para crear la solicitud (Lo que envía el cliente)
class JobRequestCreate(BaseModel):
    categoria: str
    ciudad: str
    descripcion: str
    presupuesto: str

# Esquema para mostrar la solicitud en el panel de búsqueda
class JobRequestOut(BaseModel):
    id: int
    client_id: int
    categoria: str
    ciudad: str
    descripcion: str
    presupuesto: str
    estado: str

    class Config:
        from_attributes = True

# Esquema para crear la solicitud (Lo que envía el cliente)
class JobRequestCreate(BaseModel):
    categoria: str
    ciudad: str
    descripcion: str
    presupuesto: str

# Esquema para mostrar la solicitud en el panel de búsqueda
class JobRequestOut(BaseModel):
    id: int
    client_id: int
    categoria: str
    ciudad: str
    descripcion: str
    presupuesto: str
    estado: str

    class Config:
        from_attributes = True

class PortfolioItemOut(BaseModel):
    id = int
    url_foto = str

    class Config:
        from_attributes = True