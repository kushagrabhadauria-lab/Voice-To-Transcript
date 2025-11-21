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


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


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
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

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

    def generate_summary(self, file_info):
        logging.info("Generating filtered call summary...")

        model = self.client.models
        
        config = GenerateContentConfig(temperature=0.2)

        parts = [
            Part.from_uri(file_uri = file_info.uri, mime_type=file_info.mime_type),
            Part.from_text(text = self.FILTERED_SUMMARY_PROMPT),
        ]

        response = model.generate_content(
            model="gemini-2.5-flash",
            contents=[Content(parts=parts)],
            config=config
        )

        summary = response.text
        if not summary:
            logging.warning("Blank response, retrying...")
            parts.append(
                Part.from_text(text="If unclear, summarize based on audible sections only.")
            )
            response = model.generate_content(model="gemini-2.5-flash", contents=[Content(parts=parts)], config=config)
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
        uploaded_name = None
        try:
            logging.info("Starting filtered call summary extraction...")
            if not self.file_path and not self.recording_url:
                logging.error("Please provide file_path or recording_url")
                return None
            
            if self.recording_url:
                audio_path = self.downloader.download()

            else:
                audio_path = self.file_path

            file_obj = self.manager.upload_file(audio_path)
            uploaded_name = file_obj.name

            ready_file = self.manager.wait_until_ready(file_obj)
            summary = self.generator.generate_summary(ready_file)

            # timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            # summary_path = f"filtered_summary_{timestamp}.txt"
            # with open(summary_path, "w") as f:
            #     f.write(summary)

            # logging.info(f"Summary saved to: {summary_path}")
            logging.info(f"Length: {len(summary)} characters")
            return summary

        except Exception as e:
            logging.error(f"Error: {e}")
            raise
        
        # finally:
        #     if uploaded_name:
        #         self.manager.delete_file(uploaded_name)
        #     if audio_path and os.path.exists(audio_path):
        #         os.remove(audio_path)
        #         logging.info("Local audio file deleted.")



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

