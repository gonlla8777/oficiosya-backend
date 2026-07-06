from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Table
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

# Tabla intermedia para la relación "muchos a muchos" entre Prestadores y Categorías
provider_categories = Table(
    "provider_categories",
    Base.metadata,
    Column("provider_id", Integer, ForeignKey("providers.id")),
    Column("category_id", Integer, ForeignKey("categories.id"))
)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True)
    telefono = Column(String)
    rol = Column(String, default="cliente") 
    fecha_registro = Column(DateTime, default=datetime.datetime.utcnow)
    foto_perfil = Column(String, nullable=True)
    provider_profile = relationship("Provider", back_populates="user", uselist=False)


class Provider(Base):
    __tablename__ = "providers"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    instagram = Column(String, nullable=True)
    ciudad = Column(String)
    provincia = Column(String)
    descripcion = Column(Text)
    experiencia = Column(String)
    whatsapp = Column(String)
    foto_perfil = Column(String)
    verificado = Column(Boolean, default=False)
    destacado = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    urgencias = Column(Boolean, default=False)
    
    # Relaciones
    user = relationship("User", back_populates="provider_profile")
    categories = relationship("Category", secondary=provider_categories, back_populates="providers")
    reviews = relationship("Review", back_populates="provider")
    portfolio = relationship("PortfolioItem", back_populates="provider", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="provider")
    


class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)

    providers = relationship("Provider", secondary=provider_categories, back_populates="categories")


class Review(Base):
    __tablename__ = "reviews"
    
    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"))
    client_id = Column(Integer, ForeignKey("users.id"))
    calidad = Column(Integer) # 1 a 5
    puntualidad = Column(Integer) # 1 a 5
    precio = Column(Integer) # 1 a 5
    trato = Column(Integer) # 1 a 5
    comentario = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    provider = relationship("Provider", back_populates="reviews")


class JobRequest(Base):
    __tablename__ = "job_requests"
    
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id"))
    categoria = Column(String)
    ciudad = Column(String)
    descripcion = Column(Text)
    presupuesto = Column(String)
    estado = Column(String, default="abierta") # abierta, cerrada, etc.


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id"))
    plan = Column(String)
    fecha_inicio = Column(DateTime, default=datetime.datetime.utcnow)
    fecha_fin = Column(DateTime)

    provider = relationship("Provider", back_populates="subscriptions")

class PortfolioItem(Base):
    __tablename__ = "portfolio_items"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("providers.id", ondelete="CASCADE"))
    url_foto = Column(String, nullable=False)

    # Relación inversa para poder acceder desde el prestador
    provider = relationship("Provider", back_populates="portfolio")