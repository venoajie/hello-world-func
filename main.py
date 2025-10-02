
# main.py
import json
import logging
import os
import uuid
from typing import Annotated

import oci
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

# --- OCI and Business Logic (mostly unchanged) ---

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_env_var(var_name):
    """Gets a required environment variable or raises an error."""
    value = os.getenv(var_name)
    if not value:
        # In a web server, raising an exception is better
        raise ValueError(f"FATAL: Required environment variable '{var_name}' is not set.")
    return value

def write_object_to_bucket(invocation_id: str):
    """Authenticates and writes a file to Object Storage."""
    logger.info(f"Function logic started for invocation ID: {invocation_id}")
    
    # 1. Get configuration from function environment variables
    oci_namespace = get_env_var("OCI_NAMESPACE")
    target_bucket = get_env_var("TARGET_BUCKET_NAME")
    
    # 2. Authenticate using the function's identity (Resource Principal)
    signer = oci.auth.signers.get_resource_principals_signer()
    os_client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
    logger.info("Successfully authenticated with OCI using Resource Principals.")

    # 3. Prepare the file to write
    object_name = f"hello-from-fastapi-{invocation_id}.txt"
    file_content = f"Hello from FastAPI on OCI Functions! This is invocation {invocation_id}."
    
    # 4. Execute the write operation
    logger.info(f"Attempting to write object '{object_name}' to bucket '{target_bucket}'.")
    os_client.put_object(
        namespace_name=oci_namespace,
        bucket_name=target_bucket,
        object_name=object_name,
        put_object_body=file_content.encode('utf-8')
    )
    logger.info("Successfully wrote object to bucket.")
    return {"bucket": target_bucket, "object_name": object_name}


# --- FastAPI Application ---

app = FastAPI(title="Hello World Writer", docs_url=None, redoc_url=None)

@app.post("/")
async def handle_invocation(
    # The platform passes the invocation ID in this header
    fn_invoke_id: Annotated[str | None, Header(alias="fn-invoke-id")] = None
):
    """
    This endpoint is called by the OCI Functions platform for every invocation.
    """
    # Use the platform's ID if available, otherwise generate one.
    invocation_id = fn_invoke_id or str(uuid.uuid4())
    
    try:
        result = write_object_to_bucket(invocation_id)
        
        return JSONResponse(
            content={
                "status": "success",
                "message": "File written to bucket successfully.",
                "invocation_id": invocation_id,
                **result
            },
            status_code=200
        )
    except Exception as e:
        logger.error(f"An error occurred during invocation {invocation_id}: {str(e)}", exc_info=True)
        # Use HTTPException for standard error responses
        raise HTTPException(
            status_code=500,
            detail=f"An internal error occurred: {str(e)}"
        )

@app.get("/health")
async def health_check():
    return {"status": "ok"}