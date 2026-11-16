"""Configuración: lee las claves del archivo .env y define rutas."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Carpeta raíz del proyecto (dos niveles por encima de este archivo: src/vigia/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Carga las variables del .env en el entorno (si el archivo existe)
load_dotenv(PROJECT_ROOT / ".env")

# Ruta de la base de datos. Se puede cambiar con la variable VIGIA_DB.
DB_PATH = Path(os.getenv("VIGIA_DB", PROJECT_ROOT / "data" / "vigia.db"))

# País para los precios (código ISO de 2 letras)
COUNTRY = os.getenv("VIGIA_COUNTRY", "ES")


def get_itad_key() -> str:
    """Devuelve la clave de IsThereAnyDeal o lanza un error claro si falta."""
    key = os.getenv("ITAD_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Falta ITAD_API_KEY. Ponla en el archivo .env (nunca en el código)."
        )
    return key


def get_ggdeals_key() -> str | None:
    """Clave de GG.deals. Es opcional: sin ella solo se consulta Steam."""
    key = os.getenv("GGDEALS_API_KEY", "").strip()
    return key or None


def keyshop_alerts_enabled() -> bool:
    """KEYSHOP_ALERTS=off en el .env desactiva los avisos de tiendas de claves."""
    return os.getenv("KEYSHOP_ALERTS", "on").strip().lower() not in ("off", "0", "no", "false")


def get_serpapi_key() -> str | None:
    """Clave de SerpApi. Opcional: sin ella no se vigilan productos físicos."""
    key = os.getenv("SERPAPI_KEY", "").strip()
    return key or None


# Horas mínimas entre dos consultas del mismo producto físico (ahorra búsquedas:
# el plan gratuito de SerpApi da 250 al mes)
PHYSICAL_INTERVAL_HOURS = float(os.getenv("PHYSICAL_INTERVAL_HOURS", "20"))
