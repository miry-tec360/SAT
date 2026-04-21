from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from stdnum.cl import rut as std_rut

from config import Config


def compact_spaces(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_upper(value: str | None) -> str:
    return compact_spaces(value).upper()


def split_last_names(last_name: str | None) -> Tuple[str, str]:
    normalized = normalize_upper(last_name)
    if not normalized:
        return "", ""
    parts = normalized.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _calc_dv(rut_digits: str) -> str:
    """Calcula el dígito verificador de un RUT chileno dado solo los dígitos."""
    reversed_digits = reversed(rut_digits)
    factors = [2, 3, 4, 5, 6, 7, 2, 3]
    total = sum(int(d) * f for d, f in zip(reversed_digits, factors))
    remainder = 11 - (total % 11)
    if remainder == 11:
        return "0"
    if remainder == 10:
        return "K"
    return str(remainder)


def validate_rut_dv(rut_str: str) -> tuple[str, str]:
    if not rut_str or not isinstance(rut_str, str):
        raise ValueError(f"RUT inválido: '{rut_str}'")

    cleaned = rut_str.strip().replace(".", "").replace(" ", "")

    # Si viene sin DV (solo dígitos), calcular el DV automáticamente
    if cleaned.isdigit():
        dv = _calc_dv(cleaned)
        return cleaned, dv

    # Si viene con DV (ej: "20905343-8" o "20905343K"), validar normalmente
    try:
        compact = std_rut.compact(cleaned)
        validated = std_rut.validate(compact)
    except Exception as exc:
        raise ValueError(f"RUT inválido o DV incorrecto: '{rut_str}'") from exc
    rut = validated[:-1]
    dv = validated[-1].upper()
    return rut, dv


def normalize_title(title: str | None) -> str:
    return compact_spaces(title).lower()


def role_code_from_title(title: str | None) -> str:
    normalized = normalize_title(title)
    if not normalized:
        return Config.SAT_DEFAULT_ROLE_CODE_IF_UNMAPPED
    return Config.SAT_TITLE_ROLE_MAP.get(normalized, Config.SAT_DEFAULT_ROLE_CODE_IF_UNMAPPED)


def role_record_from_code(code: str | None) -> Dict[str, Any]:
    selected = Config.SAT_ROLES.get(str(code or "").strip().upper())
    if selected:
        return selected
    return Config.SAT_ROLES[Config.SAT_DEFAULT_ROLE_CODE_IF_UNMAPPED]


def derive_sat_username(
    *,
    user_name: str | None,
    external_id: str | None,
    rut_value: str | None,
    tipo_usuario: str | None,
) -> str:
    """
    Regla práctica:
    - si llega extension/custom con rut -> usa RUT sin DV
    - si tipoUsuario sugiere casa matriz y no hay RUT -> usa login antes de @ en mayúsculas
    - fallback: userName completo en mayúsculas
    """
    tipo = normalize_title(tipo_usuario)
    if rut_value:
        rut, _ = validate_rut_dv(rut_value)
        return rut

    source = str(external_id or "").strip()
    if not source:
        source = str(user_name or "").strip()

    if not source:
        raise ValueError("No fue posible derivar USUARIO para SAT. Debes enviar rut o userName/externalId.")

    if "matriz" in tipo or "casa matriz" in tipo:
        return source.split("@", 1)[0].upper()

    if "@" in source:
        return source.split("@", 1)[0].upper()

    return source.upper()