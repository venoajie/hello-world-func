
"""
main.py - OCI Function with FastAPI (ULTRA-TARGETED DEBUG VERSION)

This version adds one critical log message to print the exact database
connection parameters right before the connection attempt that is causing
the timeout.
"""

import base64
import json
import logging
import os
import re
import tempfile
import textwrap
import uuid
import traceback
from contextlib import asynccontextmanager
from typing import Annotated

import oci
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

# --- Constants for Configuration and Keys (No changes) ---
REQUIRED_AUTH_VARS = [
    "OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_TENANCY_OCID",
    "OCI_REGION", "OCI_PRIVATE_KEY_CONTENT"
]
PEM_HEADER = "-----BEGIN RSA PRIVATE KEY-----"
PEM_FOOTER = "-----END RSA PRIVATE KEY-----"


# --- Logging Setup (No changes) ---
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": record.created,
            "level": record.levelname,
            "message": record.getMessage(),
            "invocation_id": getattr(record, 'invocation_id', 'N/A'),
        }
        if record.exc_info:
            log_record['exception'] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(log_record)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if logger.hasHandlers():
    logger.handlers.clear()
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.propagate = False


# --- Global Clients & Connection Pool (No changes) ---
object_storage_client = None
secrets_client = None
db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global object_storage_client, secrets_client, db_pool
    log = logging.LoggerAdapter(logger, {'invocation_id': 'startup'})
    log.info("--- LIFESPAN START: BEGINNING INITIALIZATION ---")

    key_file_path = None
    try:
        # Steps 1-4: OCI Client Initialization (Assumed to be working)
        env_string = repr(os.environ)
        def _get_config_from_env_str(key: str, env_str: str) -> str | None:
            match = re.search(f"'{re.escape(key)}': '([^']*)'", env_str)
            return match.group(1) if match else None

        config_values = {key: _get_config_from_env_str(key, env_string) for key in REQUIRED_AUTH_VARS}
        if not all(config_values.values()):
            missing = [k for k, v in config_values.items() if not v]
            raise ValueError(f"Missing OCI auth config: {missing}")

        base64_body = config_values["OCI_PRIVATE_KEY_CONTENT"].replace(PEM_HEADER, "").replace(PEM_FOOTER, "").strip()
        wrapped_body = "\n".join(textwrap.wrap(base64_body, 64))
        private_key_content = f"{PEM_HEADER}\n{wrapped_body}\n{PEM_FOOTER}\n"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as key_file:
            key_file.write(private_key_content)
            key_file_path = key_file.name

        config = {
            "user": config_values["OCI_USER_OCID"], "key_file": key_file_path,
            "fingerprint": config_values["OCI_FINGERPRINT"], "tenancy": config_values["OCI_TENANCY_OCID"],
            "region": config_values["OCI_REGION"]
        }
        oci.config.validate_config(config)
        object_storage_client = oci.object_storage.ObjectStorageClient(config=config)
        secrets_client = oci.secrets.SecretsClient(config=config)
        log.info("OCI clients initialized successfully.")

        # Step 5: Fetch DB Secret from Vault
        db_secret_ocid = _get_config_from_env_str('DB_SECRET_OCID', env_string)
        if not db_secret_ocid:
            raise ValueError("Missing critical configuration: DB_SECRET_OCID")

        secret_bundle = secrets_client.get_secret_bundle(secret_id=db_secret_ocid)
        secret_content = secret_bundle.data.secret_bundle_content.content
        decoded_secret = base64.b64decode(secret_content).decode('utf-8')
        db_creds = json.loads(decoded_secret)
        log.info("Database secret successfully fetched and decoded from Vault.")

        # <<< --- THIS IS THE NEW, CRITICAL LOG MESSAGE --- >>>
        log.info("CRITICAL_DEBUG: About to attempt database connection with the following parameters:",
                 extra={
                     "db_host": db_creds.get('host'),
                     "db_port": db_creds.get('port'),
                     "db_user": db_creds.get('username'),
                     "db_name": db_creds.get('dbname')
                 })
        # <<< --- END OF NEW LOG MESSAGE --- >>>

        # Step 6: Initialize and Test Database Connection Pool
        conn_info_real = (
            f"host={db_creds['host']} port={db_creds['port']} "
            f"dbname={db_creds['dbname']} user={db_creds['username']} "
            f"password={db_creds['password']}"
        )
        db_pool = AsyncConnectionPool(conninfo=conn_info_real, min_size=1, max_size=5, open_timeout=15) # Added 15s timeout
        
        log.info("Testing database connection...")
        async with db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
        log.info("Database connection test successful.")
        log.info("--- LIFESPAN SUCCESS: ALL DEPENDENCIES INITIALIZED ---")

    except Exception as e:
        log.critical(f"--- FATAL LIFESPAN CRASH: An unexpected error occurred during startup: {e}", exc_info=True)
        raise
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)

    yield
    # (Rest of the file is unchanged)
    if db_pool:
        await db_pool.close()

# --- FastAPI Dependency Injection and Application (No changes) ---
def get_logger(fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None) -> logging.LoggerAdapter:
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    return logging.LoggerAdapter(logger, {'invocation_id': invocation_id})

def get_os_client():
    if object_storage_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: OCI client not initialized.")
    return object_storage_client

async def get_db_connection():
    if db_pool is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: DB pool not initialized.")
    async with db_pool.connection() as conn:
        yield conn

app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None, lifespan=lifespan)

@app.post("/call")
async def handle_invocation(
    os_client: Annotated[any, Depends(get_os_client)],
    log: Annotated[logging.LoggerAdapter, Depends(get_logger)],
    db_conn: Annotated[psycopg.AsyncConnection, Depends(get_db_connection)]
):
    log.info("Invocation received.")
    db_version = None
    try:
        try:
            oci_namespace = os.getenv('OCI_NAMESPACE')
            target_bucket = os.getenv('TARGET_BUCKET_NAME')
            if not oci_namespace or not target_bucket:
                raise KeyError("OCI_NAMESPACE or TARGET_BUCKET_NAME not set")
        except KeyError as e:
            log.error(f"Missing required runtime configuration: {e}")
            raise HTTPException(status_code=500, detail=f"Configuration Error: Missing environment variable {e}")

        object_name = f"hello-from-fastapi-{log.extra['invocation_id']}.txt"
        file_content = f"Hello from FastAPI! This is invocation {log.extra['invocation_id']}."

        log.info(f"Attempting to write object '{object_name}' to bucket '{target_bucket}'.")
        os_client.put_object(
            namespace_name=oci_namespace,
            bucket_name=target_bucket,
            object_name=object_name,
            put_object_body=file_content.encode('utf-8')
        )
        log.info("Successfully wrote object to bucket.")

        log.info("Querying database to verify connection.")
        async with db_conn.cursor() as cur:
            await cur.execute("SELECT version();")
            result = await cur.fetchone()
            db_version = result[0] if result else "N/A"
        log.info(f"Successfully connected to database. Version: {db_version[:30]}...")

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "File written to bucket and database connection verified.",
                "invocation_id": log.extra['invocation_id'],
                "bucket": target_bucket,
                "object_name": object_name,
                "database_version": db_version
            }
        )
    except oci.exceptions.ServiceError as e:
        log.error(f"OCI Service Error: {e.status} {e.message}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OCI Error: {e.message}")
    except psycopg.Error as e:
        log.error(f"Database Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database Error: {e}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
