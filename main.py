
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import pydantic
import pydantic_settings
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

# --- 1. Structured Logging (from rag-app) ---
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

def get_logger(fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None) -> logging.LoggerAdapter:
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    return logging.LoggerAdapter(logger, {'invocation_id': invocation_id})

# --- 2. Strict Configuration (from rag-app) ---
class Settings(pydantic_settings.BaseSettings):
    OCI_NAMESPACE: str
    TARGET_BUCKET_NAME: str
    model_config = pydantic_settings.SettingsConfigDict(extra='ignore')

# --- 3. Core Logic and Dependency Management (Best of Both Worlds) ---
# Global variable to hold the OCI client, initialized once at startup.
object_storage_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global object_storage_client
    log = logging.LoggerAdapter(logger, {'invocation_id': 'startup'})
    log.info("Function cold start: Initializing dependencies...")
    
    # THE FIX: We import and initialize the heavy SDK inside the lifespan manager.
    # This keeps the top-level module import clean and fast.
    import oci
    
    try:
        signer = oci.auth.signers.get_resource_principals_signer()
        object_storage_client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
        log.info("Successfully created OCI Object Storage client.")
    except Exception as e:
        log.critical(f"FATAL: Could not initialize OCI client during startup: {e}", exc_info=True)
        # Re-raise to prevent the function from starting in a broken state
        raise
    
    yield # The application is now running
    
    log.info("Function shutting down.")

# Dependency injector function
def get_os_client():
    if object_storage_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: OCI client not initialized.")
    return object_storage_client

# --- 4. FastAPI Application ---
app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None, lifespan=lifespan)

@app.post("/")
async def handle_invocation(
    settings: Annotated[Settings, pydantic.Depends(Settings)],
    log: Annotated[logging.LoggerAdapter, pydantic.Depends(get_logger)],
    os_client: Annotated[any, pydantic.Depends(get_os_client)]
):
    invocation_id = log.extra['invocation_id']
    log.info("Invocation received.")
    
    try:
        object_name = f"hello-from-fastapi-{invocation_id}.txt"
        file_content = f"Hello from FastAPI on OCI Functions! This is invocation {invocation_id}."
        
        log.info(f"Attempting to write object '{object_name}' to bucket '{settings.TARGET_BUCKET_NAME}'.")
        os_client.put_object(
            namespace_name=settings.OCI_NAMESPACE,
            bucket_name=settings.TARGET_BUCKET_NAME,
            object_name=object_name,
            put_object_body=file_content.encode('utf-8')
        )
        log.info("Successfully wrote object to bucket.")
        
        return JSONResponse(
            content={
                "status": "success",
                "message": "File written to bucket successfully.",
                "invocation_id": invocation_id,
                "bucket": settings.TARGET_BUCKET_NAME,
                "object_name": object_name
            },
            status_code=200
        )
    except Exception as e:
        log.error(f"An error occurred during invocation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {e}")