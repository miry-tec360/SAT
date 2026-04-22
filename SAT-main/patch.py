from __future__ import annotations

from typing import Any, Dict, List

from logger_config import get_logger, safe_json

LOGGER = get_logger("patch")


class PatchError(ValueError):
    def __init__(self, detail: str, scim_type: str = "invalidSyntax") -> None:
        super().__init__(detail)
        self.scim_type = scim_type


def _normalize_path(path: str | None) -> str:
    return (path or "").strip()


def _extract_values(value: Any) -> List[str]:
    out: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                candidate = str(item.get("value") or item.get("display") or "").strip()
                if candidate:
                    out.append(candidate)
            else:
                candidate = str(item or "").strip()
                if candidate:
                    out.append(candidate)
    elif isinstance(value, dict):
        candidate = str(value.get("value") or value.get("display") or "").strip()
        if candidate:
            out.append(candidate)
    elif value is not None:
        candidate = str(value).strip()
        if candidate:
            out.append(candidate)
    return out


def _ensure_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise PatchError("Invalid boolean value in PATCH payload.", "invalidValue")


def _set_attr(result: Dict[str, Any], path: str, value: Any, custom_schema: str) -> None:
    normalized = path.lower()
    if normalized == "username":
        result["userName"] = str(value or "").strip()
    elif normalized in {"name.givenname", "givenname", "firstname"}:
        result["firstName"] = str(value or "").strip()
    elif normalized in {"name.familyname", "familyname", "lastname"}:
        result["lastName"] = str(value or "").strip()
    elif normalized == "active":
        result["active"] = _ensure_bool(value)
    elif normalized == "title":
        result["title"] = str(value or "").strip()
    elif normalized == "externalid":
        result["externalId"] = str(value or "").strip()
    elif normalized.endswith(".rut"):
        result["custom"]["rut"] = str(value or "").strip()
    elif normalized.endswith(".dv"):
        result["custom"]["dv"] = str(value or "").strip()
    elif normalized.endswith(".tipousuario"):
        result["custom"]["tipoUsuario"] = str(value or "").strip()
    elif normalized.endswith(".apellidomaterno"):
        result["custom"]["apellidoMaterno"] = str(value or "").strip()
    elif normalized.endswith(".codigoperfil"):
        result["custom"]["codigoPerfil"] = str(value or "").strip()
    elif normalized.endswith(".perfilnombre"):
        result["custom"]["perfilNombre"] = str(value or "").strip()
    elif normalized.endswith(".userstatus"):
        result["custom"]["userstatus"] = str(value or "").strip()
    else:
        raise PatchError(f"Unsupported PATCH path: {path}", "noTarget")


def apply_patch(current: Dict[str, Any], operations: List[Dict[str, Any]], custom_schema: str) -> Dict[str, Any]:
    result = dict(current)
    result.setdefault("custom", {})

    LOGGER.info("PATCH_REQUEST | current=%s | operations=%s", safe_json(current), safe_json(operations))

    if not isinstance(operations, list) or not operations:
        raise PatchError("PATCH request must include non-empty Operations array.")

    for op in operations:
        if not isinstance(op, dict):
            raise PatchError("Each PATCH operation must be an object.")
        operation = str(op.get("op") or "").strip().lower()
        path = _normalize_path(op.get("path"))
        value = op.get("value")
        if operation not in {"add", "replace", "remove"}:
            raise PatchError(f"Unsupported PATCH op: {operation}", "invalidSyntax")

        if operation in {"add", "replace"}:
            if not path:
                if not isinstance(value, dict):
                    raise PatchError("PATCH operation without path must include an object value.")
                if "userName" in value:
                    result["userName"] = str(value.get("userName") or "").strip()
                if "externalId" in value:
                    result["externalId"] = str(value.get("externalId") or "").strip()
                if "active" in value:
                    result["active"] = _ensure_bool(value.get("active"))
                if "title" in value:
                    result["title"] = str(value.get("title") or "").strip()
                name = value.get("name") or {}
                if isinstance(name, dict):
                    if "givenName" in name:
                        result["firstName"] = str(name.get("givenName") or "").strip()
                    if "familyName" in name:
                        result["lastName"] = str(name.get("familyName") or "").strip()
                custom = value.get(custom_schema) or {}
                if isinstance(custom, dict):
                    for key in ("rut", "dv", "tipoUsuario", "apellidoMaterno", "codigoPerfil", "perfilNombre", "userstatus"):
                        if key in custom:
                            result["custom"][key] = str(custom.get(key) or "").strip()
            else:
                _set_attr(result, path, value, custom_schema)
        else:
            if not path:
                raise PatchError("PATCH remove requires a path.", "noTarget")
            normalized = path.lower()
            if normalized == "title":
                result["title"] = ""
            elif normalized.endswith(".apellidomaterno"):
                result["custom"]["apellidoMaterno"] = ""
            elif normalized.endswith(".rut"):
                result["custom"]["rut"] = ""
            elif normalized.endswith(".tipousuario"):
                result["custom"]["tipoUsuario"] = ""
            elif normalized.endswith(".codigoperfil"):
                result["custom"]["codigoPerfil"] = ""
            else:
                raise PatchError(f"Unsupported PATCH path: {path}", "noTarget")

    LOGGER.info("PATCH_FINAL_RESULT | result=%s", safe_json(result))
    return result
