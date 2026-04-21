from __future__ import annotations

from typing import Any, Dict, List

from config import Config

SCIM_CORE_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCIM_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
SCIM_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCIM_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
OKTA_ROLE_SCHEMA = "urn:okta:scim:schemas:core:1.0:Role"
SCIM_SPC = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"


def _schema_attr(
    name: str,
    attr_type: str,
    *,
    multi_valued: bool = False,
    required: bool = False,
    case_exact: bool = False,
    mutability: str = "readWrite",
    returned: str = "default",
    uniqueness: str = "none",
    sub_attributes: List[Dict[str, Any]] | None = None,
    reference_types: List[str] | None = None,
) -> Dict[str, Any]:
    attr: Dict[str, Any] = {
        "name": name,
        "type": attr_type,
        "multiValued": multi_valued,
        "required": required,
        "caseExact": case_exact,
        "mutability": mutability,
        "returned": returned,
        "uniqueness": uniqueness,
    }
    if sub_attributes is not None:
        attr["subAttributes"] = sub_attributes
    if reference_types is not None:
        attr["referenceTypes"] = reference_types
    return attr


def service_provider_config() -> Dict[str, Any]:
    return {
        "schemas": [SCIM_SPC],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": Config.SCIM_MAX_PAGE_SIZE},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Static bearer token for Okta Provisioning Agent",
                "specUri": "https://datatracker.ietf.org/doc/html/rfc6750",
                "primary": True,
            }
        ],
    }


def schemas() -> List[Dict[str, Any]]:
    return [
        {
            "schemas": [SCIM_SCHEMA],
            "id": SCIM_CORE_USER,
            "name": "User",
            "description": "Core SCIM User",
            "attributes": [
                _schema_attr("userName", "string", required=True, returned="always", uniqueness="server"),
                _schema_attr("externalId", "string"),
                _schema_attr(
                    "name",
                    "complex",
                    sub_attributes=[
                        _schema_attr("givenName", "string"),
                        _schema_attr("familyName", "string"),
                    ],
                ),
                _schema_attr("title", "string"),
                _schema_attr("active", "boolean"),
            ],
            "meta": {"resourceType": "Schema", "location": f"{Config.BASE_URL}/Schemas/{SCIM_CORE_USER}"},
        },
        {
            "schemas": [SCIM_SCHEMA],
            "id": Config.CUSTOM_SCHEMA,
            "name": "SATUserProfile",
            "description": "Custom schema aligned to SAT legacy model",
            "attributes": [
                _schema_attr("rut", "string"),
                _schema_attr("dv", "string", mutability="readOnly"),
                _schema_attr("tipoUsuario", "string"),
                _schema_attr("apellidoMaterno", "string"),
                _schema_attr("codigoPerfil", "string"),
                _schema_attr("perfilNombre", "string", mutability="readOnly"),
                _schema_attr("userstatus", "string"),
            ],
            "meta": {"resourceType": "Schema", "location": f"{Config.BASE_URL}/Schemas/{Config.CUSTOM_SCHEMA}"},
        },
        {
            "schemas": [SCIM_SCHEMA],
            "id": OKTA_ROLE_SCHEMA,
            "name": "Role",
            "description": "SAT role catalog for Okta import",
            "attributes": [
                _schema_attr("displayName", "string", required=True, mutability="readOnly", returned="always"),
                _schema_attr("description", "string", mutability="readOnly"),
                _schema_attr("externalId", "string", mutability="readOnly"),
            ],
            "meta": {"resourceType": "Schema", "location": f"{Config.BASE_URL}/Schemas/{OKTA_ROLE_SCHEMA}"},
        },
    ]


def resource_types() -> List[Dict[str, Any]]:
    return [
        {
            "schemas": [SCIM_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "description": "SAT users",
            "schema": SCIM_CORE_USER,
            "schemaExtensions": [{"schema": Config.CUSTOM_SCHEMA, "required": False}],
        },
        {
            "schemas": [SCIM_RESOURCE_TYPE],
            "id": "Role",
            "name": "Role",
            "endpoint": "/Roles",
            "description": "SAT role catalog",
            "schema": OKTA_ROLE_SCHEMA,
        },
    ]


def role_to_scim(role: Dict[str, Any], base_url: str, endpoint: str = "Roles") -> Dict[str, Any]:
    role_id = str(role["code"])
    return {
        "schemas": [OKTA_ROLE_SCHEMA],
        "id": role_id,
        "externalId": role_id,
        "displayName": role.get("name"),
        "description": role.get("description"),
        "meta": {"resourceType": "Role", "location": f"{base_url}/{endpoint}/{role_id}"},
    }


def user_to_scim(user: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    custom = user.get("custom", {})
    role_code = custom.get("codigoPerfil") or Config.SAT_DEFAULT_CODPERFIL
    profile_name = custom.get("perfilNombre") or Config.SAT_ROLES.get(role_code, {}).get("name", "")
    return {
        "schemas": [SCIM_CORE_USER, Config.CUSTOM_SCHEMA],
        "id": str(user["id"]),
        "externalId": str(user.get("externalId") or user["id"]),
        "userName": user.get("userName"),
        "active": bool(user.get("active", True)),
        "name": {
            "givenName": user.get("firstName"),
            "familyName": user.get("lastName"),
        },
        "title": user.get("title"),
        "roles": [
            {
                "value": role_code,
                "display": profile_name,
                "type": "perfilNombre",
                "primary": True,
            }
        ] if role_code else [],
        Config.CUSTOM_SCHEMA: {
            "rut": custom.get("rut"),
            "dv": custom.get("dv"),
            "tipoUsuario": custom.get("tipoUsuario"),
            "apellidoMaterno": custom.get("apellidoMaterno"),
            "codigoPerfil": role_code,
            "perfilNombre": profile_name,
            "userstatus": custom.get("userstatus") or ("activo" if user.get("active", True) else "inactivo"),
        },
        "meta": {"resourceType": "User", "location": f"{base_url}/Users/{user['id']}"},
    }
