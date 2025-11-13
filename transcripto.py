from hubspot import HubSpot
from hubspot.crm.objects.calls import SimplePublicObjectInput
import requests
import os
import openai

api_client = HubSpot(access_token='pat-na2-7dbb3945-12d7-4197-ae96-8f8eb521ac6b')


def get_all_calls(limit=50):
    """Fetch call records from HubSpot"""
    calls = api_client.crm.objects.calls.basic_api.get_page(
        limit=limit,
        properties=["hs_call_recording_url"]
    )
    return calls.results


def download_recording(call_id, rec_url):
    """Download recording from Google Drive"""
    if not rec_url:
        return None

    try:
        file_id = rec_url.split("/")[-2]
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        output_path = os.path.join(os.getcwd(), f"{call_id}.mp3")

        response = requests.get(download_url, stream=True)
        if response.status_code == 200:
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Downloaded recording: {output_path}")
            return output_path
    except:
        print(f" Failed to download recording for {call_id}")
    
    return None


# def transcribe_audio(file_path):
#     """Transcribe using Whisper API (disabled for now)"""
#     with open(file_path, "rb") as audio_file:
#         transcript = openai.Audio.transcriptions.create(
#             model="gpt-4o-transcribe",
#             file=audio_file,
#             response_format="text"
#         )
#     return transcript.text


def update_hubspot_call_details(call_id, message):
    """Update HubSpot custom column 'call_details'"""
    update_obj = SimplePublicObjectInput(
        properties={"call_details": message}
    )
    api_client.crm.objects.calls.basic_api.update(
        call_id=call_id,
        simple_public_object_input=update_obj
    )
    print(f" Updated 'call_details' for call {call_id}")


if __name__ == "__main__":
    calls = get_all_calls(limit=20)

    for call in calls:
        call_id = call.id
        rec_url = call.properties.get("hs_call_recording_url")

        print(f"\n Processing Call ID: {call_id}")

        if not rec_url:
            print(" No recording URL → skipped")
            continue

        mp3_path = download_recording(call_id, rec_url)
        if not mp3_path:
            continue

        message = "Yes, converted and updated to call_details column."

        update_hubspot_call_details(call_id, message)

    print("\nDone! All calls processed.")
