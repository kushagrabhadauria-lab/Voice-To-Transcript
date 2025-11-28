import requests
import os


class DownloadFromDrive:
    '''
        Download from drive 
    '''
    fixed_url = "https://drive.google.com/uc?export=download&id="
    destination = os.getcwd()+"/downloads"

    def __init__(self):
        self.file_id = None


    def download(self, file_id, call_id):
        url = self.fixed_url+file_id
        response = requests.get(url, stream=True)

        if response.status_code == 200:
            destination = self.destination+f"/{call_id}.mp3"

            with open(destination, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(" File downloaded:", destination)
        
        else:
            print("Failed to download, status:", response.status_code)


    def find_file_id(self, url):
        file_id = url.split("/")[-2]
        return file_id
    

class AudioDownloader:
    '''
        Download audio from the link
    '''
    def __init__(self):
        self.destination = os.path.join(os.getcwd(), "downloads")
        
        # Ensure download directory exists
        os.makedirs(self.destination, exist_ok=True)
        

    def download(self, url, call_id):
        '''
            Download function from link
        '''
        try:
            response = requests.get(url, stream=True)

            if response.status_code != 200:
                raise Exception(f"Failed! Status {response.status_code}")

            output_file_name = self.destination+f"/{call_id}.mp3"

            with open(output_file_name, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)

            print(f"Audio file saved {output_file_name}")
            return output_file_name


        except Exception as err:
            return None


class GetRecordingUrlIdFromCsv:
    '''
        Class to get the call_id from the csv
    ''' 
    import pandas as pd
    def __init__(self, file_path: str):
        self.df = self.pd.read_csv(file_path, dtype={"ID": str})

    def get_recording_url_id(self):
        done_df = self.df[self.df["Done"].str.upper() == "YES"]
    
        # Extract only the ID column
        ids = done_df["ID"].tolist()
    
        return ids

class SentimentScoreExtractor:
    '''
        Class to get Sentiment score from summary
    '''
    sentiment_pattern = r"Rating:\s*(\d+)/10"

    def get_sentiment(self, summary):
        import re
        if not summary:
            return None
        match = re.search(self.sentiment_pattern, summary)
        if match:
            return match.group(1)
        
        return None


if __name__ == "__main__":
    url_id_obj = GetRecordingUrlIdFromCsv("/home/aryanverma/hubspot_integration/Voice-To-Transcript/updated_url_sheet.csv")
    print(url_id_obj.get_recording_url_id())