import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class Config:
    HOST = os.getenv("SCIM_HOST", "0.0.0.0")
    PORT = int(os.getenv("SCIM_PORT", "6000"))
    BASE_URL = os.getenv("SCIM_BASE_URL", "http://localhost:6000/scim/v2").rstrip("/")
    BEARER_TOKEN = os.getenv("SCIM_BEARER_TOKEN", "")
    CUSTOM_SCHEMA = os.getenv("OKTA_CUSTOM_SCHEMA", "urn:okta:sat:1.0:user:custom")

    ORACLE_USER = os.getenv("ORACLE_USER", "")
    ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "")
    ORACLE_DSN = os.getenv("ORACLE_DSN", "")
    ORACLE_THICK_MODE = _as_bool(os.getenv("ORACLE_THICK_MODE"), False)
    ORACLE_CLIENT_LIB_DIR = os.getenv("ORACLE_CLIENT_LIB_DIR", "").strip() or None

    SCIM_DEBUG = _as_bool(os.getenv("SCIM_DEBUG"), False)
    SCIM_LOG_LEVEL = os.getenv("SCIM_LOG_LEVEL", "DEBUG" if SCIM_DEBUG else "INFO").upper()
    SCIM_LOG_DIR = os.getenv("SCIM_LOG_DIR", "logs")
    SCIM_LOG_FILE = os.getenv("SCIM_LOG_FILE", "scim-server.log")
    SCIM_LOG_BACKUP_COUNT = max(1, int(os.getenv("SCIM_LOG_BACKUP_COUNT", "30")))
    SCIM_MAX_PAGE_SIZE = max(1, min(int(os.getenv("SCIM_MAX_PAGE_SIZE", "200")), 1000))
    SCIM_DEFAULT_PAGE_SIZE = max(1, min(int(os.getenv("SCIM_DEFAULT_PAGE_SIZE", "100")), SCIM_MAX_PAGE_SIZE))

    SAT_SCHEMA_OWNER = os.getenv("SAT_SCHEMA_OWNER", "COMSATCLPR")
    SAT_DEFAULT_INSTALAC = os.getenv("SAT_DEFAULT_INSTALAC", "SAT")
    SAT_DEFAULT_CODPERFIL = os.getenv("SAT_DEFAULT_CODPERFIL", "04")
    SAT_DEFAULT_CODPERFILEXT = os.getenv("SAT_DEFAULT_CODPERFILEXT", "E1")
    SAT_DEFAULT_CODENTUMO = os.getenv("SAT_DEFAULT_CODENTUMO", "0015")
    SAT_DEFAULT_CODOFIUMO = os.getenv("SAT_DEFAULT_CODOFIUMO", "0001")
    SAT_DEFAULT_USUARIOUMO = os.getenv("SAT_DEFAULT_USUARIOUMO", "SCIMSAT")
    SAT_DEFAULT_CODTERMUMO = os.getenv("SAT_DEFAULT_CODTERMUMO", "88888888")
    SAT_DEFAULT_PASSWORD_HASH = os.getenv(
        "SAT_DEFAULT_PASSWORD_HASH",
        "668d66d64fd48db423c4bae74b553cdc50f0925e4e7212bba2543031a74d49ae",
    )
    SAT_DEFAULT_FECFINCON = os.getenv("SAT_DEFAULT_FECFINCON", "9999-12-31")
    SAT_ACTIVE_FECBAJA = os.getenv("SAT_ACTIVE_FECBAJA", "0001-01-01")
    SAT_ACTIVE_FECFINCON = os.getenv("SAT_ACTIVE_FECFINCON", "9999-12-31")
    SAT_DEFAULT_NUMMAXCON = int(os.getenv("SAT_DEFAULT_NUMMAXCON", "3"))
    SAT_DEFAULT_VIGCONUSU = int(os.getenv("SAT_DEFAULT_VIGCONUSU", "90"))
    SAT_DEFAULT_NIVSEGUSU = os.getenv("SAT_DEFAULT_NIVSEGUSU", "0")
    SAT_DEFAULT_CODIDIOMA = os.getenv("SAT_DEFAULT_CODIDIOMA", "ES")
    SAT_DEFAULT_VERPAN = os.getenv("SAT_DEFAULT_VERPAN", "N")
    SAT_DEFAULT_OFICINA = os.getenv("SAT_DEFAULT_OFICINA", "8888")
    SAT_DEFAULT_CENTTRA = os.getenv("SAT_DEFAULT_CENTTRA", "            ")  # CHAR(12): 12 espacios en blanco
    SAT_DEFAULT_ROLE_CODE_IF_UNMAPPED = os.getenv("SAT_DEFAULT_ROLE_CODE_IF_UNMAPPED", "04")
    SAT_USERNAME_STRATEGY = os.getenv("SAT_USERNAME_STRATEGY", "extensionAttribute1")

    SAT_ROLES = {
        "01": {
            "code": "01",
            "name": "CONSULTA",
            "description": "Permite realizar consultas a contratos a través del front de SAT.",
        },
        "02": {
            "code": "02",
            "name": "OPERACIONES",
            "description": "Permite consultas y operaciones sobre cuentas a través del front de SAT.",
        },
        "04": {
            "code": "04",
            "name": "AUDITORIA",
            "description": "No tiene acceso al front de SAT; solo trazabilidad de mantenimientos vía Backoffice y Omni.",
        },
        "CU": {
            "code": "CU",
            "name": "GESTION USUARIOS",
            "description": "Administración de usuarios a través del front de SAT.",
        },
        "PT": {
            "code": "PT",
            "name": "PARAMETRIA",
            "description": "Permite parametrías de productos de tarjeta de crédito a través del front de SAT.",
        },
    }

    SAT_TITLE_ROLE_MAP = {
        "agente": "04",
        "cajero(a)": "04",
        "ejecutivo(a) integral": "04",
        "gerente de sucursales": "04",
        "gerente zonal": "04",
        "supervisor (a) de sucursal": "04",
        "tesorero": "04",
        "ejecutivo de atención de canales digitales": "04",
        "ejecutivo(a) banca telefonica": "04",
        "supervisor atencion canales digitales": "04",
        "supervisor banca telefonica": "04",
    }