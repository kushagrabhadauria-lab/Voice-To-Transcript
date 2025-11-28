import os
import time
import requests
from datetime import datetime
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    Part,
    Content,
)
from google.genai.types import UploadFileConfig
import logging
from dotenv import load_dotenv
import threading
import time


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
        logging.info("📥 Downloading recording...")
        response = requests.get(self.url, timeout=60)
        response.raise_for_status()

        file_path = os.path.join(self.save_dir, filename)
        with open(file_path, "wb") as f:
            f.write(response.content)

        size_mb = len(response.content) / (1024 * 1024)
        logging.info(f"✅ Downloaded {size_mb:.2f} MB to {file_path}")
        return file_path



class GeminiFileManager:

    SMALL_FILE_LIMIT_MB = 20.0

    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

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
    

    def prepare_file(self, file_path):
        try:
            '''Return Part obj or file_obj according to file size'''
            if self.is_small_file(file_path):
                return self.upload_small_file(file_path), "small"

            else:
                return self.upload_large_file(file_path), "large"
            
        except Exception as err:
            raise(f"[ERROR] cannot upload file : {err}")
        


    def upload_file(self, file_path, mime_type="audio/mpeg", display_name="Call Recording"):
        logging.info("Uploading audio to Gemini...")
        try:
            config = UploadFileConfig(
                mime_type=mime_type,
                display_name=display_name
            )

            file_obj = self.client.files.upload(
                file=file_path,
                config=config
            )
            logging.info(f"Uploaded successfully: {file_obj.name}")
            return file_obj

        except Exception as e:
            logging.error(f"Failed to upload audio: {e}")
            raise

    
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
            logging.info(f"🧹 Deleted remote file: {file_name}")
        except Exception as e:
            logging.warning(f"Could not delete file: {e}")


class CallSummaryGenerator:
    FILTERED_SUMMARY_PROMPT = """
        You are an expert call analyst. Based on this call recording, provide ONLY the following sections:

         1️⃣ CALL TYPE
         - Call Type: (Inbound/Outbound, Support/Sales/Complaint/Inquiry)
         - Primary Language(s):

         2️⃣ OVERALL OUTCOME
         - Overall Outcome: (Resolved/Unresolved/Follow-up needed/Escalated)

         3️⃣ PARTICIPANTS
         For each speaker:
         - Name/Role: [exact name from intro or within the call]
         - Communication Style:
         - Key Characteristics:

         4️⃣ CALL PURPOSE & TOPIC
         - Main reason for call:
         - Customer’s concern/request:
         - Related issues discussed:

         5️⃣ RESOLUTION STATUS
         - Was the issue resolved: Yes/No/Partial
         - Customer Satisfaction Rating: [X/10]
         - Satisfaction Reasoning:
           * Initial tone
           * Emotional changes
           * Satisfaction indicators
           * End tone

         6️⃣ TONE & SENTIMENT ANALYSIS
         - Customer emotion: Beginning → End
         - Agent approach:
         - Interaction quality:
         - Escalation points:

         ⚠️ DO NOT include anything else.
         ⚠️ Ensure accurate identification of agent vs customer.
    """

    def __init__(self, api_key, model_name="gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name


    def call_gemini_with_retry(self, contents):
        max_retries = 5
        backoff = 1  # seconds

        attempt = 0

        while attempt < max_retries:
            try:
                pause_event.wait()   # Wait if system is paused

                response = self.client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                    config=GenerateContentConfig(temperature=0.2)
                )
                return response  # SUCCESS

            except Exception as e:
                if "503" in str(e):
                    logging.warning(f"503 error… thread {threading.get_ident()} attempt={attempt+1}")

                    # ONLY ONE THREAD HANDLES RETRIES
                    if retry_lock.acquire(blocking=False):
                        logging.warning("This thread is the RETRY MANAGER")

                        pause_event.clear()  # stop all other threads
                        time.sleep(backoff)

                        backoff *= 2
                        attempt += 1

                        pause_event.set()    # allow threads after backoff
                        retry_lock.release() # unlock so others go normally

                    else:
                        # Other threads only wait—not retry
                        logging.warning(f"Thread {threading.get_ident()} waiting during retry...")
                        pause_event.wait()   # blocked until retry thread resumes

                else:
                    raise e  # some other exception → not retryable

        raise RuntimeError("Gemini API returned 503 after 5 retries")


    def generate_summary(self, file_input, file_type):
        '''
            file_input:
                - SMALL FILE → Part object (Part.from_bytes)
                - LARGE FILE → file_info object returned from Gemini after upload
            file_type: "small" or "large"

        '''
        logging.info("Generating filtered call summary...")

        model = self.client.models
        
        config = GenerateContentConfig(temperature=0.2)

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

        # response = model.generate_content(
        #     model="gemini-2.5-flash",
        #     contents=[Content(parts=parts)],
        #     config=config
        # )

        response = self.call_gemini_with_retry([Content(parts=parts)])

        summary = response.text        

        if not summary:
            raise ValueError("Empty summary after retry.")

        logging.info("Summary generated successfully!")
        return summary.strip()


class CallSummaryPipeline:
    def __init__(self, api_key, recording_url=None, file_path=None):
        self.api_key = api_key
        self.recording_url = recording_url
        self.file_path = None
        self.downloader = AudioDownloader(recording_url)
        self.manager = GeminiFileManager(api_key)
        self.generator = CallSummaryGenerator(api_key)


    def set_file_path(self, file_path):
        self.file_path = file_path

    def run(self):
        audio_path = None
        try:
            logging.info("Starting filtered call summary extraction...")
            if not self.file_path and not self.recording_url:
                logging.error("Please provide file_path or recording_url")
                return None
            
            if self.recording_url:
                audio_path = self.downloader.download()

            else:
                audio_path = self.file_path


            file_obj_or_part, file_type = self.manager.prepare_file(audio_path)
            
            # if file_type "large"
            if file_type == "large":
                file_obj_or_part = self.manager.wait_until_ready(file_obj_or_part)

            #generate summary

            summary = self.generator.generate_summary(file_obj_or_part, file_type)
            logging.info(f"Length: {len(summary)} characters")
            return summary

        except Exception as e:
            logging.error(f"Error: {e}")
            raise
        



if __name__ == "__main__":
    load_dotenv()
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    RECORDING_URL = None
    FILE_PATH = os.getcwd()+"/downloads/call_19.mp3"

    start_time = datetime.now()
    logging.info(f"Started processing at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    pipeline = CallSummaryPipeline(GEMINI_KEY, RECORDING_URL)
    pipeline.set_file_path(FILE_PATH)
    summary = pipeline.run()

    end_time = datetime.now()
    duration = end_time - start_time

    logging.info(f"Finished processing at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Total time taken: {duration.total_seconds():.2f} seconds")

