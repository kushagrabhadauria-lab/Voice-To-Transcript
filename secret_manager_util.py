# --- Google Cloud Authentication Imports ---
from google.cloud import secretmanager
from google.oauth2 import service_account
import json
from google import genai
import logging
import google.api_core.exceptions as gcp_exceptions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)



# class GcpConfig:
#     '''
#         GCP configs and authentication functions
#     '''
#     PROJECT_ID = "52019818198" # e.g., "my-transcription-project-12345" 
#     # Vertex AI region for Gemini access
#     REGION = "us-central1"        
#     # The full resource path of your Service Account Key in Secret Manager
#     SECRET_RESOURCE_NAME = "projects/52019818198/secrets/mec-trasnscript-service-key/versions/latest" 
#     SCOPES = ['https://www.googleapis.com/auth/cloud-platform']
    
    
#     def _get_service_account_key(self):
#         """Retrieves the SA key JSON string from Secret Manager."""
#         logging.info(f"Fetching Secret Manager key: {self.SECRET_RESOURCE_NAME}")

#         sm_client = secretmanager.SecretManagerServiceClient()
        
#         try:
#             # Use the defined constant for the full resource name
#             resp = sm_client.access_secret_version(request={"name": self.SECRET_RESOURCE_NAME})
#             sa_key_json_string = resp.payload.data.decode("utf-8")
#             logging.info("Successfully retrieved service account key.")
#             return json.loads(sa_key_json_string) 
        
#         except gcp_exceptions.NotFound:
#             logging.error("Secret not found in Secret Manager.")
#             raise

#         except gcp_exceptions.PermissionDenied:
#             logging.error("Permission denied when accessing Secret Manager.")
#             raise

#         except Exception as e:
#             logging.exception("Unexpected error while fetching SA key.")
#             raise RuntimeError("Failed to bootstrap credentials.") from e



#     def _create_authenticated_client(self):
#         """Creates an in-memory authenticated genai.Client using the SA key."""
#         # 1. Get SA key info as a dictionary
#         logging.info("Creating authenticated GenAI client...")
#         sa_key_info = self._get_service_account_key()
        
#         # 2. Create in-memory credentials object
#         try:
#             target_credentials = service_account.Credentials.from_service_account_info(
#                 sa_key_info,
#                 scopes=self.SCOPES
#             )
#             logging.info("Credentials created successfully.")
            
#         except Exception as e:
#             raise
        
#         # 3. Create the Gen AI Client, specifying Vertex AI backend and credentials
#         client = genai.Client(
#             vertexai=True,              # CRITICAL: Use Vertex AI endpoint
#             project=self.PROJECT_ID,
#             location=self.REGION,
#             credentials=target_credentials
#         )

#         logging.info("GenAI client initialized successfully.")
#         return client

from google.cloud import secretmanager
from google import genai
import logging

logging.basicConfig(level=logging.INFO)

class GcpConfig:
    PROJECT_ID = "52019818198"
    REGION = "us-central1"

    def _create_authenticated_client(self):
        logging.info("Creating GenAI client using ADC...")

        client = genai.Client(
            vertexai=True,
            project=self.PROJECT_ID,
            location=self.REGION
        )

        logging.info("GenAI client initialized successfully.")
        return client
