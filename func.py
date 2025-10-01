
import io
import json
import logging
import os
import uuid
from fdk import response

import oci
from oci.object_storage.models import CreateBucketDetails

# Configure basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_env_var(var_name):
    """Gets a required environment variable or raises an error."""
    value = os.getenv(var_name)
    if not value:
        raise ValueError(f"FATAL: Required environment variable '{var_name}' is not set.")
    return value

def handler(ctx, data: io.BytesIO=None):
    """
    OCI Function handler.
    Authenticates using Resource Principals and writes a file to Object Storage.
    """
    invocation_id = ctx.FnInvokeID()
    logger.info(f"Function invoked. Invocation ID: {invocation_id}")

    try:
        # 1. Get configuration from function environment variables
        oci_namespace = get_env_var("OCI_NAMESPACE")
        target_bucket = get_env_var("TARGET_BUCKET_NAME")
        
        # 2. Authenticate using the function's identity (Resource Principal)
        signer = oci.auth.signers.get_resource_principals_signer()
        os_client = oci.object_storage.ObjectStorageClient(config={}, signer=signer)
        logger.info("Successfully authenticated with OCI using Resource Principals.")

        # 3. Prepare the file to write
        object_name = f"hello-from-function-{invocation_id}-{uuid.uuid4()}.txt"
        file_content = f"Hello from OCI Function! This is invocation {invocation_id}."
        
        # 4. Execute the write operation
        logger.info(f"Attempting to write object '{object_name}' to bucket '{target_bucket}'.")
        os_client.put_object(
            namespace_name=oci_namespace,
            bucket_name=target_bucket,
            object_name=object_name,
            put_object_body=file_content.encode('utf-8')
        )
        logger.info("Successfully wrote object to bucket.")

        # 5. Return a success response
        return response.Response(
            ctx, 
            response_data=json.dumps({
                "status": "success",
                "message": "File written to bucket successfully.",
                "bucket": target_bucket,
                "object_name": object_name
            }),
            headers={"Content-Type": "application/json"}
        )

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)
        return response.Response(
            ctx, 
            response_data=json.dumps({
                "status": "error",
                "message": str(e)
            }),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )
