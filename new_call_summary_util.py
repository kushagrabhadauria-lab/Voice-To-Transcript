import os
import time
import requests
import json
import random # Added for jitter in backoff
from datetime import datetime
from google.genai.types import (
    GenerateContentConfig,
    Part,
    Content,
)
from google.genai.types import UploadFileConfig
import logging
import threading



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

pause_event = threading.Event()
pause_event.set()  # initially threads can run
retry_lock = threading.Lock()


class AudioDownloader:
    '''
        Audio Downloader class to download the audio
    '''
    def __init__(self, url, save_dir="temp"):
        self.url = url
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    
    def download(self, filename="recording.mp3"):
        logging.info("Downloading recording...")
        
        # Ensure 'temp' directory exists
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

        # Use datetime for unique filename if URL is provided
        if self.url:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"recording_{timestamp}.mp3"

        response = requests.get(self.url, timeout=60)
        response.raise_for_status()

        file_path = os.path.join(self.save_dir, filename)
        with open(file_path, "wb") as f:
            f.write(response.content)

        size_mb = len(response.content) / (1024 * 1024)
        logging.info(f"Downloaded {size_mb:.2f} MB to {file_path}")
        return file_path


# --- CLASS UPDATED: Accepts client object instead of api_key ---
class GeminiFileManager:

    SMALL_FILE_LIMIT_MB = 20.0

    def __init__(self, client): # <-- Changed from api_key
        self.client = client # <-- Use the authenticated client

    def is_small_file(self, file_path):
        '''helper function to check if file is less than LIMIT.'''
        size_mb = os.path.getsize(file_path)/ (1024*1024)
        return size_mb<=self.SMALL_FILE_LIMIT_MB


    def upload_small_file(self, file_path):
        '''Uploading files which are less than LIMIT directly. No file api'''
        logging.info("Uploading small file directly with Part.from_bytes()")
        try:
            with open(file_path, "rb") as f:
                data = f.read()

            return Part.from_bytes(
                data=data,
                mime_type="audio/mpeg"
            )
        
        except Exception as err:
            logging.error(f"Failed to upload audio: {err}")
            raise # Re-raise error for pipeline to catch

    
    def upload_large_file(self, file_path):
        """Upload via Gemini File API."""
        try:
            logging.info("Uploading large file using client.files.upload()")
            config = UploadFileConfig(
                mime_type="audio/mpeg",
                display_name="Call Recording"
            )
            file_obj = self.client.files.upload(file=file_path, config=config)
            return file_obj
        
        except Exception as err:
            logging.error(f"Failed to upload audio: {err}")
            raise

    
    def prepare_file(self, file_path):
        try:
            '''Return Part obj or file_obj according to file size'''
            if self.is_small_file(file_path):
                return self.upload_small_file(file_path), "small"

            else:
                return self.upload_large_file(file_path), "large"
            
        except Exception as err:
            raise RuntimeError(f"[ERROR] cannot upload file : {err}")
        


    def wait_until_ready(self, file_obj):
        logging.info("Waiting for file to process...")
        while True:
            file_info = self.client.files.get(name = file_obj.name)
            if file_info.state.name != "PROCESSING":
                logging.info("File ready!")
                return file_info
            time.sleep(2)

    
    def delete_file(self, file_name):
        try:
            self.client.files.delete(name = file_name)
            logging.info(f"Deleted remote file: {file_name}")
        except Exception as e:
            logging.warning(f"Could not delete remote file {file_name}: {e}")

# --- CLASS UPDATED: Accepts client object instead of api_key ---
class CallSummaryGenerator:
    FILTERED_SUMMARY_PROMPT = """
        # ROLE
    You are an expert Call Quality Analyst specializing in Customer Satisfaction (CSAT) and Agent Performance.

    # TASK
    Analyze the provided call recording and generate a comprehensive CSAT report. You must provide evidence for every score given.

    # ANALYSIS GUIDELINES
    - OBJECTIVITY: Score based on explicit verbal cues and outcomes, not assumptions.
    - DIFFERENTIATION: Clearly identify the CUSTOMER and the AGENT.
    - EVIDENCE-BASED: For every score, provide a specific quote or reference from the call.
    - SCORING: Strictly follow the 0â€“10 scale. Use decimals (e.g., 7.5) if necessary for nuance.

    # SCORING FRAMEWORK
    
    1. ISSUE RESOLUTION STATUS (30%)
       - 9-10: Issue fully resolved; no further action needed.
       - 6-8: Partial resolution; clear follow-up path established.
       - 2-5: Unresolved; vague next steps; customer left confused.
       - 0-1: No resolution; customer requested escalation or refund.

    2. CUSTOMER SENTIMENT TRAJECTORY (10%)
       - 8-10: Negative/Neutral start -> Strong Positive/Appreciative end.
       - 4-7: Negative start -> Neutral/Calm end.
       - 0-3: Negative start -> Negative/Aggravated end (or worsened).

    3. CUSTOMER TRUST & CONFIDENCE (10%)
       - 8-10: Customer explicitly thanks agent or confirms future business.
       - 4-7: Customer is compliant but shows no high enthusiasm.
       - 0-3: Customer expresses doubt, threatens to cancel, or asks for manager.

    4. AGENT HANDLING QUALITY (30%)
       - 8-10: High empathy, active listening, clear technical explanations.
       - 5-7: Professional and polite, but lacked deep empathy or struggled with technicals.
       - 0-4: Defensive, rude, interrupted the customer, or provided incorrect info.

    5. CLOSURE QUALITY (20%)
       - 8-10: Clear summary of action items; polite sign-off; customer satisfied with end.
       - 4-7: Standard sign-off; no summary of next steps.
       - 0-3: Call cut off abruptly or customer ended the call in anger.

    # OUTPUT STRUCTURE (DO NOT ALTER HEADINGS)

    ## 1. CALL OVERVIEW
    - **Call Type:** [Inbound/Outbound] | [Support/Sales/Complaint]
    - **Language:** - **Outcome:** [Resolved/Unresolved/Escalated]

    ## 2. PARTICIPANTS
    - **Agent:** [Name/Role] | [Style: e.g., Patient, Authoritative, Passive]
    - **Customer:** [Name] | [Style: e.g., Frustrated, Tech-savvy, Distressed]

    ## 3. CALL PURPOSE & KEY TOPICS
    - **Primary Concern:** - **Technical/Secondary Issues:**

    ## 4. CSAT SCORECARD
        a) **ISSUE RESOLUTION ASSESSMENT**
        - **Score:** [0-10]/10
        - **Justification:** [Single sentence with specific evidence or quote]

        b) **CUSTOMER SENTIMENT TRAJECTORY**
        - **Score:** [0-10]/10
        - **Justification:** [Single sentence with specific evidence or quote]

        c) **CUSTOMER TRUST & CONFIDENCE**
        - **Score:** [0-10]/10
        - **Justification:** [Single sentence with specific evidence or quote]

        d) **AGENT HANDLING QUALITY**
        - **Score:** [0-10]/10
        - **Justification:** [Single sentence with specific evidence or quote]

        e) **CLOSURE QUALITY**
        - **Score:** [0-10]/10
        - **Justification:** [Single sentence with specific evidence or quote]

    ## 5. FINAL ASSESSMENT
    - **Normalized CSAT (0-10):** [Weighted Average]
    - **Executive Summary:** [3-sentence summary of why this score was given.]
    - **Actionable Coaching Tip:** [Specific things the agent could do better next time.]
    """

    def __init__(self, client, model_name="gemini-2.5-flash"): 
        self.client = client 
        self.model_name = model_name


    def call_gemini_with_retry(self, contents):
        max_retries = 5
        base_backoff = 1 

        attempt = 0

        while attempt < max_retries:
            try:
                pause_event.wait() 
                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config=GenerateContentConfig(temperature=0.2)
                )

                return response

            except Exception as e:
                # Check for transient errors (503 Service Unavailable, 429 Rate Limit)
                if "503" in str(e) or "429" in str(e):
                    logging.warning(f"Transient error (503/429) caught: {e}. Thread {threading.get_ident()} attempt={attempt+1}")

                    if retry_lock.acquire(blocking=False):
                        logging.warning("This thread is the RETRY MANAGER. Pausing others.")
                        
                        try:
                            pause_event.clear()  
                            # Exponential backoff with Jitter
                            wait_time = min(60, (base_backoff * (2 ** attempt)) + random.uniform(0, 1))
                            logging.info(f"Retrying in {wait_time:.2f} seconds...")
                            time.sleep(wait_time)
                            attempt += 1
                            pause_event.set()    
                        finally:
                            retry_lock.release()
                    else:
                        logging.warning(f"Thread {threading.get_ident()} waiting during retry...")
                        pause_event.wait()
                else:
                    # Non-retryable exception
                    raise e

        raise RuntimeError(f"Gemini API returned transient error after {max_retries} retries.")


    def generate_summary(self, file_input, file_type):
        '''
            Generates summary using the file input.
        '''
        logging.info("Generating filtered call summary...")
        if file_type == "large":
            # file_input is a Gemini file_info object
            parts = [
                Part.from_uri(
                    file_uri=file_input.uri,
                    mime_type=file_input.mime_type
                ),
                Part.from_text(text=self.FILTERED_SUMMARY_PROMPT),
            ]
        else:
            # file_input is already a Part.from_bytes object
            parts = [
                file_input,
                Part.from_text(text=self.FILTERED_SUMMARY_PROMPT),
            ]
        response = self.call_gemini_with_retry([Content(parts=parts, role="user")])
        summary = response.text        

        if not summary:
            raise ValueError("Empty summary after retry.")

        logging.info("Summary generated successfully!")
        return summary.strip()


# --- CLASS UPDATED: Added Service Account Logic and Cleanup ---
class CallSummaryPipeline:
    
    # Removed api_key from __init__
    def __init__(self, gcp_client, recording_url=None, file_path=None):
        # 1. AUTHENTICATE AND CREATE CLIENT
        self.client = gcp_client
        
        # 2. INITIALIZE SUB-CLASSES WITH THE CLIENT
        self.recording_url = recording_url
        self.file_path = None
        self.downloader = AudioDownloader(recording_url)
        # Pass the authenticated client
        self.manager = GeminiFileManager(self.client) 
        self.generator = CallSummaryGenerator(self.client)



    def set_file_path(self, file_path):
        self.file_path = file_path

    def run(self):
        audio_path = None
        file_name_to_delete = None
        
        try:
            logging.info("Starting filtered call summary extraction...")
            if not self.file_path and not self.recording_url:
                logging.error("Please provide file_path or recording_url")
                return None
            
            # 1. Audio Download/Path Setup
            if self.recording_url:
                audio_path = self.downloader.download() 
            else:
                audio_path = self.file_path

            # 2. File Preparation (Upload or Part Creation)
            file_obj_or_part, file_type = self.manager.prepare_file(audio_path)
            
            if file_type == "large":
                # Wait for processing and capture the remote file name for cleanup
                file_obj_or_part = self.manager.wait_until_ready(file_obj_or_part)
                file_name_to_delete = file_obj_or_part.name

            # 3. Generate Summary
            summary = self.generator.generate_summary(file_obj_or_part, file_type)
            logging.info(f"Length: {len(summary)} characters")
            return summary

        except Exception as e:
            logging.error(f"Pipeline Error: {e}")
            raise

        finally:
            # 4. CLEANUP
            # Delete the remote file if it was a large upload
            if file_name_to_delete:
                self.manager.delete_file(file_name_to_delete)
            
            # Delete the local downloaded file if the URL was provided
            # Only delete if we performed the download (i.e., recording_url was set)
            if self.recording_url and audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                    logging.info(f"Deleted local file: {audio_path}")
                except Exception as e:
                    logging.warning(f"Could not delete local file {audio_path}: {e}")
# -----------------------------------------------------------


if __name__ == "__main__":
    
    # NOTE: .env and GEMINI_KEY are no longer needed
    
    RECORDING_URL = "https://cloudphone.tatateleservices.com/file/recording?callId=f41829f2-5f02-4710-b31a-8ea7820d2421&type=rec&token=Y1A3eWtzUjh5ckF2bjlyQlRvaUhIdTc0OXluQmxsVkVpcGxRWmhNUUhQd1k5Y3FoZVdrVk90d1Jja253WEVVYzo6YWIxMjM0Y2Q1NnJ0eXl1dQ%3D%3D" # Set to None if using local file
    # Use an existing local file if RECORDING_URL is None
    FILE_PATH = None 

    if RECORDING_URL is None and not os.path.exists(FILE_PATH):
        logging.error(f"FATAL: Local file not found at {FILE_PATH}. Please check the path or provide a URL.")
        exit(1)


    start_time = datetime.now()
    logging.info(f"Started processing at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        # Initialize pipeline without API Key
        pipeline = CallSummaryPipeline(recording_url=RECORDING_URL) 
        if RECORDING_URL is None:
             pipeline.set_file_path(FILE_PATH)
             
        summary = pipeline.run()
        print("summary: ", summary)
        end_time = datetime.now()
        duration = end_time - start_time

        logging.info(f"\n--- GENERATED SUMMARY ---\n{summary}\n-------------------------")
        logging.info(f"Finished processing at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logging.info(f"Total time taken: {duration.total_seconds():.2f} seconds")
    
    except Exception as e:
        logging.error(f"Pipeline failed: {e}")