import os
import pandas as pd
from hubspot_util import HubSpotClient
from new_call_summary_util import CallSummaryPipeline as vertex_ai_call_summary_pipeline
from helper_functions import DownloadFromDrive, AudioDownloader, GetRecordingUrlIdFromCsv
from global_variables import EnviromentVariable
from dotenv import load_dotenv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from secret_manager_util import GcpConfig

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
        # changed: ensure downloads path ends with slash and exists
        self.file_path = os.path.join(os.getcwd(), "downloads") + os.sep  # changed
        os.makedirs(self.file_path, exist_ok=True)                       # changed
        logging.info("Gcp Authentication Initiated!")
        self.gcp_client_obj = GcpConfig()._create_authenticated_client() 
        logging.info("Gcp authentication completed!")
        self.hubspot_token = EnviromentVariable.HUBSPOT_TOKEN
        self.output_dir = EnviromentVariable.OUTPUT_DIR
        self.hubspot_client_obj = HubSpotClient(self.hubspot_token)
        # self.call_summary_pipeline = CallSummaryPipeline(self.gemini_key)
        self.call_summary_pipeline = vertex_ai_call_summary_pipeline(self.gcp_client_obj)
        self.download_from_drive_obj = DownloadFromDrive()
        self.download_audio_obj = AudioDownloader()
        # If you need CSV helper in test_run, uncomment and set correct path:
        # self.get_call_recording_ids_from_csv_obj = GetRecordingUrlIdFromCsv("/home/aryanverma/hubspot_integration/Voice-To-Transcript/updated - New 500 Urls.csv")

        self.processed_ids = []
        self.total_call_processed = 1
        self.not_processed_files = 0
        # changed: Ensure logs dir exists
        os.makedirs("logs", exist_ok=True)                                # changed
    
    
    def process_single_call(self, call_id, call_url, recording_url_id=None):
        """
            Process a single call:
            - download file
            - run summary pipeline (retry happens inside pipeline)
            - update hubspot
        """
        try:
            logging.info(f"Starting processing call_id={call_id}")

            # download the audio
            self.download_audio_obj.download(call_url, call_id)

            # set file path dynamically
            file_full_path = os.path.join(self.file_path, f"{call_id}.mp3")
            self.call_summary_pipeline.set_file_path(file_full_path)

            # 🚀 NO RETRY HERE — central retry exists inside pipeline.run()
            logging.info(f"Running summary pipeline for call_id={call_id}")
            summary = self.call_summary_pipeline.run()

            if summary is None or summary.strip() == "":
                raise ValueError("Summary was empty in run().")

            # update hubspot
            self.hubspot_client_obj.update_summary_and_sentiment_score(call_id, summary)
                
            logging.info(f"[SUCCESS] call_id={call_id} recording_url={call_url}")
            return f"[SUCCESS] {call_id}"

        except Exception as err:
            logging.error(f"[FAILED] call_id={call_id} recording_url={call_url} error={err}")
            self.not_processed_files+=1
            return f"[FAILED] {call_id}: {err}"

        finally:
            # safe file cleanup
            try:
                os.remove(file_full_path)
            except Exception:
                pass

    
    
    def run(self):
        try:
            # call_recordings = self.hubspot_client_obj.get_call_with_empty_summary_and_recording_url_id()
            call_recordings = self.hubspot_client_obj.get_call_with_recording_url_and_company_name_today()
            # changed: to store both recording url and recording_url_id in dict
            call_recording_dict = {
                call["call_id"]: {
                    "recording_url": call["recording_url"],
                }
                for call in call_recordings
            }                                                              # changed

            print(f"📞 Total calls to process: {len(call_recording_dict)}")
            call_processed_count = 1
            # ---------- THREADING STARTS HERE ----------
            results = []

            with ThreadPoolExecutor(max_workers=5) as executor:
                future_map = {
                    executor.submit(
                        self.process_single_call,
                        call_id,
                        call_obj["recording_url"],
                        call_obj.get("recording_url_id", None)
                    ): call_id
                    for call_id, call_obj in call_recording_dict.items()
                }

                for future in as_completed(future_map):
                    result = future.result()
                    results.append(result)
                    print(result)
                    print("call_processed_count: ", call_processed_count)
                    call_processed_count+=1

            
            print("Failed processed files: ", self.not_processed_files)
            print("All threads completed!")

        except Exception as err:
            raise Exception(f"Unexpected error: {err}")
        
        finally:
            try:
                self.clean_downloads_folder()
            except:
                pass


    def test_run(self):
        try:
            self.processed_ids = self.get_call_recording_ids_from_csv_obj.get_recording_url_id()
            self.processed_ids = self.processed_ids[200: 350]
        
            print(self.processed_ids)

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
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_map = {
                    executor.submit(
                        self.process_single_call, call_id, call_obj["recording_url"], call_obj.get("recording_url_id")
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
        

    def clean_downloads_folder(self):
        try:
            for filename in os.listdir(self.file_path):
                file_path = os.path.join(self.file_path, filename)

                # remove only files (not subfolders)
                if os.path.isfile(file_path):
                    os.remove(file_path)

            logging.info("Downloads folder cleaned successfully.")

        except Exception as err:
            logging.error(f"Failed to clean downloads folder: {err}")
        


if __name__ == "__main__":
    start_time = datetime.now()
    logging.info(f"Started processing at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    interface = Interface()
    interface.run()

    end_time = datetime.now()
    duration = end_time - start_time

    logging.info(f"Finished processing at: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Total time taken: {duration.total_seconds():.2f} seconds")