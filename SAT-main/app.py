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


def _extract_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    extension = payload.get(Config.CUSTOM_SCHEMA) or {}
    name = payload.get("name") or {}
    data = {
        "userName": str(payload.get("userName") or "").strip(),
        "externalId": str(payload.get("externalId") or "").strip(),
        "firstName": str(name.get("givenName") or payload.get("firstName") or "").strip(),
        "lastName": str(name.get("familyName") or payload.get("lastName") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "active": bool(payload.get("active", True)),
        "custom": {
            "rut": str(extension.get("rut") or payload.get("rut") or "").strip(),
            "dv": str(extension.get("dv") or payload.get("dv") or "").strip(),
            "tipoUsuario": str(extension.get("tipoUsuario") or payload.get("tipoUsuario") or "").strip(),
            "apellidoMaterno": str(extension.get("apellidoMaterno") or payload.get("apellidoMaterno") or "").strip(),
            "codigoPerfil": str(extension.get("codigoPerfil") or payload.get("codigoPerfil") or "").strip(),
            "perfilNombre": str(extension.get("perfilNombre") or payload.get("perfilNombre") or "").strip(),
            "userstatus": str(extension.get("userstatus") or payload.get("userstatus") or "").strip(),
        },
    }
    LOGGER.info("PAYLOAD_NORMALIZED | input=%s | normalized=%s", safe_json(payload), safe_json(data))
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


@app.post("/scim/v2/Users")
def create_user():
    payload = request.get_json(force=True, silent=False) or {}
    data = _extract_payload(payload)
    try:
        user = repo.upsert_user(data)
        return jsonify(user_to_scim(user, Config.BASE_URL)), 201
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        LOGGER.exception("USER_CREATE_ERROR")
        return _error(str(exc), 500)


@app.put("/scim/v2/Users/<user_id>")
def replace_user(user_id: str):
    payload = request.get_json(force=True, silent=False) or {}
    data = _extract_payload(payload)
    data["userName"] = data.get("userName") or user_id
    try:
        user = repo.upsert_user(data)
        return jsonify(user_to_scim(user, Config.BASE_URL))
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        LOGGER.exception("USER_REPLACE_ERROR")
        return _error(str(exc), 500)


@app.patch("/scim/v2/Users/<user_id>")
def patch_user(user_id: str):
    existing = repo.get_user(user_id)
    if not existing:
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
        return jsonify(user_to_scim(user, Config.BASE_URL))
    except PatchError as exc:
        return scim_error(str(exc), 400, exc.scim_type)
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception as exc:
        LOGGER.exception("USER_PATCH_ERROR")
        return _error(str(exc), 500)


@app.delete("/scim/v2/Users/<user_id>")
def delete_user(user_id: str):
    try:
        repo.deactivate_user(user_id)
        return "", 204
    except Exception as exc:
        LOGGER.exception("USER_DELETE_ERROR")
        return _error(str(exc), 500)


if __name__ == "__main__":
    LOGGER.info("APP_START | host=%s | port=%s | base_url=%s", Config.HOST, Config.PORT, Config.BASE_URL)
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.SCIM_DEBUG)