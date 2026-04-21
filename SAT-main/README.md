# SAT SCIM 2.0 Server

Servidor SCIM 2.0 para la integración entre **Okta** y la aplicación legada **SAT** (Sistema de Administración de Tarjetas) de Falabella. Implementado en Python/Flask con backend Oracle, expone los endpoints necesarios para el aprovisionamiento automático de usuarios y roles desde Okta hacia SAT.

---

## Arquitectura general

```
Okta (Identity Provider)
        │
        │  SCIM 2.0 over HTTPS
        │  Bearer Token Auth
        ▼
SAT SCIM 2.0 Server  (Flask, puerto 6000)
        │
        │  oracledb
        ▼
Oracle DB  (schema: COMSATCLPR)
  ├── SGDT947   ← tabla de usuarios
  └── SGDT958   ← tabla de perfiles/roles
```

---

## Características

- Autenticación por Bearer Token estático
- Paginación SCIM (`startIndex` + `count`)
- Filtrado por `userName` y `externalId`
- Custom schema `urn:okta:sat:1.0:user:custom` con atributos SAT
- Roles hardcodeados + mapeados desde BD Oracle
- Validación de RUT chileno via `python-stdnum`
- Logging estructurado rotativo por día
- Upsert de usuarios contra `SGDT947`
- Gestión de perfil contra `SGDT958`
- Baja lógica en DELETE (no elimina físicamente)
- Respuesta `roles[]` compatible con Okta Import

---

## Roles disponibles

| Código | Nombre            | Descripción                                                                 |
|--------|-------------------|-----------------------------------------------------------------------------|
| `01`   | CONSULTA          | Permite consultas a contratos vía front SAT                                 |
| `02`   | OPERACIONES       | Permite consultas y operaciones sobre cuentas vía front SAT                 |
| `04`   | AUDITORIA         | Sin acceso al front SAT; solo trazabilidad vía Backoffice y Omni            |
| `CU`   | GESTION USUARIOS  | Administración de usuarios vía front SAT                                    |
| `PT`   | PARAMETRIA        | Parametrías de productos de tarjeta de crédito vía front SAT                |

El rol se deriva del atributo `title` del usuario en Okta usando la tabla `SAT_TITLE_ROLE_MAP`. Si no hay match, se aplica el código por defecto `04` (AUDITORIA).

---

## Custom schema

Namespace: `urn:okta:sat:1.0:user:custom`

| Atributo        | Tipo   | Mutabilidad | Descripción                        |
|-----------------|--------|-------------|-------------------------------------|
| `rut`           | string | readWrite   | RUT sin dígito verificador          |
| `dv`            | string | readOnly    | Dígito verificador (puede ser null) |
| `tipoUsuario`   | string | readWrite   | Tipo de usuario (sucursal/casa matriz) |
| `apellidoMaterno` | string | readWrite | Apellido materno                   |
| `codigoPerfil`  | string | readWrite   | Código de rol SAT                   |
| `perfilNombre`  | string | readOnly    | Nombre del rol SAT                  |
| `userstatus`    | string | readWrite   | Estado: `activo` / `inactivo`       |

---

## Endpoints

| Método   | Ruta                              | Descripción                          |
|----------|-----------------------------------|--------------------------------------|
| `GET`    | `/`                               | Health check básico                  |
| `GET`    | `/healthz`                        | Verifica conexión a Oracle           |
| `GET`    | `/scim/v2/ServiceProviderConfig`  | Capacidades del servidor SCIM        |
| `GET`    | `/scim/v2/Schemas`                | Esquemas soportados                  |
| `GET`    | `/scim/v2/ResourceTypes`          | Tipos de recursos                    |
| `GET`    | `/scim/v2/Roles`                  | Lista todos los roles                |
| `GET`    | `/scim/v2/Roles/{id}`             | Obtiene un rol por código            |
| `GET`    | `/scim/v2/Users`                  | Lista usuarios con paginación/filtro |
| `GET`    | `/scim/v2/Users/{id}`             | Obtiene un usuario por RUT           |
| `POST`   | `/scim/v2/Users`                  | Crea o actualiza un usuario          |
| `PUT`    | `/scim/v2/Users/{id}`             | Reemplaza un usuario completo        |
| `PATCH`  | `/scim/v2/Users/{id}`             | Actualiza atributos específicos      |
| `DELETE` | `/scim/v2/Users/{id}`             | Baja lógica del usuario              |

---

## Instalación

### Requisitos previos

- Python 3.10+
- Oracle Instant Client (si `ORACLE_THICK_MODE=true`)
- Acceso a la base de datos Oracle de SAT

### Pasos

```bash
# 1. Clonar el repositorio
git clone <repo_url>
cd sat-scim-server

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con los valores reales

# 5. Iniciar el servidor
python app.py
```

---

## Variables de entorno

### Servidor

| Variable              | Valor por defecto | Descripción                          |
|-----------------------|-------------------|--------------------------------------|
| `SCIM_HOST`           | `0.0.0.0`         | Interfaz de escucha                  |
| `SCIM_PORT`           | `6000`            | Puerto del servidor                  |
| `SCIM_BASE_URL`       | `http://localhost:6000/scim/v2` | URL base pública          |
| `SCIM_BEARER_TOKEN`   | *(requerido)*     | Token de autenticación               |
| `SCIM_DEBUG`          | `false`           | Modo debug Flask                     |
| `SCIM_LOG_LEVEL`      | `INFO`            | Nivel de log (`DEBUG`, `INFO`, etc.) |
| `SCIM_MAX_PAGE_SIZE`  | `200`             | Máximo de resultados por página      |

### Oracle

| Variable                | Descripción                              |
|-------------------------|------------------------------------------|
| `ORACLE_USER`           | Usuario de base de datos                 |
| `ORACLE_PASSWORD`       | Contraseña de base de datos              |
| `ORACLE_DSN`            | DSN de conexión (host:port/service)      |
| `ORACLE_THICK_MODE`     | `true` si se usa Oracle Instant Client   |
| `ORACLE_CLIENT_LIB_DIR` | Ruta al Oracle Instant Client (si aplica)|

### SAT

| Variable                        | Valor por defecto | Descripción                              |
|---------------------------------|-------------------|------------------------------------------|
| `SAT_SCHEMA_OWNER`              | `COMSATCLPR`      | Schema Oracle de SAT                     |
| `SAT_DEFAULT_CODPERFIL`         | `04`              | Perfil por defecto                       |
| `SAT_DEFAULT_ROLE_CODE_IF_UNMAPPED` | `04`          | Rol si no hay match por título           |
| `SAT_DEFAULT_INSTALAC`          | `SAT`             | Instalación SAT por defecto              |
| `SAT_ACTIVE_FECBAJA`            | `0001-01-01`      | Fecha baja para usuarios activos         |
| `SAT_DEFAULT_FECFINCON`         | `9999-12-31`      | Fecha fin de contrato por defecto        |

---

## Lógica de derivación de usuario SAT

La función `derive_sat_username()` en `sat_utils.py` determina el `USUARIO` que se almacena en SAT según esta prioridad:

1. Si viene `rut` en el custom schema → usa el RUT sin DV
2. Si `tipoUsuario` contiene "casa matriz" y no hay RUT → usa la parte antes del `@` del login, en mayúsculas
3. Si el `userName` o `externalId` contiene `@` → usa la parte antes del `@`, en mayúsculas
4. Fallback → `userName` completo en mayúsculas

---

## Ejemplo de payload de creación de usuario

```json
{
  "schemas": [
    "urn:ietf:params:scim:schemas:core:2.0:User",
    "urn:okta:sat:1.0:user:custom"
  ],
  "userName": "johann.valenzuela@falabella.cl",
  "externalId": "00u124zrn4kWTedzg698",
  "active": true,
  "name": {
    "givenName": "JOHANN",
    "familyName": "VALENZUELA"
  },
  "title": "AUDITORIA",
  "urn:okta:sat:1.0:user:custom": {
    "rut": "20905343",
    "tipoUsuario": "Sucursal",
    "apellidoMaterno": "GARRIDO",
    "codigoPerfil": "04",
    "perfilNombre": "AUDITORIA",
    "userstatus": "activo"
  }
}
```

---

## Ejemplo de respuesta GET /Users

```json
{
  "schemas": [
    "urn:ietf:params:scim:schemas:core:2.0:User",
    "urn:okta:sat:1.0:user:custom"
  ],
  "id": "20905343",
  "externalId": "00u124zrn4kWTedzg698",
  "userName": "20905343",
  "active": true,
  "name": {
    "givenName": "JOHANN",
    "familyName": "VALENZUELA"
  },
  "title": "AUDITORIA",
  "roles": [
    {
      "value": "04",
      "display": "AUDITORIA",
      "type": "perfilNombre",
      "primary": true
    }
  ],
  "urn:okta:sat:1.0:user:custom": {
    "rut": "20905343",
    "dv": null,
    "tipoUsuario": null,
    "apellidoMaterno": "GARRIDO",
    "codigoPerfil": "04",
    "perfilNombre": "AUDITORIA",
    "userstatus": "activo"
  }
}
```

---

## Logging

Los logs se escriben en `logs/scim-server.log` con rotación diaria. Cada entrada incluye:

- `REQUEST_IN` — request entrante con headers sanitizados y body
- `PAYLOAD_NORMALIZED` — payload normalizado internamente
- `SCIM_LIST_RESPONSE` — respuestas de listado
- `PATCH_REQUEST` / `PATCH_FINAL_RESULT` — operaciones PATCH
- `ERROR_RESPONSE` / `SCIM_ERROR` — errores con status y detalle
- `RESPONSE_OUT` — respuesta saliente con duración en ms

El campo `Authorization` se enmascara automáticamente como `***MASKED***` en todos los logs.

---

## Tablas Oracle involucradas

| Tabla     | Descripción                              |
|-----------|------------------------------------------|
| `SGDT947` | Tabla principal de usuarios SAT          |
| `SGDT958` | Tabla de perfiles/roles por usuario      |

---

## Consideraciones para producción

- Confirmar que `SGDT947` tiene todas las columnas usadas en el insert
- Validar si `CODPERFILEXT` debe variar según `CODPERFIL`
- Revisar si se necesita soporte de filtro por atributos adicionales
- Confirmar comportamiento de `USUARIO` para tipos distintos de sucursal
- Probar siempre en ambiente QA antes de ejecutar contra productivo
- Rotar el `SCIM_BEARER_TOKEN` periódicamente y actualizarlo en Okta

---

## Dependencias principales

| Paquete           | Versión  | Uso                              |
|-------------------|----------|----------------------------------|
| `flask`           | 3.0.3    | Framework web                    |
| `oracledb`        | 2.2.1    | Conexión a Oracle                |
| `python-dotenv`   | 1.0.1    | Variables de entorno desde `.env`|
| `python-stdnum`   | 1.20     | Validación de RUT chileno        |