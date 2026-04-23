from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import oracledb

from config import Config
from logger_config import get_logger, safe_json, sanitize_binds
from sat_utils import derive_sat_username, normalize_upper, role_code_from_title, role_record_from_code, split_last_names, validate_rut_dv

LOGGER = get_logger("db")


class SatOracleRepo:
    def __init__(self) -> None:
        self._thick_initialized = False
        if Config.ORACLE_THICK_MODE and Config.ORACLE_CLIENT_LIB_DIR:
            oracledb.init_oracle_client(lib_dir=Config.ORACLE_CLIENT_LIB_DIR)
            self._thick_initialized = True
            LOGGER.info("ORACLE_CLIENT_INIT | thick_mode=true | lib_dir=%s", Config.ORACLE_CLIENT_LIB_DIR)
        else:
            LOGGER.info("ORACLE_CLIENT_INIT | thick_mode=false")

    @property
    def table_947(self) -> str:
        return f'{Config.SAT_SCHEMA_OWNER}.SGDT947'

    @property
    def table_958(self) -> str:
        return f'{Config.SAT_SCHEMA_OWNER}.SGDT958'

    def _connect(self):
        LOGGER.info("ORACLE_CONNECT | dsn=%s | user=%s", Config.ORACLE_DSN, Config.ORACLE_USER)
        return oracledb.connect(
            user=Config.ORACLE_USER,
            password=Config.ORACLE_PASSWORD,
            dsn=Config.ORACLE_DSN,
        )

    @staticmethod
    def _row_to_dict(cursor, row) -> Dict[str, Any]:
        return {d[0]: row[i] for i, d in enumerate(cursor.description)}

    @staticmethod
    def _log_sql(sql: str, binds: Dict[str, Any] | None = None) -> None:
        LOGGER.info(
            "SQL_EXECUTE | sql=%s | binds=%s",
            " ".join(line.strip() for line in sql.strip().splitlines()),
            safe_json(sanitize_binds(binds)),
        )

    def _fetch_one(self, sql: str, binds: Dict[str, Any] | None = None) -> Optional[Dict[str, Any]]:
        self._log_sql(sql, binds)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, binds or {})
            row = cur.fetchone()
            return self._row_to_dict(cur, row) if row else None

    def _fetch_all(self, sql: str, binds: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        self._log_sql(sql, binds)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, binds or {})
            return [self._row_to_dict(cur, row) for row in cur.fetchall()]

    def healthcheck(self) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("select 1 from dual")
            row = cur.fetchone()
            ok = bool(row and row[0] == 1)
            LOGGER.info("HEALTHCHECK_DB | ok=%s", ok)
            return ok

    def list_roles(self, start_index: int = 1, count: int = Config.SCIM_DEFAULT_PAGE_SIZE) -> Tuple[List[Dict[str, Any]], int]:
        values = list(Config.SAT_ROLES.values())
        total = len(values)
        offset = max(start_index - 1, 0)
        limit = offset + max(1, min(count, Config.SCIM_MAX_PAGE_SIZE))
        return values[offset:limit], total

    def get_role(self, role_id: str) -> Optional[Dict[str, Any]]:
        return Config.SAT_ROLES.get(str(role_id or "").strip().upper())

    def _build_scim_user_model(self, row_947: Dict[str, Any], row_958: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        role_code = (row_958 or {}).get("CODPERFIL") or Config.SAT_DEFAULT_CODPERFIL
        role_info = role_record_from_code(role_code)
        fec_baja = str(row_947.get("FECBAJA") or "")
        active = fec_baja == Config.SAT_ACTIVE_FECBAJA or fec_baja == ""
        last_name = " ".join(x for x in [row_947.get("APELL1USU"), row_947.get("APELL2USU")] if x).strip()
        username_api = str(row_947.get("USERNAMEAPI") or "").strip()
        dv = ""
        if username_api:
            try:
                rut, dv = validate_rut_dv(username_api) if "-" in username_api else (re.sub(r"\D", "", username_api), "")
            except Exception:
                rut = re.sub(r"\D", "", username_api)
        else:
            rut = re.sub(r"\D", "", str(row_947.get("USUARIO") or ""))

        return {
            "id": str(row_947["USUARIO"]),
            "externalId": str(row_947.get("USUARIO")),
            "userName": str(row_947.get("USUARIO")),
            "firstName": row_947.get("NOMBREUSU"),
            "lastName": row_947.get("APELL1USU") or "",
            "title": role_info["name"],
            "active": active,
            "custom": {
                "rut": rut or None,
                "dv": dv or None,
                "tipoUsuario": row_947.get("TIPOUSUARIO") if "TIPOUSUARIO" in row_947 else None,
                "apellidoMaterno": row_947.get("APELL2USU") or "",
                "codigoPerfil": role_code,
                "perfilNombre": role_info["name"],
                "userstatus": "activo" if active else "inactivo",
            },
        }

    def get_user(self, usuario: str) -> Optional[Dict[str, Any]]:
        sql_947 = f"""
            SELECT USUARIO, NOMBREUSU, APELL1USU, APELL2USU, FECBAJA
            FROM {self.table_947}
            WHERE USUARIO = :usuario
        """
        row_947 = self._fetch_one(sql_947, {"usuario": usuario})
        if not row_947:
            return None

        sql_958 = f"""
            SELECT USUARIO, INSTALAC, CODPERFIL, CODPERFILEXT, FECALTA, FECBAJA
            FROM {self.table_958}
            WHERE USUARIO = :usuario
              AND INSTALAC = :instalac
            ORDER BY FECALTA DESC
        """
        rows_958 = self._fetch_all(sql_958, {"usuario": usuario, "instalac": Config.SAT_DEFAULT_INSTALAC})
        row_958 = rows_958[0] if rows_958 else None
        return self._build_scim_user_model(row_947, row_958)

    def list_users(self, start_index: int = 1, count: int = Config.SCIM_DEFAULT_PAGE_SIZE, filter_attr: str | None = None, filter_value: str | None = None) -> Tuple[List[Dict[str, Any]], int]:
        start_index = max(1, int(start_index))
        count = max(1, min(int(count), Config.SCIM_MAX_PAGE_SIZE))
        offset = start_index - 1

        base_where = ""
        binds: Dict[str, Any] = {}

        if filter_attr and filter_value:
            if filter_attr == "userName":
                base_where = "WHERE u.USUARIO = :filter_value"
                binds["filter_value"] = filter_value
            else:
                raise ValueError(f"Unsupported filter for Users: {filter_attr}")

        sql_count = f"""
            SELECT COUNT(1) AS TOTAL
            FROM (
                SELECT u.USUARIO
                FROM {self.table_947} u
                {base_where}
            )
        """

        sql_page = f"""
            SELECT * FROM (
                SELECT q.*, ROW_NUMBER() OVER (ORDER BY q.USUARIO) AS RN
                FROM (
                    SELECT u.USUARIO, u.NOMBREUSU, u.APELL1USU, u.APELL2USU, u.FECBAJA
                    FROM {self.table_947} u
                    {base_where}
                ) q
            )
            WHERE RN > :offset AND RN <= :limit
        """
        total_row = self._fetch_one(sql_count, binds)
        page_binds = dict(binds)
        page_binds["offset"] = offset
        page_binds["limit"] = offset + count
        rows_947 = self._fetch_all(sql_page, page_binds)

        resources = []
        for row_947 in rows_947:
            sql_958 = f"""
                SELECT USUARIO, INSTALAC, CODPERFIL, CODPERFILEXT, FECALTA, FECBAJA
                FROM {self.table_958}
                WHERE USUARIO = :usuario
                  AND INSTALAC = :instalac
                ORDER BY FECALTA DESC
            """
            rows_958 = self._fetch_all(sql_958, {"usuario": row_947["USUARIO"], "instalac": Config.SAT_DEFAULT_INSTALAC})
            row_958 = rows_958[0] if rows_958 else None
            resources.append(self._build_scim_user_model(row_947, row_958))

        total = int(total_row["TOTAL"] if total_row else 0)
        return resources, total

    def _insert_947(self, cur, *, usuario: str, first_name: str, apellido1: str, apellido2: str) -> None:
        sql = f"""
            INSERT INTO {self.table_947} (
                USUARIO, CODPERFIL, NOMBREUSU, APELL1USU, APELL2USU, PASSWORDD, FECINICON,
                FECFINCON, INDCONADM, CONTADOR, NUMMAXCON, VIGCONUSU, NIVSEGUSU, CODIDIOMA,
                FECACTIVA, FECDESACT, FECALTA, FECBAJA, FECULTMOD, CENTTRA, OFICINA, VERPAN,
                CODENTUMO, CODOFIUMO, USUARIOUMO, CODTERMUMO, CONTCUR
            ) VALUES (
                :usuario, '  ', :nombre, :apellido1, :apellido2, :passwordd, TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                :fecfincon, 'N', 0, :nummaxcon, :vigconusu, :nivsegusu, :codidioma,
                TO_CHAR(SYSDATE,'YYYY-MM-DD'), :fecfincon, TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                :fecbaja_activa, TO_CHAR(SYSDATE,'YYYY-MM-DD'), :centtra, :oficina, :verpan,
                :codentumo, :codofi, :usuarioumo, :codtermumo,
                TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
            )
        """
        binds = {
            "usuario": usuario,
            "nombre": first_name,
            "apellido1": apellido1,
            "apellido2": apellido2,
            "passwordd": Config.SAT_DEFAULT_PASSWORD_HASH,
            "fecfincon": Config.SAT_DEFAULT_FECFINCON,
            "nummaxcon": Config.SAT_DEFAULT_NUMMAXCON,
            "vigconusu": Config.SAT_DEFAULT_VIGCONUSU,
            "nivsegusu": Config.SAT_DEFAULT_NIVSEGUSU,
            "codidioma": Config.SAT_DEFAULT_CODIDIOMA,
            "fecbaja_activa": Config.SAT_ACTIVE_FECBAJA,
            "centtra": Config.SAT_DEFAULT_CENTTRA,
            "oficina": Config.SAT_DEFAULT_OFICINA,
            "verpan": Config.SAT_DEFAULT_VERPAN,
            "codentumo": Config.SAT_DEFAULT_CODENTUMO,
            "codofi": Config.SAT_DEFAULT_CODOFIUMO,
            "usuarioumo": Config.SAT_DEFAULT_USUARIOUMO,
            "codtermumo": Config.SAT_DEFAULT_CODTERMUMO,
        }
        self._log_sql(sql, binds)
        cur.execute(sql, binds)

    def _update_947(self, cur, *, usuario: str, first_name: str, apellido1: str, apellido2: str, active: bool) -> None:
        sql = f"""
            UPDATE {self.table_947}
               SET NOMBREUSU = :nombre,
                   APELL1USU = :apellido1,
                   APELL2USU = :apellido2,
                   FECULTMOD = TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                   USUARIOUMO = :usuarioumo,
                   CODTERMUMO = :codtermumo,
                   FECBAJA = :fecbaja,
                   CONTCUR = TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
             WHERE USUARIO = :usuario
        """
        binds = {
            "usuario": usuario,
            "nombre": first_name,
            "apellido1": apellido1,
            "apellido2": apellido2,
            "usuarioumo": Config.SAT_DEFAULT_USUARIOUMO,
            "codtermumo": Config.SAT_DEFAULT_CODTERMUMO,
            "fecbaja": Config.SAT_ACTIVE_FECBAJA if active else "TOUCH",  # placeholder patched below
        }
        binds["fecbaja"] = Config.SAT_ACTIVE_FECBAJA if active else None
        self._log_sql(sql, binds)
        cur.execute(sql, binds)

        if not active:
            sql_baja = f"""
                UPDATE {self.table_947}
                   SET FECBAJA = TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                       FECULTMOD = TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                       USUARIOUMO = :usuarioumo,
                       CONTCUR = TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
                 WHERE USUARIO = :usuario
            """
            baja_binds = {"usuario": usuario, "usuarioumo": Config.SAT_DEFAULT_USUARIOUMO}
            self._log_sql(sql_baja, baja_binds)
            cur.execute(sql_baja, baja_binds)

    def _ensure_958(self, cur, *, usuario: str, role_code: str, active: bool) -> None:
        # Usar MERGE para evitar race conditions y problemas con CHAR padding en Oracle.
        # PK de SGDT958 es (USUARIO + INSTALAC).
        fecbaja = Config.SAT_ACTIVE_FECBAJA if active else "BAJA"
        sql_merge = f"""
            MERGE INTO {self.table_958} tgt
            USING (
                SELECT :usuario AS USUARIO, :instalac AS INSTALAC FROM DUAL
            ) src
            ON (TRIM(tgt.USUARIO) = TRIM(src.USUARIO) AND TRIM(tgt.INSTALAC) = TRIM(src.INSTALAC))
            WHEN MATCHED THEN
                UPDATE SET
                    CODPERFIL    = :codperfil,
                    CODPERFILEXT = :codperfil_ext,
                    FECBAJA      = CASE WHEN :activo = 1
                                        THEN :fecbaja_activa
                                        ELSE TO_CHAR(SYSDATE,'YYYY-MM-DD') END,
                    USUARIOUMO   = :usuarioumo,
                    CONTCUR      = TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
            WHEN NOT MATCHED THEN
                INSERT (
                    USUARIO, INSTALAC, CODPERFIL, CODPERFILEXT, FECALTA, FECBAJA,
                    CODENTUMO, CODOFIUMO, USUARIOUMO, CODTERMUMO, CONTCUR
                ) VALUES (
                    :usuario, :instalac, :codperfil, :codperfil_ext,
                    TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                    CASE WHEN :activo = 1
                         THEN :fecbaja_activa
                         ELSE TO_CHAR(SYSDATE,'YYYY-MM-DD') END,
                    :codentumo, :codofi, :usuarioumo, :codtermumo,
                    TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
                )
        """
        binds = {
            "usuario":       usuario,
            "instalac":      Config.SAT_DEFAULT_INSTALAC,
            "codperfil":     role_code,
            "codperfil_ext": Config.SAT_DEFAULT_CODPERFILEXT,
            "activo":        1 if active else 0,
            "fecbaja_activa": Config.SAT_ACTIVE_FECBAJA,
            "codentumo":     Config.SAT_DEFAULT_CODENTUMO,
            "codofi":        Config.SAT_DEFAULT_CODOFIUMO,
            "usuarioumo":    Config.SAT_DEFAULT_USUARIOUMO,
            "codtermumo":    Config.SAT_DEFAULT_CODTERMUMO,
        }
        self._log_sql(sql_merge, binds)
        cur.execute(sql_merge, binds)

    def upsert_user(self, data: Dict[str, Any]) -> Dict[str, Any]:
        custom = data.get("custom") or {}
        rut_value = str(custom.get("rut") or "").strip()
        dv = str(custom.get("dv") or "").strip().upper()
        if rut_value:
            if dv and "-" not in rut_value:
                rut_input = f"{rut_value}-{dv}"
            else:
                rut_input = rut_value
            rut_only, dv_only = validate_rut_dv(rut_input)
        else:
            rut_only, dv_only = "", ""

        usuario = derive_sat_username(
            user_name=data.get("userName"),
            external_id=data.get("externalId"),
            rut_value=(f"{rut_only}-{dv_only}" if rut_only else ""),
            tipo_usuario=custom.get("tipoUsuario"),
        )
        first_name = normalize_upper(data.get("firstName"))
        apellido1 = normalize_upper(data.get("lastName"))
        apellido2 = normalize_upper(custom.get("apellidoMaterno"))

        if not apellido2 and apellido1 and " " in apellido1:
            apellido1, apellido2 = split_last_names(apellido1)

        if not first_name:
            raise ValueError("El atributo firstName es obligatorio para SAT.")
        if not apellido1:
            raise ValueError("El atributo lastName es obligatorio para SAT.")

        role_code = str(custom.get("codigoPerfil") or role_code_from_title(data.get("title"))).upper()
        role_info = role_record_from_code(role_code)
        active = bool(data.get("active", True))
        LOGGER.info(
            "SAT_UPSERT_START | usuario=%s | first_name=%s | apellido1=%s | apellido2=%s | active=%s | role_code=%s | title=%s",
            usuario, first_name, apellido1, apellido2, active, role_info["code"], data.get("title")
        )

        existing = self.get_user(usuario)
        with self._connect() as conn, conn.cursor() as cur:
            if existing:
                self._update_947(cur, usuario=usuario, first_name=first_name, apellido1=apellido1, apellido2=apellido2, active=active)
            else:
                self._insert_947(cur, usuario=usuario, first_name=first_name, apellido1=apellido1, apellido2=apellido2)

            self._ensure_958(cur, usuario=usuario, role_code=role_info["code"], active=active)
            conn.commit()
            LOGGER.info("DB_COMMIT | action=UPSERT_SAT_USER | usuario=%s", usuario)

        user = self.get_user(usuario)
        if not user:
            raise RuntimeError(f"No fue posible recuperar el usuario SAT '{usuario}' después del upsert.")

        user["title"] = data.get("title") or role_info["name"]
        user["custom"]["rut"] = rut_only or user["custom"].get("rut")
        user["custom"]["dv"] = dv_only or user["custom"].get("dv")
        user["custom"]["tipoUsuario"] = custom.get("tipoUsuario") or user["custom"].get("tipoUsuario")
        user["custom"]["apellidoMaterno"] = apellido2 or user["custom"].get("apellidoMaterno")
        user["custom"]["codigoPerfil"] = role_info["code"]
        user["custom"]["perfilNombre"] = role_info["name"]
        user["custom"]["userstatus"] = custom.get("userstatus") or ("activo" if active else "inactivo")
        return user

    def deactivate_user(self, usuario: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            sql_947 = f"""
                UPDATE {self.table_947}
                   SET FECBAJA = TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                       FECULTMOD = TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                       USUARIOUMO = :usuarioumo,
                       CONTCUR = TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
                 WHERE USUARIO = :usuario
            """
            binds_947 = {"usuario": usuario, "usuarioumo": Config.SAT_DEFAULT_USUARIOUMO}
            self._log_sql(sql_947, binds_947)
            cur.execute(sql_947, binds_947)

            sql_958 = f"""
                UPDATE {self.table_958}
                   SET FECBAJA = TO_CHAR(SYSDATE,'YYYY-MM-DD'),
                       USUARIOUMO = :usuarioumo,
                       CONTCUR = TO_CHAR(SYSDATE,'YYYY-MM-DD-HH24.MI.SS') || '.0' || TO_CHAR(SYSDATE,'SSSSS')
                 WHERE USUARIO = :usuario
                   AND INSTALAC = :instalac
            """
            binds_958 = {
                "usuario": usuario,
                "instalac": Config.SAT_DEFAULT_INSTALAC,
                "usuarioumo": Config.SAT_DEFAULT_USUARIOUMO,
            }
            self._log_sql(sql_958, binds_958)
            cur.execute(sql_958, binds_958)
            conn.commit()
            LOGGER.info("DB_COMMIT | action=DEACTIVATE_SAT_USER | usuario=%s", usuario)