
# main.py (DIAGNOSTIC BUILD)
import json
import logging
import os
import uuid
import tempfile
from contextlib import asynccontextmanager
from typing import Annotated

import oci
import oci.exceptions # Explicitly import for try/except catching
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import JSONResponse

# --- 1. Structured Logging ---
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
    log.info("Function cold start: Initializing dependencies (DIAGNOSTIC MODE)...")

    key_file_path = None

    try:
        # --- DIAGNOSTIC INSERTION START ---
        private_key_content = os.environ['OCI_PRIVATE_KEY_CONTENT']
        
        # 1. Log the type coming from the environment
        log.info(f"DIAGNOSTIC: 'OCI_PRIVATE_KEY_CONTENT' Python Type: {type(private_key_content).__name__}")

        # 2. Log the exact byte representation that will be written to disk
        # We encode to utf-8 here to simulate what 'w' mode does, and inspect the bytes.
        debug_bytes = private_key_content.encode('utf-8')
        # Show hex to detect hidden characters/BOM, and repr to show escaped chars like \n
        log.info(f"DIAGNOSTIC: Key Content First 64 Bytes (HEX): {debug_bytes[:64].hex()}")
        log.info(f"DIAGNOSTIC: Key Content First 64 Bytes (REPR): {repr(debug_bytes[:64])}")

        # Proceed with writing the file as before
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".pem") as key_file:
            key_file.write(private_key_content)
            key_file_path = key_file.name
        log.info(f"DIAGNOSTIC: Temp file written to {key_file_path}")
        # --- DIAGNOSTIC INSERTION END ---

        config = {
            "user": os.environ['OCI_USER_OCID'],
            "key_file": key_file_path,
            "fingerprint": os.environ['OCI_FINGERPRINT'],
            "tenancy": os.environ['OCI_TENANCY_OCID'],
            "region": os.environ['OCI_REGION']
        }
        
        oci.config.validate_config(config)
        log.info("OCI config validated. Attempting Signer creation...")
        
        # --- DIAGNOSTIC TRAP START ---
        try:
            # This is the expected failure point
            signer = oci.Signer.from_config(config)
            log.info("DIAGNOSTIC: Signer created successfully (UNEXPECTED).")
        except oci.exceptions.InvalidPrivateKey as e:
            # Capture the exact SDK error
            log.critical(f"DIAGNOSTIC: CAUGHT EXPECTED InvalidPrivateKey. Message: {str(e)}")
            log.critical(f"DIAGNOSTIC: Underlying error (if any): {getattr(e, 'inner_exception', 'None')}")
            raise # Re-raise to trigger the fatal catch below
        # --- DIAGNOSTIC TRAP END ---

        object_storage_client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
        log.info("Successfully created OCI Object Storage client.")
        
    except Exception as e:
        log.critical(f"FATAL: Could not initialize OCI client during startup: {e}", exc_info=True)
        # Ensure container fails initialization
        raise
    finally:
        if key_file_path and os.path.exists(key_file_path):
            os.remove(key_file_path)
            log.info("DIAGNOSTIC: Cleaned up temp key file.")
    
    yield
    log.info("Function shutting down.")
    
def get_os_client():
    if object_storage_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: OCI client not initialized.")
    return object_storage_client

# --- 3. FastAPI Application ---
app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None, lifespan=lifespan)

@app.post("/")
async def handle_invocation(
    # --- THE FIX: Reordered the parameters ---
    os_client: Annotated[any, Depends(get_os_client)],
    fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None
):
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    log = logging.LoggerAdapter(logger, {'invocation_id': invocation_id})
    log.info("Invocation received.")
    
    try:
        # We get these from the environment now, not Pydantic settings
        oci_namespace = os.environ['OCI_NAMESPACE']
        target_bucket = os.environ['TARGET_BUCKET_NAME']

        object_name = f"hello-from-fastapi-{invocation_id}.txt"
        file_content = f"Hello from FastAPI on OCI Functions! This is invocation {invocation_id}."
        
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
                "invocation_id": invocation_id,
                "bucket": target_bucket,
                "object_name": object_name
            },
            status_code=200
        )
    except Exception as e:
        log.error(f"An error occurred during invocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")