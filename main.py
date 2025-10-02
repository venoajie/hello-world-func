
# main.py - DIAGNOSTIC VERSION
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Lifespan Manager for Diagnostics ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("--- DIAGNOSTIC STARTUP ---")
    
    try:
        # We will read all the critical environment variables
        user_ocid = os.getenv("OCI_USER_OCID")
        tenancy_ocid = os.getenv("OCI_TENANCY_OCID")
        fingerprint = os.getenv("OCI_FINGERPRINT")
        region = os.getenv("OCI_REGION")
        private_key = os.getenv("OCI_PRIVATE_KEY_CONTENT")

        # --- Log the results for inspection ---
        logger.info(f"OCI_USER_OCID: {user_ocid}")
        logger.info(f"OCI_TENANCY_OCID: {tenancy_ocid}")
        logger.info(f"OCI_FINGERPRINT: {fingerprint}")
        logger.info(f"OCI_REGION: {region}")

        if private_key:
            logger.info(f"OCI_PRIVATE_KEY_CONTENT length: {len(private_key)}")
            logger.info(f"OCI_PRIVATE_KEY_CONTENT starts with: {private_key[:35]}")
            logger.info(f"OCI_PRIVATE_KEY_CONTENT ends with: {private_key[-35:]}")
            # This will reveal if newlines are being converted to literal '\n'
            logger.info(f"OCI_PRIVATE_KEY_CONTENT contains literal '\\n': {'\\n' in private_key}")
        else:
            logger.error("FATAL: OCI_PRIVATE_KEY_CONTENT is NOT SET in the environment.")

    except Exception as e:
        logger.critical(f"An unexpected error occurred during diagnostic startup: {e}", exc_info=True)
    
    # We will stop the application cleanly after logging.
    # This prevents it from hanging or throwing other errors.
    logger.info("--- DIAGNOSTIC COMPLETE. Forcing exit. ---")
    # NOTE: This will cause a "ContainerInitFail" error, which is EXPECTED.
    # We only care about the logs produced before the failure.
    raise SystemExit("Debug run finished.")

    yield # This part will not be reached

# --- FastAPI Application ---
app = FastAPI(title="Diagnostic Tool", lifespan=lifespan)

@app.get("/")
async def root():
    # This endpoint will never be reached, which is intended.
    return {"status": "ok"}