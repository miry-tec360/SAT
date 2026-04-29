# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any, Dict

from flask import Flask, g, jsonify, request

from config import Config
from db_sat import SatOracleRepo
from logger_config import get_logger, safe_json, sanitize_headers
from patch import PatchError, apply_patch
from schema import (
    SCIM_ERROR,
    SCIM_LIST_RESPONSE,
    resource_types,
    role_to_scim,
    schemas,
    service_provider_config,
    user_to_scim,
)

app = Flask(__name__)
repo = SatOracleRepo()
LOGGER = get_logger("app")


def parse_pagination():
    try:
        start_index = int(request.args.get("startIndex", 1))
        count = int(request.args.get("count", Config.SCIM_DEFAULT_PAGE_SIZE))
    except Exception:
        start_index = 1
        count = Config.SCIM_DEFAULT_PAGE_SIZE

    if start_index < 1:
        start_index = 1
    if count < 1:
        count = Config.SCIM_DEFAULT_PAGE_SIZE

    return start_index, min(count, Config.SCIM_MAX_PAGE_SIZE)


def parse_filter(filter_expr: str):
    try:
        parts = filter_expr.split(" eq ")
        if len(parts) != 2:
            return None, None
        attr = parts[0].strip()
        value = parts[1].strip().strip('"')
        return attr, value
    except Exception:
        return None, None


def list_response(resources, total, start_index, count):
    payload = {
        "schemas": [SCIM_LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }
    LOGGER.info(
        "SCIM_LIST_RESPONSE | total=%s | startIndex=%s | requestedCount=%s | returned=%s | body=%s",
        total, start_index, count, len(resources), safe_json(payload)
    )
    return jsonify(payload)


def scim_error(detail, status=400, scimType=None):
    err = {"schemas": [SCIM_ERROR], "detail": detail, "status": str(status)}
    if scimType:
        err["scimType"] = scimType

    log_level = LOGGER.error if status >= 500 else LOGGER.warning
    log_level("SCIM_ERROR | status=%s | scimType=%s | detail=%s", status, scimType, detail)
    return jsonify(err), status


def _error(message: str, status_code: int):
    payload = {"schemas": [SCIM_ERROR], "detail": message, "status": str(status_code)}
    log_level = LOGGER.error if status_code >= 500 else LOGGER.warning
    log_level("ERROR_RESPONSE | status=%s | detail=%s", status_code, message)
    return jsonify(payload), status_code


def _extract_primary_role(payload: Dict[str, Any]) -> str:
    roles = payload.get("roles") or []
    if not roles:
        return ""
    primary = next((r for r in roles if r.get("primary") is True), None)
    selected = primary or roles[0]
    return str(selected.get("value") or "").strip()


def _derive_names(payload: Dict[str, Any]) -> tuple:
    """
    Deriva firstName y lastName priorizando name.formatted sobre givenName/familyName.
    Esto resuelve el caso donde Okta envia el nombre actualizado en formatted
    pero givenName/familyName aun tienen el valor cacheado anterior.
    """
    name = payload.get("name") or {}
    formatted = str(name.get("formatted") or "").strip()
    given   = str(name.get("givenName")  or payload.get("firstName") or "").strip()
    family  = str(name.get("familyName") or payload.get("lastName")  or "").strip()
    # Strip adicional para limpiar padding CHAR de Oracle que puede venir en familyName
    family  = family.strip()

    # Si formatted tiene valor y difiere de la combinación givenName+familyName
    # usamos formatted como fuente de verdad
    if formatted:
        combined = f"{given} {family}".strip()
        if formatted != combined:
            # Usar familyName para lastName y derivar firstName desde formatted
            if family and formatted.upper().endswith(family.upper()):
                first = formatted[:-len(family)].strip()
                return first.upper(), family.upper()
            # Sin familyName: split simple
            parts = formatted.split(" ", 1)
            return parts[0].upper(), (parts[1].upper() if len(parts) > 1 else parts[0].upper())

    # formatted igual a givenName+familyName ? usar givenName/familyName directamente
    first = given or (formatted.split(" ", 1)[0] if formatted else "")
    last  = family or (formatted.split(" ", 1)[1] if formatted and " " in formatted else first)

    return first.upper(), last.upper()


def _extract_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    extension = payload.get(Config.CUSTOM_SCHEMA) or {}

    first_name, last_name = _derive_names(payload)

    role_from_roles = _extract_primary_role(payload)
    role_from_schema = str(extension.get("codigoPerfil") or payload.get("codigoPerfil") or "").strip()
    codigo_perfil = role_from_roles or role_from_schema

    data = {
        "userName": str(payload.get("userName") or "").strip(),
        "externalId": str(payload.get("externalId") or "").strip(),
        "firstName": first_name,
        "lastName": last_name,
        "title": str(payload.get("title") or "").strip(),
        "active": bool(payload.get("active", True)),
        "custom": {
            "rut": str(extension.get("rut") or payload.get("rut") or "").strip(),
            "dv": str(extension.get("dv") or payload.get("dv") or "").strip(),
            "tipoUsuario": str(extension.get("tipoUsuario") or payload.get("tipoUsuario") or "").strip(),
            "apellidoMaterno": str(extension.get("apellidoMaterno") or payload.get("apellidoMaterno") or "").strip(),
            "codigoPerfil": codigo_perfil,
            "perfilNombre": str(extension.get("perfilNombre") or payload.get("perfilNombre") or "").strip(),
            "userstatus": str(extension.get("userstatus") or payload.get("userstatus") or "").strip(),
        },
    }
    LOGGER.info(
        "PAYLOAD_NORMALIZED | input=%s | normalized=%s | role_source=%s",
        safe_json(payload), safe_json(data),
        "roles[]" if role_from_roles else "codigoPerfil",
    )
    return data


@app.before_request
def _log_request():
    g.start_time = time.time()
    request_id = request.headers.get("X-Request-Id") or request.headers.get("X-Okta-Request-Id")
    if not request_id:
        request_id = f"req-{int(g.start_time * 1000)}"
    g.request_id = request_id

    raw_body = request.get_data(cache=True, as_text=True)
    json_body = request.get_json(silent=True)
    body_for_log = json_body if json_body is not None else (raw_body if raw_body else None)

    LOGGER.info(
        "REQUEST_IN | request_id=%s | method=%s | path=%s | url=%s | remote_addr=%s | params=%s | headers=%s | body=%s",
        request_id,
        request.method,
        request.path,
        request.url,
        request.remote_addr,
        safe_json(dict(request.args)),
        safe_json(sanitize_headers(dict(request.headers))),
        safe_json(body_for_log),
    )


@app.before_request
def _require_token():
    if request.path in {"/healthz", "/"}:
        return None
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {Config.BEARER_TOKEN}"
    if not Config.BEARER_TOKEN:
        return _error("SCIM_BEARER_TOKEN no configurado.", 500)
    if auth != expected:
        return _error("Unauthorized", 401)
    return None


@app.after_request
def _log_response(response):
    duration_ms = round((time.time() - getattr(g, "start_time", time.time())) * 1000, 2)
    response_body = response.get_data(as_text=True)
    LOGGER.info(
        "RESPONSE_OUT | request_id=%s | status=%s | duration_ms=%s | headers=%s | body=%s",
        getattr(g, "request_id", "n/a"),
        response.status_code,
        duration_ms,
        safe_json(dict(response.headers)),
        response_body,
    )
    return response


@app.get("/")
def root():
    return jsonify({"service": "SAT SCIM 2.0", "status": "ok"})


@app.get("/healthz")
def healthz():
    try:
        payload = {"ok": repo.healthcheck()}
        return jsonify(payload)
    except Exception as exc:
        LOGGER.exception("HEALTHCHECK_ERROR")
        return jsonify({"ok": False, "error": str(exc)}), 503


@app.get("/scim/v2/ServiceProviderConfig")
def get_spc():
    return jsonify(service_provider_config())


@app.get("/scim/v2/ResourceTypes")
def get_resource_types():
    data = resource_types()
    payload = {
        "Resources": data,
        "totalResults": len(data),
        "itemsPerPage": len(data),
        "startIndex": 1,
        "schemas": [SCIM_LIST_RESPONSE],
    }
    return jsonify(payload)


@app.get("/scim/v2/Schemas")
def get_schemas():
    data = schemas()
    payload = {
        "Resources": data,
        "totalResults": len(data),
        "itemsPerPage": len(data),
        "startIndex": 1,
        "schemas": [SCIM_LIST_RESPONSE],
    }
    return jsonify(payload)


@app.get("/scim/v2/Groups")
def list_groups():
    payload = {
        "schemas": [SCIM_LIST_RESPONSE],
        "totalResults": 0,
        "startIndex": 1,
        "itemsPerPage": 0,
        "Resources": [],
    }
    return jsonify(payload)


@app.get("/scim/v2/Roles")
def list_roles():
    try:
        start_index, count = parse_pagination()
        filter_expr = request.args.get("filter", "").strip()

        if filter_expr:
            attr, value = parse_filter(filter_expr)
            if attr == "id":
                role = repo.get_role(value)
                resources = [role_to_scim(role, Config.BASE_URL)] if role else []
                return list_response(resources, len(resources), 1, len(resources))
            if attr == "displayName":
                rows, _ = repo.list_roles(1, Config.SCIM_MAX_PAGE_SIZE)
                matched = [role_to_scim(r, Config.BASE_URL) for r in rows if (r.get("name") or "").lower() == value.lower()]
                return list_response(matched, len(matched), 1, len(matched))
            return scim_error("Unsupported filter for Roles.", 400, "invalidFilter")

        rows, total = repo.list_roles(start_index, count)
        resources = [role_to_scim(r, Config.BASE_URL) for r in rows]
        return list_response(resources, total, start_index, count)
    except Exception as exc:
        LOGGER.exception("Error in GET /Roles")
        return scim_error(str(exc), 500)


@app.get("/scim/v2/Roles/<role_id>")
def get_role(role_id: str):
    role = repo.get_role(role_id)
    if not role:
        return _error("Role not found", 404)
    return jsonify(role_to_scim(role, Config.BASE_URL))


@app.get("/scim/v2/Users")
def list_users():
    try:
        filter_expr = request.args.get("filter", "").strip()
        start_index, count = parse_pagination()

        filter_attr = None
        filter_value = None
        if filter_expr:
            filter_attr, filter_value = parse_filter(filter_expr)
            if not filter_attr:
                return scim_error("Invalid filter syntax.", 400, "invalidFilter")

        rows, total = repo.list_users(start_index=start_index, count=count, filter_attr=filter_attr, filter_value=filter_value)
        resources = [user_to_scim(r, Config.BASE_URL) for r in rows]
        return list_response(resources, total if not filter_expr else len(resources), start_index, count)
    except ValueError as exc:
        return scim_error(str(exc), 400, "invalidFilter")
    except Exception as exc:
        LOGGER.exception("Error in GET /Users")
        return scim_error(str(exc), 500)


@app.get("/scim/v2/Users/<user_id>")
def get_user(user_id: str):
    user = repo.get_user(user_id)
    if not user:
        return _error("User not found", 404)
    return jsonify(user_to_scim(user, Config.BASE_URL))


def _nombre_completo(data: Dict[str, Any]) -> str:
    first = str(data.get("firstName") or "").strip()
    last  = str(data.get("lastName")  or "").strip()
    return f"{first} {last}".strip() or "SIN NOMBRE"


def _rol_display(data: Dict[str, Any]) -> str:
    custom = data.get("custom") or {}
    codigo = custom.get("codigoPerfil") or ""
    nombre = custom.get("perfilNombre") or (Config.SAT_ROLES.get(codigo, {}).get("name", "") if codigo else "")
    return f"{codigo} - {nombre}" if nombre else codigo or "SIN ROL"


def _estado_display(data: Dict[str, Any]) -> str:
    return "ACTIVO" if data.get("active", True) else "INACTIVO"


def _split_apellidos(data: Dict[str, Any]):
    """Deriva apell1 y apell2 igual que db_sat.py para mostrar en logs."""
    custom = data.get("custom") or {}
    apell1 = str(data.get("lastName") or "").strip()
    apell2 = str(custom.get("apellidoMaterno") or "").strip()
    if not apell2 and apell1 and " " in apell1:
        partes = apell1.split(" ", 1)
        apell1 = partes[0].strip()
        apell2 = partes[1].strip()
    return apell1, apell2


def _log_exito_alta(data: Dict[str, Any]) -> None:
    usuario = str(data.get("userName") or "").strip()
    nombre  = _nombre_completo(data)
    apell1, apell2 = _split_apellidos(data)
    rol     = _rol_display(data)
    estado  = _estado_display(data)
    from datetime import datetime
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        "\n========================================"
        "\nALTA DE USUARIO - EXITOSO"
        "\n========================================"
        "\nUsuario    : " + usuario +
        "\nNombre     : " + nombre +
        "\nApellido 1 : " + apell1 +
        "\nApellido 2 : " + apell2 +
        "\nRol        : " + rol +
        "\nEstado     : " + estado +
        "\nFecha      : " + fecha +
        "\n========================================"
    )
    LOGGER.info(msg)


def _log_exito_actualizacion(data: Dict[str, Any], usuario_id: str) -> None:
    nombre  = _nombre_completo(data)
    apell1, apell2 = _split_apellidos(data)
    rol     = _rol_display(data)
    estado  = _estado_display(data)
    from datetime import datetime
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        "\n========================================"
        "\nACTUALIZACION DE USUARIO - EXITOSO"
        "\n========================================"
        "\nUsuario    : " + usuario_id +
        "\nNombre     : " + nombre +
        "\nApellido 1 : " + apell1 +
        "\nApellido 2 : " + apell2 +
        "\nRol        : " + rol +
        "\nEstado     : " + estado +
        "\nFecha      : " + fecha +
        "\n========================================"
    )
    LOGGER.info(msg)


def _log_exito_baja(usuario_id: str, nombre: str) -> None:
    from datetime import datetime
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        "\n========================================"
        "\nBAJA DE USUARIO - EXITOSO"
        "\n========================================"
        "\nUsuario    : " + usuario_id +
        "\nNombre     : " + nombre +
        "\nEstado     : INACTIVO"
        "\nFecha      : " + fecha +
        "\n========================================"
    )
    LOGGER.info(msg)


def _log_error(operacion: str, usuario_id: str, motivo: str, accion: str) -> None:
    from datetime import datetime
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        "\n========================================"
        "\nERROR - " + operacion + " FALLIDO"
        "\n========================================"
        "\nUsuario    : " + usuario_id +
        "\nMotivo     : " + motivo +
        "\nAccion     : " + accion +
        "\nFecha      : " + fecha +
        "\n========================================"
    )
    LOGGER.error(msg)


@app.post("/scim/v2/Users")
def create_user():
    payload = request.get_json(force=True, silent=False) or {}
    data = _extract_payload(payload)
    usuario = data.get("userName") or ""
    try:
        user = repo.upsert_user(data)
        _log_exito_alta(data)
        return jsonify(user_to_scim(user, Config.BASE_URL)), 201
    except ValueError as exc:
        _log_error("ALTA", usuario, str(exc), "Verificar los datos del usuario en Okta antes de reasignar")
        return _error(str(exc), 400)
    except Exception as exc:
        _log_error("ALTA", usuario, f"Error inesperado: {str(exc)}", "Revisar logs tecnicos y contactar al administrador")
        LOGGER.exception("USER_CREATE_ERROR")
        return _error(str(exc), 500)


@app.put("/scim/v2/Users/<user_id>")
def replace_user(user_id: str):
    payload = request.get_json(force=True, silent=False) or {}
    data = _extract_payload(payload)
    data["userName"] = data.get("userName") or user_id
    try:
        user = repo.upsert_user(data)
        _log_exito_actualizacion(data, user_id)
        return jsonify(user_to_scim(user, Config.BASE_URL))
    except ValueError as exc:
        _log_error("ACTUALIZACION", user_id, str(exc), "Verificar los datos del usuario en Okta y reintentar")
        return _error(str(exc), 400)
    except Exception as exc:
        _log_error("ACTUALIZACION", user_id, f"Error inesperado: {str(exc)}", "Revisar logs tecnicos y contactar al administrador")
        LOGGER.exception("USER_REPLACE_ERROR")
        return _error(str(exc), 500)


@app.patch("/scim/v2/Users/<user_id>")
def patch_user(user_id: str):
    existing = repo.get_user(user_id)
    if not existing:
        _log_error("ACTUALIZACION", user_id, "Usuario no encontrado en SAT", "Verificar que el usuario exista en la BD antes de actualizar")
        return _error("User not found", 404)

    current = {
        "userName": existing["userName"],
        "externalId": existing["externalId"],
        "firstName": existing["firstName"],
        "lastName": existing["lastName"],
        "title": existing["title"],
        "active": existing["active"],
        "custom": existing["custom"],
    }
    payload = request.get_json(force=True, silent=False) or {}

    try:
        patched = apply_patch(current, payload.get("Operations") or [], Config.CUSTOM_SCHEMA)
        user = repo.upsert_user(patched)
        _log_exito_actualizacion(patched, user_id)
        return jsonify(user_to_scim(user, Config.BASE_URL))
    except PatchError as exc:
        _log_error("ACTUALIZACION", user_id, f"Operacion PATCH invalida: {str(exc)}", "Verificar el formato de la operacion enviada por Okta")
        return scim_error(str(exc), 400, exc.scim_type)
    except ValueError as exc:
        _log_error("ACTUALIZACION", user_id, str(exc), "Verificar los datos del usuario en Okta y reintentar")
        return _error(str(exc), 400)
    except Exception as exc:
        _log_error("ACTUALIZACION", user_id, f"Error inesperado: {str(exc)}", "Revisar logs tecnicos y contactar al administrador")
        LOGGER.exception("USER_PATCH_ERROR")
        return _error(str(exc), 500)


@app.delete("/scim/v2/Users/<user_id>")
def delete_user(user_id: str):
    try:
        existing = repo.get_user(user_id)
        nombre = _nombre_completo(existing) if existing else "SIN NOMBRE"
        repo.deactivate_user(user_id)
        _log_exito_baja(user_id, nombre)
        return "", 204
    except Exception as exc:
        _log_error("BAJA", user_id, f"Error inesperado: {str(exc)}", "Revisar logs tecnicos y contactar al administrador")
        LOGGER.exception("USER_DELETE_ERROR")
        return _error(str(exc), 500)


if __name__ == "__main__":
    LOGGER.info("APP_START | host=%s | port=%s | base_url=%s", Config.HOST, Config.PORT, Config.BASE_URL)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.SCIM_DEBUG)