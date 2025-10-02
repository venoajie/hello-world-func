
# main.py - DIAGNOSTIC VERSION 2.0
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
            
            # --- THE FIX ---
            # Pre-calculate the boolean value to avoid the f-string SyntaxError.
            has_literal_newline = '\\n' in private_key
            logger.info(f"OCI_PRIVATE_KEY_CONTENT contains literal '\\n': {has_literal_newline}")
        else:
            logger.error("FATAL: OCI_PRIVATE_KEY_CONTENT is NOT SET in the environment.")

    except Exception as e:
        logger.critical(f"An unexpected error occurred during diagnostic startup: {e}", exc_info=True)
    
    logger.info("--- DIAGNOSTIC COMPLETE. Forcing exit. ---")
    raise SystemExit("Debug run finished.")

    yield

# --- FastAPI Application ---
app = FastAPI(title="Diagnostic Tool", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "ok"}