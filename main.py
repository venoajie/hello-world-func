
"""
main.py - OCI Function with FastAPI

This application serves as a robust template for deploying a Python FastAPI application
as an OCI Function. It is designed to write a simple file to an OCI Object Storage bucket.

CRITICAL ARCHITECTURAL NOTES:
This file contains a mandatory, non-standard workaround for a known platform bug
in the OCI Functions runtime related to `os.environ`.

For a full explanation of this workaround, please consult the
`FUNCTION_OPERATIONS_MANUAL.md` document in this repository.
"""

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
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

# --- Constants for Configuration and Keys ---
# This improves readability and prevents typos.
REQUIRED_AUTH_VARS = [
    "OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_TENANCY_OCID",
    "OCI_REGION", "OCI_PRIVATE_KEY_CONTENT"
]

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


# --- Core Logic & OCI Initialization ---
object_storage_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup logic. This is where the OCI client is
    initialized, including all mandatory platform workarounds.
    """
    global object_storage_client
    log = logging.LoggerAdapter(logger, {'invocation_id': 'startup'})
    log.info("Function cold start: Initializing OCI client...")

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
            key: _get_config_from_env_str(key, env_str)
            for key in REQUIRED_AUTH_VARS
        }

        if not all(config_values.values()):
            missing = [k for k, v in config_values.items() if not v]
            raise ValueError(f"Missing critical OCI configuration: {missing}")

        # --- TEST: The PEM Key Reconstruction Workaround is REMOVED ---
        # We are now assuming the OCI_PRIVATE_KEY_CONTENT environment variable
        # contains a perfectly formatted, multi-line PEM string.
        log.info("TESTING: Bypassing PEM key reconstruction. Using raw key content directly.")
        private_key_content = config_values["OCI_PRIVATE_KEY_CONTENT"]
        # --- END OF TEST MODIFICATION ---

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
        object_storage_client = oci.object_storage.ObjectStorageClient(config=config)
        log.info("Successfully created and configured OCI Object Storage client.")

    except Exception as e:
        log.critical(f"FATAL: Could not initialize OCI client during startup: {e}", exc_info=True)
        raise
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)

    yield
    log.info("Function shutting down.")


# --- FastAPI Dependency Injection & Application (Unchanged) ---
def get_logger(fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None) -> logging.LoggerAdapter:
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    return logging.LoggerAdapter(logger, {'invocation_id': invocation_id})

def get_os_client():
    if object_storage_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: OCI client not initialized.")
    return object_storage_client

app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None, lifespan=lifespan)

@app.post("/call")
async def handle_invocation(
    os_client: Annotated[any, Depends(get_os_client)],
    log: Annotated[logging.LoggerAdapter, Depends(get_logger)]
):
    log.info("Invocation received.")
    try:
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

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "File written to bucket successfully.",
                "invocation_id": log.extra['invocation_id'],
                "bucket": target_bucket,
                "object_name": object_name
            }
        )
    except oci.exceptions.ServiceError as e:
        log.error(f"OCI Service Error: {e.status} {e.message}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OCI Error: {e.message}")
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
