import os
import random
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.objects.calls import SimplePublicObjectInput
from hubspot.crm.objects import ApiException
import openai

# ========================
# Load Environment Variables
# ========================
load_dotenv()

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./downloads")

if not HUBSPOT_TOKEN:
    raise RuntimeError("HUBSPOT_TOKEN not found. Set it in your .env file.")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not found. Set it in your .env file.")

openai.api_key = OPENAI_API_KEY


# ========================
# HubSpot Client
# ========================
class HubSpotClient:
    """Handles HubSpot API operations for calls."""

    def __init__(self, access_token: str):
        self.client = HubSpot(access_token=access_token)

    def get_calls_with_recordings(self, limit: int = 100):
        """
        Fetch calls that have a recording URL and don't have transcription yet.
        """
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup

        filters = [
            Filter(property_name="hs_call_recording_url", operator="HAS_PROPERTY"),
            Filter(property_name="model_to_hb_transcription", operator="NOT_HAS_PROPERTY")
        ]
        filter_group = FilterGroup(filters=filters)

        search_request = PublicObjectSearchRequest(
            filter_groups=[filter_group],
            limit=limit,
            properties=["hs_call_recording_url", "hs_call_start_time"]
        )

        try:
            results = self.client.crm.objects.calls.search_api.do_search(public_object_search_request=search_request)
            return results.results
        except ApiException as e:
            print(f"❌ Error fetching calls with recordings: {e}")
            return []

    def get_calls_without_recordings(self, limit: int = 100):
        """
        Fetch calls that do NOT have a recording URL.
        """
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup

        filter_ = Filter(property_name="hs_call_recording_url", operator="NOT_HAS_PROPERTY")
        filter_group = FilterGroup(filters=[filter_])
        search_request = PublicObjectSearchRequest(filter_groups=[filter_group], limit=limit)

        try:
            results = self.client.crm.objects.calls.search_api.do_search(public_object_search_request=search_request)
            with open("logs/skipped_files.txt", "a") as skipped_file:
                for call in results.results:
                    curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    skipped_file.write(f"[{curr_time_stamp}] Call id: {call.id} — no recording\n")
            return results.results
        except ApiException as e:
            print(f"❌ Error fetching calls without recordings: {e}")
            return []

    def update_call_transcription(self, call_id: str, message: str):
        """Update HubSpot call property 'model_to_hb_transcription'"""
        update_obj = SimplePublicObjectInput(properties={"model_to_hb_transcription": message})
        try:
            self.client.crm.objects.calls.basic_api.update(
                call_id=call_id,
                simple_public_object_input=update_obj
            )
            print(f"✅ Updated model_to_hb_transcription for call {call_id}")
        except ApiException as e:
            curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("logs/failed_files.txt", 'a') as failed_file:
                failed_file.write(f"[{curr_time_stamp}] Call id: {call_id} — update failed: {e}\n")
            print(f"❌ Failed to update call {call_id}: {e}")


# ========================
# Audio Manager
# ========================
class AudioManager:
    """Handles recording downloads."""

    def __init__(self, output_dir: str = "./downloads"):
        os.makedirs(output_dir, exist_ok=True)
        self.output_dir = output_dir

    def download_recording(self, call_id: str, rec_url: Optional[str]) -> Optional[str]:
        """Download the audio file if possible."""
        if not rec_url:
            return None
        try:
            file_id = rec_url.split("/")[-2] if "drive.google.com" in rec_url else call_id
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            local_path = os.path.join(self.output_dir, f"{call_id}.mp3")

            response = requests.get(download_url, stream=True, timeout=30)
            if response.status_code == 200:
                with open(local_path, "wb") as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                print(f"🎧 Downloaded: {local_path}")
                return local_path
            else:
                print(f"⚠️ Download failed (status {response.status_code}) for {call_id}")
        except Exception as e:
            print(f"❌ Error downloading for {call_id}: {e}")
        return None


# ========================
# Transcription Handler
# ========================

class Transcriber:
    """Handles OpenAI transcription process."""

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def transcribe_audio(self, file_path: str) -> str:
        """Transcribe using Whisper model (new OpenAI API syntax)."""
        try:
            with open(file_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model="gpt-4o-transcribe",
                    file=audio_file
                )
            return transcript.text
        except Exception as e:
            print(f"❌ Transcription failed for {file_path}: {e}")
            return ""


# ========================
# Call Processor
# ========================
class CallProcessor:
    """Main processor for recent calls."""

    def __init__(self, hubspot_token: str, output_dir: str = "./downloads"):
        self.hub = HubSpotClient(hubspot_token)
        self.audio_mgr = AudioManager(output_dir)
        self.transcriber = Transcriber()

    def process_calls(self):
        """Fetch, download, transcribe, and update calls."""
        os.makedirs("logs", exist_ok=True)
        try:
            calls = self.hub.get_calls_with_recordings()
            self.hub.get_calls_without_recordings()
            print(f"\n📞 Found {len(calls)} call(s) ready for transcription.\n")

            for call in calls:
                call_id = call.id
                rec_url = call.properties.get("hs_call_recording_url")

                print(f"➡️ Processing Call ID: {call_id}")
                if not rec_url:
                    print("⚠️ No recording URL — skipping.\n")
                    continue

                # Step 1: Download Recording
                mp3_path = self.audio_mgr.download_recording(call_id, rec_url)
                if not mp3_path:
                    continue

                # Step 2: Transcribe Audio
                transcript_text = self.transcriber.transcribe_audio(mp3_path)
                if not transcript_text.strip():
                    print(f"⚠️ Empty transcription for {call_id}, skipping update.\n")
                    continue

                # Step 3: Update HubSpot
                self.hub.update_call_transcription(call_id, transcript_text)

                # Step 4: Log Success
                curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open("logs/success_files.txt", "a") as success_files:
                    success_files.write(f"[{curr_time_stamp}] Call id: {call_id} processed successfully.\n")

            print("\n🎯 Processing complete.\n")

        except Exception as err:
            curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("logs/failed_files.txt", "a") as failed_txt:
                failed_txt.write(f"[{curr_time_stamp}] Error: {err}\n")
            print(f"❌ Fatal error: {err}")


# ========================
# Entry Point
# ========================
if __name__ == "__main__":
    processor = CallProcessor(HUBSPOT_TOKEN, output_dir=OUTPUT_DIR)
    processor.process_calls()
