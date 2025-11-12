import os
import random
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.objects.calls import SimplePublicObjectInput
from hubspot.crm.objects import ApiException

load_dotenv()

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./downloads")

if not HUBSPOT_TOKEN:
    raise RuntimeError("HUBSPOT_TOKEN not found. Set it in your .env file.")


class HubSpotClient:
    """Handles HubSpot API operations for calls."""

    def __init__(self, access_token: str):
        self.client = HubSpot(access_token=access_token)

    def get_recent_calls_by_endtime(self, hours: int = 6, limit: int = 100):
        """
        Fetch calls whose hs_call_start_time is within last `hours`.
        """
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup

        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
        since_timestamp = int(since.timestamp() * 1000)

        filter_ = Filter(
            property_name="hs_call_start_time",
            operator="GTE",
            value=str(since_timestamp)
        )
        filter_group = FilterGroup(filters=[filter_])

        search_request = PublicObjectSearchRequest(
            filter_groups=[filter_group],
            limit=limit,
            properties=["hs_call_recording_url", "hs_call_start_time"]
        )

        try:
            results = self.client.crm.objects.calls.search_api.do_search(public_object_search_request=search_request)
            return results.results
        except ApiException as e:
            print(f"Error fetching calls by end time: {e}")
            return []

    def get_calls_with_recordings(self, limit: int = 100):
        """
        Fetch calls that have a recording URL (existing ones).
        Useful for processing past calls that already exist.
        """
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup

        # Filter: hs_call_recording_url is known (not null)
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
            print(f"Error fetching calls with recordings: {e}") # No recording found
            return []


    def get_calls_without_recordings(self, limit: int = 100):
        """
            Fetch calls that do NOT have a recording URL.
            Useful for identifying unrecorded or missing-recording calls.
        """
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup
        from hubspot.crm.objects.calls.exceptions import ApiException

        # Filter: hs_call_recording_url is NOT present
        filter_ = Filter(property_name="hs_call_recording_url", operator="NOT_HAS_PROPERTY")
        filter_group = FilterGroup(filters=[filter_])

        search_request = PublicObjectSearchRequest(
            filter_groups=[filter_group],
            limit=limit,
            properties=["hs_call_start_time", "hs_call_title"]
        )

        try:
            results = self.client.crm.objects.calls.search_api.do_search(
                public_object_search_request=search_request
            )

            with open("logs/skipped_files.txt", "a") as skipped_file:
                for call in results.results:
                    curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    skipped_file.write(f"[{curr_time_stamp}] Call id: {call.id} not processed\n")
            
            return results.results
        
        except ApiException as e:
            print(f"Error fetching calls without recordings: {e}")
            return []


    def update_call_transcription(self, call_id: str, message: str):
        """Update custom property 'model_to_hb_transcription'"""
        update_obj = SimplePublicObjectInput(properties={"model_to_hb_transcription": message})
        try:
            self.client.crm.objects.calls.basic_api.update(
                call_id=call_id,
                simple_public_object_input=update_obj
            )
            print(f" Updated model_to_hb_transcription for call {call_id}")
        except ApiException as e:
            with open("logs/failed_files.txt", 'a') as failed_file:
                curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                failed_file.write(f"[{curr_time_stamp}] Call id: {call_id} failed to update call : {e}\n")
            
            print(f"Failed to update call {call_id}: {e}")


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
                print(f"🎧 Downloaded recording to {local_path}")
                return local_path
            else:
                print(f"⚠️ Failed to download recording (status {response.status_code}) for {call_id}")
        except Exception as e:
            print(f"Error downloading for {call_id}: {e}")

        return None


class CallProcessor:
    """Main processor for recent calls."""

    FAKE_MESSAGES = [
        '''FILTERED CALL SUMMARY
Generated: 10/8/2025, 12:47:42 PM
Audio File Size: 0.39 MB
======================================================================

**1. CALL TYPE**
Call Type: Outbound, Support/Inquiry (Agent initiated call to inform customer about a complimentary service)
Primary Language(s): English

**2. OVERALL OUTCOME**
Overall Outcome: Follow-up needed

**3. PARTICIPANTS**
Name/Role: Kritika / Support Agent
    - Communication Style: Professional, clear, informative, patient
    - Key Characteristics: Systematically gathered information, explained the service and offer details, confirmed details, and outlined next steps.
Name/Role: Customer / Business Owner/Representative
    - Communication Style: Calm, professional, cooperative, cautious
    - Key Characteristics: Provided requested information, asked clarifying questions, indicated a need for internal discussion before proceeding.

**4. CALL PURPOSE & TOPIC**
Main reason for the call: Kritika (Agent) called to inform the Customer about a complimentary Meta Ads service they are entitled to after purchasing a "Gonuka plan" and to gather necessary details for its setup.
Customer's primary concern/request: To understand the details of the Meta Ads service, provide accurate business information, clarify the offer, and understand the process.
Related issues discussed:
    - Confirmation of contact numbers.
    - Confirmation of business name ("Prana Hyperbaric Oxygen Therapy Center") and email ID.
    - Confirmation of the specific business address for the service (Borivali branch).
    - Desired geographical location for running the Meta Ads (entire Western Line).
    - Details of the Meta Ads offer (reduced price of 3000 from 4500, plus one free session).
    - Age (5-88 years) and gender (both male and female) criteria for their customers.
    - Request for business logo and specific ad requirements.
    - Explanation of the authorization process (linking Facebook, Instagram, WhatsApp).
    - Clarification on the type of business/services offered (Hyperbaric Oxygen Therapy for medical treatment).

**5. RESOLUTION STATUS**
Was the issue resolved: No
**Customer Satisfaction Rating: 7/10**
**Satisfaction Reasoning:**
  *   Initial mood/tone at call beginning: The customer's tone was neutral and professional at the start of the call.
  *   Emotional changes during the call: The customer maintained a calm and professional demeanor throughout the call. There were no indications of frustration, confusion, or significant emotional shifts.
  *   Specific moments that indicate satisfaction or dissatisfaction: The customer was cooperative in providing information and asking clarifying questions, indicating engagement and a willingness to understand. However, the customer explicitly stated, "I'll discuss with the directors and get back to you," which shows that a final decision or full commitment has not been made, and the issue is not fully resolved from their perspective.
  *   Whether their questions were answered: All questions posed by the customer were clearly and patiently answered by the agent.
  *   Whether they received what they wanted: The customer received all the necessary information about the complimentary service, its offer, and the setup process, which was the immediate goal of the call.
  *   Tone at the end of the call: The tone at the end was neutral and professional, with a clear plan for a follow-up.
  *   Any explicit statements of satisfaction or dissatisfaction: There were no explicit statements of satisfaction or dissatisfaction.
  *   Overall engagement level: Both the agent and the customer were highly engaged in the conversation, ensuring all details were covered.
  *   The customer's receptiveness and the agent's thoroughness contribute to a positive interaction, but the need for internal consultation prevents a higher satisfaction score, as the ultimate outcome is still pending.

**6. TONE & SENTIMENT ANALYSIS**
Customer's emotional state: Neutral/Calm → Neutral/Calm
Agent's approach: Professional, clear, patient, and helpful. Kritika maintained a structured approach, ensuring all necessary information was exchanged and questions were addressed.
Overall interaction quality: Good. The communication was effective, polite, and efficient, with both parties demonstrating professionalism.
Any escalation points: None. The conversation proceeded smoothly without any conflicts or need for escalation.

======================================================================
END OF DOCUMENT''',
    ]

    def __init__(self, hubspot_token: str, output_dir: str = "./downloads"):
        self.hub = HubSpotClient(hubspot_token)
        self.audio_mgr = AudioManager(output_dir)

    @staticmethod
    def random_message() -> str:
        """Return a simple random message."""
        return random.choice(CallProcessor.FAKE_MESSAGES)

    def process_calls(self, hours: int = 6):
        """
        mode = "recent" → last X hours by end time
        mode = "existing" → all calls with recordings
        """
        try:

            calls = self.hub.get_calls_with_recordings()
            self.hub.get_calls_without_recordings()
            print(f"Found {len(calls)} existing call(s) with recordings.\n")

            for call in calls:
                try:
                    call_id = call.id
                    rec_url = call.properties.get("hs_call_recording_url")
                    end_time = call.properties.get("hs_call_start_time")

                    print(f"➡️ Processing Call ID: {call_id} | End Time: {end_time}")
                    if rec_url:
                        self.audio_mgr.download_recording(call_id, rec_url)
                    else:
                        print("No recording URL found — skipping download.")

                    message = self.random_message()
                    self.hub.update_call_transcription(call_id, message)

                    with open("logs/success_files.txt", "a") as success_files:
                        curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        success_files.write(f"[{curr_time_stamp}] Call id: {call_id} proccessed successfully.\n")

                except Exception as err:
                    with open("logs/failed_files.txt", "a") as failed_txt:
                        curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        failed_txt.writelines(f"[{curr_time_stamp}] Call id: {call_id} not processed | error: {err}\n")

                    print(f"Call id: {call_id} not processed | error: {err}")

            print("🎯 Processing complete.\n")

        except Exception as err:
            with open("logs/failed_files.txt", "a") as failed_txt:
                curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                failed_txt.writelines(f"[{curr_time_stamp}] error: {err}\n")


if __name__ == "__main__":
    processor = CallProcessor(HUBSPOT_TOKEN, output_dir=OUTPUT_DIR)

    processor.process_calls()
