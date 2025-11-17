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