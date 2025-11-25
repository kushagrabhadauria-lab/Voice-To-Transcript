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
import time

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

        self.hubspot_token = EnviromentVariable.HUBSPOT_TOKEN
        self.output_dir = EnviromentVariable.OUTPUT_DIR
        self.gemini_key = EnviromentVariable.GEMINI_KEY
        self.hubspot_client_obj = HubSpotClient(self.hubspot_token)
        self.call_summary_pipeline = CallSummaryPipeline(self.gemini_key)
        self.download_from_drive_obj = DownloadFromDrive()
        self.download_audio_obj = AudioDownloader()
        # If you need CSV helper in test_run, uncomment and set correct path:
        self.get_call_recording_ids_from_csv_obj = GetRecordingUrlIdFromCsv("/home/aryanverma/.../500_recording_url.csv")

        self.processed_ids = []
        # changed: Ensure logs dir exists
        os.makedirs("logs", exist_ok=True)                                # changed
    
    def process_single_call(self, call_id, call_url, recording_url_id=None):
        """
        Process a single call:
        - download file
        - run summary pipeline (with retries for transient failures)
        - update hubspot
        """
        try:
            logging.info(f"Starting processing call_id={call_id} recording_url_id={recording_url_id}")
            # download the audio
            self.download_audio_obj.download(call_url, call_id)

            # set file path dynamically
            file_full_path = os.path.join(self.file_path, f"{call_id}.mp3")
            self.call_summary_pipeline.set_file_path(file_full_path)

            # changed: Retry loop for transient errors (e.g., 503 model overloaded)
            max_attempts = 3                                              # changed
            attempt = 0                                                   # changed
            summary = None                                                # changed
            while attempt < max_attempts:
                try:
                    attempt += 1                                           # changed
                    logging.info(f"Running summary pipeline for call_id={call_id} attempt={attempt}")  # changed
                    summary = self.call_summary_pipeline.run()             # changed
                    # If pipeline.run() returns successfully, break out
                    break                                                  # changed
                except Exception as e:
                    # If last attempt, re-raise to outer except
                    logging.warning(f"Attempt {attempt} failed for call_id={call_id} recording_url_id={recording_url_id}: {e}")  # changed
                    if attempt >= max_attempts:
                        raise
                    # Exponential backoff before retrying
                    backoff = 2 ** (attempt - 1)
                    time.sleep(backoff)

            if summary is None or (isinstance(summary, str) and summary.strip() == ""):
                raise ValueError("Summary was empty in run().")

            # update hubspot
            self.hubspot_client_obj.update_call_transcription(call_id, summary)

            # changed: Write success log with recording_url_id included
            with open("logs/success_files.txt", "a") as f:
                f.write(
                    f"[{datetime.now()}] call_id: {call_id} recording_url_id: {recording_url_id} Processed successfully.\n"
                )

            logging.info(f"[SUCCESS] call_id={call_id} recording_url_id={recording_url_id}")
            return f"[SUCCESS] {call_id}"

        except Exception as err:
            # changed: Write failure log with recording_url_id included
            with open("logs/failed_files.txt", "a") as f:
                f.write(
                    f"[{datetime.now()}] call_id: {call_id} recording_url_id: {recording_url_id} error: {err}\n"
                )

            logging.error(f"[FAILED] call_id={call_id} recording_url_id={recording_url_id} error={err}")
            return f"[FAILED] {call_id}: {err}"
        
        finally:
            # Don't remove file immediately so you can inspect in case of problems.
            # If you want to remove, uncomment:
            # try:
            #     os.remove(file_full_path)
            # except Exception:
            #     pass
            pass
    
    
    def run(self):
        try:
            call_recordings = self.hubspot_client_obj.get_call_with_empty_summary_and_recording_url_id()

            # changed: to store both recording url and recording_url_id in dict
            call_recording_dict = {
                call.id: {
                    "recording_url": call.properties.get("hs_call_recording_url"),
                    "recording_url_id": call.properties.get("recording_url_id") or call.properties.get("recording_url_id", None)
                }
                for call in call_recordings
            }                                                              # changed

            print(f"📞 Total calls to process: {len(call_recording_dict)}")
            
            # ---------- THREADING STARTS HERE ----------
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                future_map = {
                    executor.submit(
                        self.process_single_call,
                        call_id,
                        call_obj["recording_url"],
                        call_obj.get("recording_url_id")
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
        
    def test_run(self):
        try:
            self.processed_ids = self.get_call_recording_ids_from_csv_obj.get_recording_url_id()
        
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
            with ThreadPoolExecutor(max_workers=10) as executor:
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