import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from hubspot import HubSpot
from hubspot.crm.objects.calls import SimplePublicObjectInput, BatchInputSimplePublicObjectBatchInput
from hubspot.crm.objects import ApiException
from helper_functions import GetRecordingUrlIdFromCsv, SentimentScoreExtractor

load_dotenv()

HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./downloads")

if not HUBSPOT_TOKEN:
    raise RuntimeError("HUBSPOT_TOKEN not found. Set it in your .env file.")


class HubSpotClient:
    """Handles HubSpot API operations for calls."""

    def __init__(self, access_token: str):
        self.client = HubSpot(access_token=access_token)
        self.sentiment_extractor_obj = SentimentScoreExtractor()

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
        """Update custom property 'model_to_hb_transcription' one call at a TIME"""
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

    
    def get_call_by_recording_url_id(self, record_url_id: str):
        """
            Fetch a call record that matches the given recording_url_id.
            Returns the HubSpot call object if found, else returns None.
        """
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup
        from hubspot.crm.objects.calls.exceptions import ApiException

        # Filter: recording_url_id == provided ID
        filter_ = Filter(
            property_name="recording_url_id",
            operator="EQ",
            value=record_url_id
        )

        filter_group = FilterGroup(filters=[filter_])

        search_request = PublicObjectSearchRequest(
            filter_groups=[filter_group],
            limit=1,
            properties=["recording_url_id", "hs_call_start_time", "hs_call_title", "sentiment_score", "model_to_hb_transcription"]
        )

        try:
            results = self.client.crm.objects.calls.search_api.do_search(
                public_object_search_request=search_request
            )

            if results and results.results:
                return results.results[0]   # return the first (and only) matched call
            else:
                return None

        except ApiException as e:
            print(f"Error fetching call by recording_url_id {record_url_id}: {e}")
            return None



    def update_sentiment_score(self, call_id: str, rating: int):
        ''' update sentiment_score in hubspot'''
        try:
            update_obj = SimplePublicObjectInput(properties={"sentiment_score": rating})
            self.client.crm.objects.calls.basic_api.update(
                call_id=call_id,
                simple_public_object_input=update_obj
            )
            print(f" Updated model_to_hb_transcription for call {call_id}")

        except ApiException as e:
            with open("logs/failed_files.txt", 'a') as failed_file:
                curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                failed_file.write(f"[{curr_time_stamp}] call_id: {call_id} failed to update call : {e}\n")
            
            print(f"Failed to update call {call_id}: {e}")

        

    def update_summary_and_sentiment_score(self, call_id: str, summary: str):
        '''
            Using call_id and summary we need to populate both summary and sentiment score
        '''
        try:
            sentiment_score = self.sentiment_extractor_obj.get_sentiment(summary)
            if not sentiment_score:
                raise ValueError("Cannot find Sentiment score in summary.")
            
            update_obj = SimplePublicObjectInput(properties={
                "model_to_hb_transcription": summary,
                "sentiment_score": int(sentiment_score)
            })

            self.client.crm.objects.calls.basic_api.update(
                call_id=call_id,
                simple_public_object_input=update_obj
            )

            print(f" Updated model_to_hb_transcription and sentiment_score for call {call_id}")
            

        except Exception as err:
            with open("logs/failed_files.txt", 'a') as failed_file:
                curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                failed_file.write(f"[{curr_time_stamp}] call_id: {call_id} failed to update call summary and sentiment_score : {err}\n")
            
            print(f"Failed to update call {call_id}: {err}")


    def bulk_update_call_transcription(self, calls_info: list):
        '''
            Bulk upload transcription to hubspot to 'model_to_hb_transcription'
            call_info = [
                {"call_id": "12345", "summary": "Transcription text..."},
                {"call_idid": "67890", "summary": "Another transcription..."},
                ...
            ]
        '''
        try:
            inputs = []
            for item in calls_info:
                inputs.append(
                    SimplePublicObjectInput(
                        id=item["call_id"],
                        properties={
                            "model_to_hb_transaction": item["summary"]
                        }
                    )
                )

            batch_body = BatchInputSimplePublicObjectBatchInput(inputs=inputs)

            self.client.crm.objects.calls.batch_api.update(batch_body)
            print(f"[SUCCESS] Bulk upload successful total file: {len(calls_info)}.")

        except Exception as err:
            with open("logs/failed_files.txt", "a") as failed_file:
                curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                failed_file.write(f"[{curr_time_stamp}] [ERROR] bulk upload failed {err}")
            
            print(f"[ERROR] Bulk upload failed : {err}")



    def get_call_recording_with_recording_url_id(self, recording_url_id: str):
        '''
            Get single call recording obj from recording_url_id filter
        '''
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup
        try:
            filters = [
                Filter(
                    property_name="recording_url_id",   # <-- your ID field here
                    operator="EQ",
                    value=recording_url_id
                )
            ]

            filter_group = FilterGroup(filters=filters)

            search_request = PublicObjectSearchRequest(
                filter_groups=[filter_group],
                properties=["recording_url_id", "hs_call_recording_url", "hs_call_start_time", "model_to_hb_transaction", "sentiment_score"]
            )

            results = self.client.crm.objects.calls.search_api.do_search(
                public_object_search_request=search_request
            )

            return results.results

        except Exception as err:
            print(f"[ERROR] Unable to get call_id obj for this recording_url_id : {err}")


    def get_call_with_recording_url_and_company_name_today(self):
        """
        Fetch calls from the last 24 hours (rolling window) that:
        - have recording_url
        - do NOT have summary
        - have an associated company
        """
        from datetime import datetime, timezone, timedelta
        from hubspot.crm.objects.calls import PublicObjectSearchRequest

        try:
            now = datetime.now(timezone.utc)
            start_24h_ago = now - timedelta(hours=24)

            start_ms = str(int(start_24h_ago.timestamp() * 1000))

            filter_groups = [
                {
                    "filters": [
                        {
                            "propertyName": "hs_timestamp",
                            "operator": "GTE",
                            "value": start_ms
                        },
                        {
                            "propertyName": "hs_call_recording_url",
                            "operator": "HAS_PROPERTY"
                        },
                        {
                            "propertyName": "model_to_hb_transcription",
                            "operator": "NOT_HAS_PROPERTY"
                        },
                        {
                            "propertyName": "hs_call_duration",
                            "operator": "GTE",
                            "value": "30000"  # 30 seconds (ms)
                        }
                    ]
                }
            ]

            properties = [
                "hs_call_recording_url",
                "model_to_hb_transcription",
                "hs_timestamp",
                "hs_call_duration"
            ]

            final_results = []
            after = None
            count = 1

            while True:
                print("count: ", count)
                count+=1
                search_request = PublicObjectSearchRequest(
                    filter_groups=filter_groups,
                    properties=properties,
                    limit=20,   # HubSpot hard limit
                    after=after
                )

                response = self.client.crm.objects.calls.search_api.do_search(
                    public_object_search_request=search_request
                )

                # print("response: ", response.results[0])
                if not response.results:
                    break

                for call in response.results:
                    call_id = call.id

                    associations = self.client.crm.associations.v4.basic_api.get_page(
                        "calls",
                        call_id,
                        "companies"
                    )

                    if not associations.results:
                        continue

                    company_id = associations.results[0].to_object_id

                    company_obj = self.client.crm.companies.basic_api.get_by_id(
                        company_id,
                        properties=["name"]
                    )
                    print({
                        "call_id": call_id,
                        "company_name": company_obj.properties.get("name"),
                        "timestamp": call.properties.get("hs_timestamp"),
                        "call_duration": call.properties.get("hs_call_duration")
                    })

                    final_results.append({
                        "call_id": call_id,
                        "recording_url": call.properties.get("hs_call_recording_url"),
                        "company_name": company_obj.properties.get("name"),
                        "summary": call.properties.get("model_to_hb_transcription"),
                        "timestamp": call.properties.get("hs_timestamp"),
                        "call_duration": call.properties.get("hs_call_duration")
                    })

                # Pagination check
                if response.paging and response.paging.next:
                    after = response.paging.next.after
                else:
                    break

            print("total calls fetched:", len(final_results))
            return final_results

        except Exception as err:
            print(f"[ERROR] Unable to get calls for last 24 hours: {err}")
            return None


    def get_call_with_empty_summary_and_recording_url_id(self):
        from hubspot.crm.objects.calls.models import PublicObjectSearchRequest, Filter, FilterGroup
        try:        
                filters = [
                    Filter(property_name="recording_url_id", operator="HAS_PROPERTY"),
                    Filter(property_name="model_to_hb_transcription", operator="NOT_HAS_PROPERTY")
                ]
                filter_group = FilterGroup(filters=filters)

                all_results = []
                after = None

                while True:
                    search_request = PublicObjectSearchRequest(
                        filter_groups=[filter_group],
                        properties=["recording_url_id", "hs_call_recording_url", "hs_call_start_time", "hs_call_duration"],
                        limit=100,
                        after=after
                    )

                    response = self.client.crm.objects.calls.search_api.do_search(
                        public_object_search_request=search_request
                    )

                    all_results.extend(response.results)

                    if not response.paging or not response.paging.next:
                        break
                    
                    after = response.paging.next.after   # move to next page

                return all_results

        except Exception as err:
            print(f"[ERROR] Unable to get call_id obj for this recording_url_id : {err}")

    
    def get_call_by_id(self, call_id: str):
        """
            Fetch a single call object from HubSpot using call_id.
        """
        try:
            call_obj = self.client.crm.objects.calls.basic_api.get_by_id(
                call_id,
                properties=[
                    "hs_call_recording_url",
                    "recording_url_id",
                    "hs_call_start_time",
                    "model_to_hb_transcription",
                    "sentiment_score"
                ]
            )

            return call_obj

        except Exception as err:
            print(f"[ERROR] Unable to fetch call for call_id={call_id}: {err}")
            return None


if __name__ == "__main__":
    hubspot_client = HubSpotClient(HUBSPOT_TOKEN)

    # for call_id in ["282969248463", "283215137471", "283110276796", "283222715127"]:
    for call_id in ["283234131686", "283260662491"]:
        print(hubspot_client.get_call_by_id(call_id))

    # print(hubspot_client.get_call_with_recording_url_and_company_name_today())
    # sentiment_score_extractor_obj = SentimentScoreExtractor()
    # url_id_obj = GetRecordingUrlIdFromCsv("/home/aryanverma/hubspot_integration/Voice-To-Transcript/updated_url_sheet.csv")
    # url_ids = url_id_obj.get_recording_url_id()
    # print(len(url_ids))
    
    # count = 0
    # for url_id in url_ids:
    #     call_data = hubspot_client.get_call_by_recording_url_id(url_id)
    #     summary = call_data.properties["model_to_hb_transcription"]
    #     rating = sentiment_score_extractor_obj.get_sentiment(summary)

    #     if rating:
    #         rating = int(rating)
    #         print(count, "url_id: ", url_id)
    #         count+=1b
    #         call_id = call_data.id
    #         hubspot_client.update_sentiment_score(call_id, rating)
    #         with open("logs/success_files.txt", "a") as f:
    #             f.write(
    #                 f"[{datetime.now()}] call_id: {call_id} recording_url_id: {url_id} sentiment updated successfully.\n"
    #             )

    #     else:
    #         with open("logs/failed_files.txt", "a") as failed_file:
    #                 curr_time_stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    #                 failed_file.write(f"[{curr_time_stamp}] [ERROR] {url_id} cannot find rating in summary.")

    #         print(f"[ERROR] rating not found")
    
    # for id in url_ids:
    #     result = hubspot_client.get_call_recording_with_recording_url_id(str(id))
    #     print("result: ", result)

    # print(hubspot_client.get_call_with_empty_summary_and_recording_url_id())