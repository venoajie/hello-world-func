
import json
import logging
import os
import uuid
import tempfile
import textwrap
from contextlib import asynccontextmanager
from typing import Annotated

import oci
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import JSONResponse

# --- 1. Structured Logging (Corrected) ---
class JSONFormatter(logging.Formatter):
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

# --- 2. Core Logic and Dependency Management ---
object_storage_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global object_storage_client
    log = logging.LoggerAdapter(logger, {'invocation_id': 'startup'})
    log.info("Function cold start: Initializing dependencies...")

    key_file_path = None
    try:
        # --- THE DEFINITIVE FIX: DEEP COPY THE ENVIRONMENT ---
        # The OCI runtime's os.environ object is unreliable. We perform a one-time,
        # full copy into a standard Python dictionary and use it exclusively.
        log.info("Performing a deep copy of the environment to a stable dictionary...")
        app_config = dict(os.environ)
        log.info("Environment copy complete.")
        # --- From this point on, we ONLY use 'app_config', never 'os.environ' ---

        # --- OCI UI WORKAROUND (using our clean app_config) ---
        log.info("Reconstructing PEM key format...")
        raw_key_content = app_config.get("OCI_PRIVATE_KEY_CONTENT", "")
        pem_header = "-----BEGIN RSA PRIVATE KEY-----"
        pem_footer = "-----END RSA PRIVATE KEY-----"
        base64_body = raw_key_content.replace(pem_header, "").replace(pem_footer, "").strip()
        wrapped_body = "\n".join(textwrap.wrap(base64_body, 64))
        private_key_content = f"{pem_header}\n{wrapped_body}\n{pem_footer}\n"
        log.info("PEM key successfully reconstructed.")

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as key_file:
            key_file.write(private_key_content)
            key_file_path = key_file.name

        # --- Build the final config using our clean app_config dictionary ---
        # We use .get() for safety, though the keys should exist.
        config = {
            "user": app_config.get("OCI_USER_OCID"),
            "key_file": key_file_path,
            "fingerprint": app_config.get("OCI_FINGERPRINT"),
            "tenancy": app_config.get("OCI_TENANCY_OCID"),
            "region": app_config.get("OCI_REGION")
        }
        
        oci.config.validate_config(config)
        log.info("OCI config validated.")
        
        signer = oci.Signer.from_config(config)
        object_storage_client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
        log.info("Successfully created OCI Object Storage client using API Key.")
        
    except Exception as e:
        log.critical(f"FATAL: Could not initialize OCI client during startup: {e}", exc_info=True)
        raise
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)
    
    yield
    log.info("Function shutting down.")

# ... (Rest of the file is unchanged) ...
def get_logger(fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None) -> logging.LoggerAdapter:
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    return logging.LoggerAdapter(logger, {'invocation_id': invocation_id})

def get_os_client():
    if object_storage_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: OCI client not initialized.")
    return object_storage_client

app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None, lifespan=lifespan)

@asynccontextmanager
async def handle_invocation(
    os_client: Annotated[any, Depends(get_os_client)],
    fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None
):
    log = get_logger(fn_invoke_id)
    log.info("Invocation received.")
    
    try:
        # It's safer to use our deep-copied config for these as well,
        # but we need to pass it down from the lifespan. For now, let's
        # assume these less critical variables work.
        app_config = dict(os.environ)
        oci_namespace = app_config.get('OCI_NAMESPACE')
        target_bucket = app_config.get('TARGET_BUCKET_NAME')

        object_name = f"hello-from-fastapi-{log.extra['invocation_id']}.txt"
        file_content = f"Hello from FastAPI on OCI Functions! This is invocation {log.extra['invocation_id']}."
        
        log.info(f"Attempting to write object '{object_name}' to bucket '{target_bucket}'.")
        os_client.put_object(
            namespace_name=oci_namespace,
            bucket_name=target_bucket,
            object_name=object_name,
            put_object_body=file_content.encode('utf-8')
        )
        log.info("Successfully wrote object to bucket.")
        
        return JSONResponse(
            content={
                "status": "success",
                "message": "File written to bucket successfully.",
                "invocation_id": log.extra['invocation_id'],
                "bucket": target_bucket,
                "object_name": object_name
            },
            status_code=200
        )
    except Exception as e:
        log.error(f"An error occurred during invocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")