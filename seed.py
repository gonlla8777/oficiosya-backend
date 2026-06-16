from database import SessionLocal
import models

def poblar_categorias():
    # Lista de categorías iniciales del MVP
    categorias_iniciales = [
        "Electricista", "Plomero", "Gasista", "Pintor", "Albañil",
        "Carpintero", "Herrero", "Mecánico", "Cerrajero", "Jardinero",
        "Técnico en Aire Acondicionado", "Fletes", "Limpieza",
        "Instalador de Cámaras", "Técnico Informático"
    ]
    
    db = SessionLocal()
    try:
        for nombre_cat in categorias_iniciales:
            # Verificamos si la categoría ya existe para no duplicarla
            existe = db.query(models.Category).filter(models.Category.nombre == nombre_cat).first()
            if not existe:
                nueva_categoria = models.Category(nombre=nombre_cat)
                db.add(nueva_categoria)
        
        db.commit()
        print("¡Categorías iniciales cargadas con éxito en Neon!")
    except Exception as e:
        db.rollback()
        print(f"Error al cargar las categorías: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    poblar_categorias()