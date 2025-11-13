import os
from datetime import datetime, timedelta, timezone
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
            properties=["hs_call_recording_url", "hs_call_start_time", "hs_call_duration"]
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



if __name__ == "__main__":
    hubspot_client = HubSpotClient(HUBSPOT_TOKEN)
    call_recordings = hubspot_client.get_calls_with_recordings()
    for call in call_recordings:
        print("caller_id: ", call.id)
        print("recording_url: ", call.properties["hs_call_recording_url"])
        print("model_to_hb_transcription", call.properties["model_to_hb_transcription"])

        print("\n\n")

