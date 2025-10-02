
import json
import logging
import os
import uuid
import tempfile
import textwrap
import ast  # Import the Abstract Syntax Tree library for safe string evaluation
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
        # --- THE DEFINITIVE FIX: PARSE THE ENVIRONMENT STRING ---
        # The os.environ object is broken. We get its string representation,
        # which we know is correct, and parse it into a real dictionary.
        log.info("Capturing string representation of the faulty environment object...")
        env_string = repr(os.environ)
        log.info(f"os.environ {os.environ}")
        log.info(f"env_string {env_string}")
        
        # Extract the dictionary literal string from the full 'environ({...})' string
        start = env_string.find('{')
        end = env_string.rfind('}') + 1
        dict_string = env_string[start:end]
        
        # Safely evaluate the string literal into a real Python dictionary
        log.info("Parsing the environment string into a stable dictionary...")
        app_config = [ast.literal_eval(str(i)) for i in dict_string]  
        log.info(f"app_config {app_config}")
        log.info("Environment successfully parsed. Proceeding with a stable config.")
        # --- From this point on, we ONLY use 'app_config' ---

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

@app.post("/")
async def handle_invocation(
    os_client: Annotated[any, Depends(get_os_client)],
    fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None
):
    log = get_logger(fn_invoke_id)
    log.info("Invocation received.")
    
    try:
        # For maximum safety, we should re-parse the environment here too,
        # or pass the app_config down from the lifespan context.
        # This simpler approach should be sufficient for now.
        env_snapshot = dict(os.environ)
        oci_namespace = env_snapshot.get('OCI_NAMESPACE', 'default_namespace') # Add defaults
        target_bucket = env_snapshot.get('TARGET_BUCKET_NAME', 'default_bucket')

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