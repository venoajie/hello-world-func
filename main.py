
import json
import logging
import os
import uuid
import tempfile
import textwrap
import re
from contextlib import asynccontextmanager
from typing import Annotated

import oci
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import JSONResponse

# --- Logging setup (unchanged) ---
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = { "timestamp": record.created, "level": record.levelname, "message": record.getMessage(), "invocation_id": getattr(record, 'invocation_id', 'N/A'), }
        return json.dumps(log_record)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)
logger.propagate = False

# --- Core Logic ---
object_storage_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global object_storage_client
    log = logging.LoggerAdapter(logger, {'invocation_id': 'startup'})
    log.info("Function cold start: Initializing dependencies...")

    key_file_path = None
    try:
        log.info("Capturing and parsing the raw environment string to bypass runtime instability.")
        env_string = repr(os.environ)

        def get_value_from_env_string(key: str, env_str: str) -> str | None:
            match = re.search(f"'{re.escape(key)}': '([^']*)'", env_str)
            if match:
                return match.group(1)
            return None

        user_ocid = get_value_from_env_string("OCI_USER_OCID", env_string)
        fingerprint = get_value_from_env_string("OCI_FINGERPRINT", env_string)
        tenancy_ocid = get_value_from_env_string("OCI_TENANCY_OCID", env_string)
        region = get_value_from_env_string("OCI_REGION", env_string)
        raw_key_content = get_value_from_env_string("OCI_PRIVATE_KEY_CONTENT", env_string)

        if not all([user_ocid, fingerprint, tenancy_ocid, region, raw_key_content]):
            log.critical(f"FATAL: Could not parse one or more required OCI credentials from the environment string.")
            raise ValueError("Failed to extract necessary OCI credentials from environment.")

        # --- CRITICAL FIX for OCI Console newline stripping bug ---
        # The OCI Console removes newlines. This code reconstructs the proper PEM format.
        log.info("Reconstructing PEM key format to handle platform newline stripping.")
        pem_header = "-----BEGIN RSA PRIVATE KEY-----"
        pem_footer = "-----END RSA PRIVATE KEY-----"
        # The key content from the environment is a single line without headers/footers.
        base64_body = raw_key_content.replace(pem_header, "").replace(pem_footer, "").strip()
        # Re-wrap the single line of base64 text into 64-character lines.
        wrapped_body = "\n".join(textwrap.wrap(base64_body, 64))
        private_key_content = f"{pem_header}\n{wrapped_body}\n{pem_footer}\n"

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as key_file:
            key_file.write(private_key_content)
            key_file_path = key_file.name

        config = {
            "user": user_ocid,
            "key_file": key_file_path,
            "fingerprint": fingerprint,
            "tenancy": tenancy_ocid,
            "region": region
        }

        oci.config.validate_config(config)
        log.info("OCI config dictionary validated successfully.")

        object_storage_client = oci.object_storage.ObjectStorageClient(config=config)
        log.info("Successfully created OCI Object Storage client.")

    except Exception as e:
        log.critical(f"FATAL: Could not initialize OCI client during startup: {e}", exc_info=True)
        raise
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)

    yield
    log.info("Function shutting down.")


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
    fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None
):
    log = get_logger(fn_invoke_id)
    log.info("Invocation received.")

    try:
        oci_namespace = os.environ.get('OCI_NAMESPACE', 'YOUR_DEFAULT_NAMESPACE')
        target_bucket = os.environ.get('TARGET_BUCKET_NAME', 'YOUR_DEFAULT_BUCKET')

        object_name = f"hello-from-fastapi-{log.extra['invocation_id']}.txt"
        file_content = f"Hello from FastAPI on OCI Functions! This is invocation {log.extra['invocation_id']}."

        log.info(f"Attempting to write object '{object_name}' to bucket '{target_bucket}' in namespace '{oci_namespace}'.")
        os_client.put_object(
            namespace_name=oci_namespace,
            bucket_name=target_bucket,
            object_name=object_name,
            put_object_body=file_content.encode('utf-8')
        )
        log.info("Successfully wrote object to bucket.")

        return JSONResponse(
            content={ "status": "success", "message": "File written to bucket successfully.", "invocation_id": log.extra['invocation_id'], "bucket": target_bucket, "object_name": object_name },
            status_code=200
        )
    except oci.exceptions.ServiceError as e:
        log.error(f"OCI Service Error during invocation: {e.status} {e.message}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"OCI Error: {e.message}")
    except Exception as e:
        log.error(f"An unexpected error occurred during invocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")
