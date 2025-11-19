import os
import pandas as pd
from hubspot_util import HubSpotClient
from call_summary_util import CallSummaryPipeline
from helper_functions import DownloadFromDrive, AudioDownloader, GetRecordingUrlIdFromCsv
from global_variables import EnviromentVariable
from dotenv import load_dotenv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

load_dotenv()


class Interface():
    '''
        Interface to combine hubspot and AI model
    '''
    def __init__(self):
        self.file_path = os.getcwd()+"/downloads/"
        self.hubspot_token = EnviromentVariable.HUBSPOT_TOKEN
        self.output_dir = EnviromentVariable.OUTPUT_DIR
        self.gemini_key = EnviromentVariable.GEMINI_KEY
        self.hubspot_client_obj = HubSpotClient(self.hubspot_token)
        self.call_summary_pipeline = CallSummaryPipeline(self.gemini_key)
        self.download_from_drive_obj = DownloadFromDrive()
        self.download_audio_obj = AudioDownloader()
        self.get_call_recording_ids_from_csv_obj = GetRecordingUrlIdFromCsv("/home/aryanverma/hubspot_integration/Voice-To-Transcript/updated_url_sheet.csv")
        self.processed_ids = []
    
    def process_single_call(self, call_id, call_url):
        """
        Process a single call:
        - download file
        - run summary pipeline
        - update hubspot
        """
        try:
            # file_id = self.download_from_drive_obj.find_file_id(call_url)
            # self.download_from_drive_obj.download(file_id, call_id)
            self.download_audio_obj.download(call_url, call_id)

            # set file path dynamically
            self.call_summary_pipeline.set_file_path(
                self.file_path + f"{call_id}.mp3"
            )

            summary = self.call_summary_pipeline.run()
            # update hubspot
            self.hubspot_client_obj.update_call_transcription(call_id, summary)
            with open("logs/success_files.txt", "a") as f:
                f.write(f"[{datetime.now()}] call_id: {call_id} Processed successfully.\n")
            return f"[SUCCESS] {call_id}"

        except Exception as err:
            with open("logs/failed_files.txt", "a") as f:
                f.write(f"[{datetime.now()}] call_id: {call_id} error: {err}\n")

            return f"[FAILED] {call_id}: {err}"
        
        finally:
            os.remove(os.getcwd()+f"/downloads/{call_id}.mp3")
    
    
    def run(self):
        try:
            call_recordings = self.hubspot_client_obj.get_call_with_empty_summary_and_recording_url_id()

            call_recording_dict = {
                call.id: call.properties["hs_call_recording_url"]
                for call in call_recordings
            }

            print(f"📞 Total calls to process: {len(call_recording_dict)}")

            # ---------- THREADING STARTS HERE ----------
            results = []
            with ThreadPoolExecutor(max_workers=1) as executor:
                future_map = {
                    executor.submit(
                        self.process_single_call, call_id, call_url
                    ): call_id
                    for call_id, call_url in call_recording_dict.items()
                }

                for future in as_completed(future_map):
                    result = future.result()
                    results.append(result)
                    print(result)

            print("All threads completed!")

        except Exception as err:
            raise Exception(f"Unexpected error: {err}")
        
    def test_run(self):
        try:
            url_ids = self.get_call_recording_ids_from_csv_obj.get_recording_url_id()
            self.processed_ids = url_ids[100: ]
            print(str(self.processed_ids))
            
            call_recordings = []
            for id in self.processed_ids:
                try:
                    call_recordings.append(self.hubspot_client_obj.get_call_recording_with_recording_url_id(str(id))[0])

                except Exception as err:
                    with open("logs/failed_files.txt", "a") as f:
                        f.write(f"[{datetime.now()}] call_id: {id} error: {err}\n")

            

            call_recording_dict = {
                call.id: {"recording_url": call.properties["hs_call_recording_url"], "recording_url_id": call.properties["recording_url_id"]}
                for call in call_recordings
            }

            # print(call_recording_dict)

            print("call_recording_dict: ", call_recording_dict)
            print(f"📞 Total calls to process: {len(call_recording_dict)}")
            # ---------- THREADING STARTS HERE ----------
            results = []
            with ThreadPoolExecutor(max_workers=20) as executor:
                future_map = {
                    executor.submit(
                        self.process_single_call, call_id, call_obj["recording_url"]
                    ): call_id
                    for call_id, call_obj in call_recording_dict.items()
                }

                for future in as_completed(future_map):
                    result = future.result()
                    results.append(result)
                    print(result)

            print("All threads completed!")

        except Exception as err:
            raise Exception(f"Unexpected error: {err}")
        
        finally:
            # print("processed_id: ", self.processed_ids)
            # csv_path = "/home/aryanverma/hubspot_integration/Voice-To-Transcript/updated - recording url id.csv"
            # df = pd.read_csv(csv_path)
            # df["summary_updated"] = df["ID"].isin(self.processed_ids)
            # df.to_csv(csv_path, index=False)
            # print(f"[OK] CSV updated successfully")
            pass



if __name__ == "__main__":
    start_time = datetime.now()
    logging.info(f"Started processing at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    interface = Interface()
    interface.run()

    end_time = datetime.now()
    duration = end_time - start_time

    logging.info(f"Finished processing at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Total time taken: {duration.total_seconds():.2f} seconds")

