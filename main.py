
"""
main.py - OCI Function with FastAPI

This application serves as a robust template for deploying a Python FastAPI application
as an OCI Function. It is designed to write a simple file to an OCI Object Storage bucket
and verify connectivity to a PostgreSQL database.

This version correctly preserves the mandatory API Key authentication method and its
associated workarounds, while adding the new functionality to connect to a database
using credentials fetched from OCI Vault.

CRITICAL ARCHITECTURAL NOTES:
This file contains two mandatory, non-standard workarounds for known platform bugs
in the OCI Functions runtime. They are not bugs in this code; they are required for
the function to operate correctly.

1.  **Environment Variable Parsing:** The `os.environ` object is unreliable. Critical
    configuration is parsed manually from its string representation.
2.  **PEM Key Reconstruction:** The private key is programmatically reformatted to handle
    a bug where the OCI Console strips newline characters.
"""

import base64
import json
import logging
import os
import re
import tempfile
import textwrap
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import oci
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from psycopg_pool import AsyncConnectionPool

# --- Constants for Configuration and Keys ---
REQUIRED_AUTH_VARS = [
    "OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_TENANCY_OCID",
    "OCI_REGION", "OCI_PRIVATE_KEY_CONTENT"
]
PEM_HEADER = "-----BEGIN RSA PRIVATE KEY-----"
PEM_FOOTER = "-----END RSA PRIVATE KEY-----"


# --- Logging Setup ---
class JSONFormatter(logging.Formatter):
    """Formats log records as a single JSON line."""
    def format(self, record):
        log_record = {
            "timestamp": record.created,
            "level": record.levelname,
            "message": record.getMessage(),
            "invocation_id": getattr(record, 'invocation_id', 'N/A'),
        }
        return json.dumps(log_record)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.propagate = False


# --- Global Clients & Connection Pool ---
object_storage_client = None
vault_client = None
db_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup logic. This is where OCI clients and the DB pool
    are initialized using the mandatory API Key authentication method.
    """
    global object_storage_client, vault_client, db_pool
    log = logging.LoggerAdapter(logger, {'invocation_id': 'startup'})
    log.info("Function cold start: Initializing OCI clients and DB pool...")

    key_file_path = None
    try:
        # --- WORKAROUND 1: Manual Environment Variable Parsing ---
        log.info("Capturing and parsing raw environment string due to platform instability.")
        env_string = repr(os.environ)

        def _get_config_from_env_str(key: str, env_str: str) -> str | None:
            """Safely extracts a value from the raw os.environ string."""
            match = re.search(f"'{re.escape(key)}': '([^']*)'", env_str)
            return match.group(1) if match else None

        config_values = {
            key: _get_config_from_env_str(key, env_string)
            for key in REQUIRED_AUTH_VARS
        }

        if not all(config_values.values()):
            missing = [k for k, v in config_values.items() if not v]
            raise ValueError(f"Missing critical OCI configuration: {missing}")

        # --- WORKAROUND 2: PEM Private Key Reconstruction ---
        log.info("Reconstructing PEM key format to handle platform newline stripping.")
        base64_body = config_values["OCI_PRIVATE_KEY_CONTENT"].replace(PEM_HEADER, "").replace(PEM_FOOTER, "").strip()
        wrapped_body = "\n".join(textwrap.wrap(base64_body, 64))
        private_key_content = f"{PEM_HEADER}\n{wrapped_body}\n{PEM_FOOTER}\n"

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as key_file:
            key_file.write(private_key_content)
            key_file_path = key_file.name

        # --- Build and Validate the Final OCI Config ---
        config = {
            "user": config_values["OCI_USER_OCID"],
            "key_file": key_file_path,
            "fingerprint": config_values["OCI_FINGERPRINT"],
            "tenancy": config_values["OCI_TENANCY_OCID"],
            "region": config_values["OCI_REGION"]
        }

        oci.config.validate_config(config)
        # --- Initialize OCI Service Clients using the validated config ---
        object_storage_client = oci.object_storage.ObjectStorageClient(config=config)
        vault_client = oci.vault.VaultsClient(config=config)
        log.info("Successfully created OCI Object Storage and Vault clients via API Key.")

        # --- Fetch DB Credentials from Vault ---
        log.info("Fetching database credentials from OCI Vault.")
        db_secret_ocid = _get_config_from_env_str('DB_SECRET_OCID', env_string)
        if not db_secret_ocid:
            raise ValueError("Missing critical configuration: DB_SECRET_OCID")

        secret_bundle = vault_client.get_secret_bundle(secret_id=db_secret_ocid)
        secret_content = secret_bundle.data.secret_bundle_content.content
        decoded_secret = base64.b64decode(secret_content).decode('utf-8')
        db_creds = json.loads(decoded_secret)

        conn_info = (
            f"host={db_creds['host']} port={db_creds['port']} "
            f"dbname={db_creds['dbname']} user={db_creds['username']} "
            f"password={db_creds['password']}"
        )

        # --- Initialize Database Connection Pool ---
        log.info(f"Initializing database connection pool for {db_creds['dbname']}@{db_creds['host']}.")
        db_pool = AsyncConnectionPool(conninfo=conn_info, min_size=1, max_size=5)
        async with db_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                log.info("Database connection pool successfully initialized and tested.")

    except Exception as e:
        log.critical(f"FATAL: Could not initialize OCI clients or DB pool during startup: {e}", exc_info=True)
        raise
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)

    yield

    if db_pool:
        await db_pool.close()
        log.info("Database connection pool closed.")
    log.info("Function shutting down.")


# --- FastAPI Dependency Injection ---
def get_logger(fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None) -> logging.LoggerAdapter:
    """Provides a logger adapter with the invocation ID."""
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    return logging.LoggerAdapter(logger, {'invocation_id': invocation_id})

def get_os_client():
    """Provides the initialized Object Storage client."""
    if object_storage_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: OCI client not initialized.")
    return object_storage_client

async def get_db_connection():
    """Provides a connection from the async database pool."""
    if db_pool is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: DB pool not initialized.")
    async with db_pool.connection() as conn:
        yield conn


# --- FastAPI Application ---
app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None, lifespan=lifespan)

@app.post("/call")
async def handle_invocation(
    os_client: Annotated[any, Depends(get_os_client)],
    log: Annotated[logging.LoggerAdapter, Depends(get_logger)],
    db_conn: Annotated[psycopg.AsyncConnection, Depends(get_db_connection)]
):
    """
    Handles the function invocation, writing a file to a bucket and querying a database.
    """
    log.info("Invocation received.")
    db_version = None

    try:
        # --- 1. Object Storage Operation ---
        try:
            oci_namespace = os.environ['OCI_NAMESPACE']
            target_bucket = os.environ['TARGET_BUCKET_NAME']
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

        # --- 2. Database Operation ---
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