import os
from hubspot_util import HubSpotClient
from call_summary_util import CallSummaryPipeline
from helper_functions import DownloadFromDrive
from global_variables import EnviromentVariable
from dotenv import load_dotenv
from datetime import datetime

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

    
    def run(self):
        try:
            call_recordings = self.hubspot_client_obj.get_calls_with_recordings()
            call_recording_dict = {
                call.id : call.properties["hs_call_recording_url"] for call in call_recordings
            }

            for call_id, call_url in call_recording_dict.items():
                try:
                    file_id = self.download_from_drive_obj.find_file_id(call_url)
                    self.download_from_drive_obj.download(file_id, call_id)

                    self.call_summary_pipeline.set_file_path(self.file_path+f"{call_id}.mp3")
                    summary = self.call_summary_pipeline.run()

                    self.hubspot_client_obj.update_call_transcription(call_id, summary)

                except Exception as err:
                    with open("logs/failed_files.txt", "a") as f:
                        f.write(f"[{datetime.now()}] call_id: {call_id} error: {err}")

        except Exception as err:
            raise Exception(f"Unexpected error: {err}")

if __name__ == "__main__":
    interface = Interface()
    interface.run()

