import os
import csv
import time
import requests
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv

from google import genai
from google.genai.types import (
    GenerateContentConfig,
    Part,
    Content,
    UploadFileConfig,
)

# ------------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

pause_event = threading.Event()
pause_event.set()
retry_lock = threading.Lock()

# ------------------------------------------------------------------
# AUDIO DOWNLOADER
# ------------------------------------------------------------------
class AudioDownloader:
    def __init__(self, url=None, save_dir="temp"):
        self.url = url
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def download(self, filename):
        logging.info("📥 Downloading recording...")
        response = requests.get(self.url, timeout=60)
        response.raise_for_status()

        path = os.path.join(self.save_dir, filename)
        with open(path, "wb") as f:
            f.write(response.content)

        size_mb = len(response.content) / (1024 * 1024)
        logging.info(f"✅ Downloaded {size_mb:.2f} MB → {path}")
        return path

# ------------------------------------------------------------------
# GEMINI FILE MANAGER
# ------------------------------------------------------------------
class GeminiFileManager:
    SMALL_FILE_LIMIT_MB = 20.0

    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)

    def prepare_file(self, file_path):
        size_mb = os.path.getsize(file_path) / (1024 * 1024)

        if size_mb <= self.SMALL_FILE_LIMIT_MB:
            with open(file_path, "rb") as f:
                return (
                    Part.from_bytes(
                        data=f.read(),
                        mime_type="audio/mpeg"
                    ),
                    "small"
                )

        config = UploadFileConfig(
            mime_type="audio/mpeg",
            display_name="Call Recording"
        )
        file_obj = self.client.files.upload(file=file_path, config=config)
        return file_obj, "large"

    def wait_until_ready(self, file_obj):
        while True:
            info = self.client.files.get(name=file_obj.name)
            if info.state.name != "PROCESSING":
                return info
            time.sleep(2)

# ------------------------------------------------------------------
# SINGLE CALL TRANSCRIPTION + CSAT
# ------------------------------------------------------------------
class UnifiedCallAnalyzer:

    PROMPT = """
        # ROLE
        You are an expert Call Quality Analyst specializing in Customer Satisfaction (CSAT) and Agent Performance.

        # TASK
        Perform ALL tasks in ONE response:
        1. Verbatim transcription
        2. CSAT evaluation

        # CORE DEFINITIONS (MANDATORY)
        - **AGENT(S):** One or more speakers representing the company.
        - **CUSTOMER(S):** One or more external speakers (owner, staff, family member, intermediary).
        - **PRIMARY CUSTOMER:** The decision-maker or account owner, if identifiable.
        - **INTERMEDIARY:** A customer-side participant who is NOT the decision-maker (e.g., receptionist, staff member, relative).

        IMPORTANT:
        - There may be MULTIPLE agents and/or MULTIPLE customers.
        - NEVER merge agent speech into customer speech or vice versa.
        - NEVER assume the first speaker is the customer.
        - NEVER assume the person who answers is the owner or decision-maker.

        # TASK
        Analyze the call recording and generate a CSAT report based strictly on spoken evidence.

        # AUDIO VALIDITY CHECK (FIRST AND MANDATORY)

        Before any analysis, determine if a valid conversational exchange exists.

        A call is INVALID if:
        - No customer-side participant responds verbally to any agent.
        - Audio contains only silence, noise, music, or unintelligible speech.
        - Only agents speak with no external participant response.
        - Voices exist but no meaningful exchange occurs.

        If INVALID, return EXACTLY:

        NO VALID CONVERSATION DETECTED.
        Reason: No meaningful two-way interaction between agent(s) and customer-side participant(s).

        # ANALYSIS RULES
        - OBJECTIVITY: Use only spoken content. No assumptions.
        - MULTI-PARTICIPANT AWARENESS:
        - Attribute statements to roles, not individuals unless explicitly named.
        - If multiple agents/customers speak, evaluate collective interaction quality.
        - INTERMEDIARY HANDLING:
        - If the customer-side speaker is not the decision-maker, clearly label them as INTERMEDIARY.
        - Do NOT penalize CSAT for lack of resolution if the PRIMARY CUSTOMER never joined the call.

        # SCORING SCOPE (CRITICAL)
        - Score AGENT PERFORMANCE based on how agents handled whoever they spoke with.
        - Score CUSTOMER SENTIMENT based ONLY on spoken customer-side reactions.
        - If resolution was impossible due to speaking only with an INTERMEDIARY, reflect this in scoring justification.



        # SCORING FRAMEWORK
        
        1. ISSUE RESOLUTION STATUS (30%)
        - 9–10: Issue fully resolved; no further action needed.
        - 6–8: Partial resolution; clear follow-up path established.
        - 2–5: Unresolved; vague next steps; customer left confused.
        - 0–1: No resolution; customer requested escalation or refund.

        2. CUSTOMER SENTIMENT TRAJECTORY (10%)
        - 9–10: Negative/Neutral start -> Strong Positive/Appreciative end.
        - 6–8: Negative start -> Neutral/Calm end.
        - 2–5: Negative start -> Negative/Aggravated end (or worsened).

        3. CUSTOMER TRUST & CONFIDENCE (10%)
        - 8–10: Customer explicitly thanks agent or confirms future business.
        - 4–7: Customer is compliant but shows no high enthusiasm.
        - 0–3: Customer expresses doubt, threatens to cancel, or asks for manager.

        4. AGENT HANDLING QUALITY (30%)
        - 8–10: High empathy, active listening, clear technical explanations.
        - 5–7: Professional and polite, but lacked deep empathy or struggled with technicals.
        - 0–4: Defensive, rude, interrupted the customer, or provided incorrect info.

        5. CLOSURE QUALITY (20%)
        - 8–10: Clear summary of action items; polite sign-off; customer satisfied with end.
        - 4–7: Standard sign-off; no summary of next steps.
        - 0–3: Call cut off abruptly or customer ended the call in anger.

        # OUTPUT STRUCTURE (DO NOT ALTER HEADINGS)

        ## 1. CALL OVERVIEW
        - **Call Type:** [Inbound/Outbound] | [Support/Sales/Complaint/Contact Attempt]
        - **Language:**
        - **Outcome:** [Resolved/Unresolved/Escalated]

        ## 2. PARTICIPANTS
        - **Agent:** [Name/Role] | [Style: e.g., Patient, Authoritative, Passive]
        - **Customer:** [Name] | [Style: e.g., Frustrated, Tech-savvy, Distressed]

        ## 3. CALL PURPOSE & KEY TOPICS
        - **Main reason for call:**
          (Reflect the INITIATING SPEAKER’S objective.)
        - **Customer’s concern/request:**
          (Decision-maker / Intermediary / Information provider)
        - **Related issues discussed:**

        ## 4. CSAT SCORECARD
            a) **ISSUE RESOLUTION ASSESSMENT**
            - **Score:** [0-10]/10
            - **Justification:** [Single sentence with specific evidence or quote]

            b) **CUSTOMER SENTIMENT TRAJECTORY**
            - **Score:** [0-10]/10
            - **Justification:** [Single sentence with specific evidence or quote]

            c) **CUSTOMER TRUST & CONFIDENCE**
            - **Score:** [0-10]/10
            - **Justification:** [Single sentence with specific evidence or quote]

            d) **AGENT HANDLING QUALITY**
            - **Score:** [0-10]/10
            - **Justification:** [Single sentence with specific evidence or quote]

            e) **CLOSURE QUALITY**
            - **Score:** [0-10]/10
            - **Justification:** [Single sentence with specific evidence or quote]

        ## 5. FINAL ASSESSMENT
        - **Normalized CSAT (0–10):** [Weighted Average]
        - **Executive Summary:** [3-sentence summary of why this score was given.]
        - **Actionable Coaching Tip:** [One specific thing the agent could do better next time.]

        ## 6. Transcription
    """

    def __init__(self, api_key, model="gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def call_with_retry(self, parts):
        backoff = 1
        for _ in range(5):
            try:
                pause_event.wait()
                return self.client.models.generate_content(
                    model=self.model,
                    contents=[Content(parts=parts)],
                    config=GenerateContentConfig(temperature=0.2)
                )
            except Exception as e:
                if "429" in str(e) or "503" in str(e):
                    if retry_lock.acquire(False):
                        pause_event.clear()
                        time.sleep(backoff)
                        backoff *= 2
                        pause_event.set()
                        retry_lock.release()
                    else:
                        pause_event.wait()
                else:
                    raise
        raise RuntimeError("Gemini API failed after retries")

    def analyze(self, file_input, file_type, record_id):
        prompt = f"""
            # CALL METADATA
            - Record ID: {record_id}

            {self.PROMPT}
            """

        if file_type == "large":
            file_input = manager.wait_until_ready(file_input)
            parts = [
                Part.from_uri(
                    file_uri=file_input.uri,
                    mime_type=file_input.mime_type
                ),
                Part.from_text(text=prompt)
            ]
        else:
            parts = [
                file_input,
                Part.from_text(text=prompt)
            ]

        response = self.call_with_retry(parts)
        return response.text.strip()

# ------------------------------------------------------------------
# CSV PIPELINE
# ------------------------------------------------------------------
def generate_csv(records, api_key, output_csv="call_analysis.csv"):
    global manager

    downloader = AudioDownloader()
    manager = GeminiFileManager(api_key)
    analyzer = UnifiedCallAnalyzer(api_key)

    rows = []

    for rec in records:
        record_id = rec["record_id"]
        downloader.url = rec["recording_url"]

        logging.info(f"🚀 Processing {record_id}")
        audio_path = downloader.download(f"{record_id}.mp3")

        file_obj, file_type = manager.prepare_file(audio_path)

        analysis = analyzer.analyze(
            file_obj,
            file_type,
            record_id
        )

        rows.append({
            "record_id": record_id,
            "recording_url": rec["recording_url"],
            "analysis": analysis
        })

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["record_id", "recording_url", "analysis"]
        )
        writer.writeheader()
        writer.writerows(rows)

    logging.info(f"✅ CSV generated → {output_csv}")

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
CALL_RECORDS = [
    {
        "record_id" : "apphubspot",
        "recording_url" : "https://cloudphone.tatateleservices.com/file/recording?callId=c81957d5-8745-4c0f-b7a1-2af3ec4088bd&type=rec&token=Mk13cENzQkR1NWF3eXlCaE5BRytSZU1ZakV3YzdkcktEcUlpT0VXWUtRZmU3dVBWNXhVOW9NZEFKaUZEbTlhSjo6YWIxMjM0Y2Q1NnJ0eXl1dQ%3D%3D"
    },
    {
        "record_id" : "292172665555",
        "recording_url" : "https://cloudphone.tatateleservices.com/file/recording?callId=c361db74-ccb8-4b4f-b375-e46befe07b35&type=rec&token=RkFiL3hrZ3ltODhKT0liazFUSlhiWVZiQm5GSEx1TExmV2xFTEdqMVQzZGpqK3BNUmwzaGxhU2svb3hCTUNvbDo6YWIxMjM0Y2Q1NnJ0eXl1dQ%3D%3D"
    },
    {
        "record_id" : "292172658405",
        "recording_url" : "https://cloudphone.tatateleservices.com/file/recording?callId=e1598b95-f290-48dc-a4f2-037985ab3014&type=rec&token=R1RFMXUxcWVLNXEyUWRnQ0NGSUdidG5mT0dRU1ZEeFozTWFrNmhiemd3QXorNWlQQzlQUmJmWnBpMUgrdUZBSzo6YWIxMjM0Y2Q1NnJ0eXl1dQ%3D%3D"
    },
    {
        "record_id" : "292529547989",
        "recording_url" : "https://cloudphone.tatateleservices.com/file/recording?callId=05cbb106-2d34-46c6-b103-d43f8b577392&type=rec&token=SXJZc2hrV1BLVE1kamRuWnpsenVhcFBWZWZ3SklQYVZTcjdCSDNZOTJUa0hUSEhSUEthZFhFSW9yZHQ0UktMUjo6YWIxMjM0Y2Q1NnJ0eXl1dQ%3D%3D"
    }
]


if __name__ == "__main__":
    load_dotenv()
    GEMINI_KEY = os.getenv("GEMINI_KEY")

    start = datetime.now()
    generate_csv(CALL_RECORDS, GEMINI_KEY)
    end = datetime.now()

    logging.info(f"⏱ Total time: {(end - start).total_seconds():.2f}s")
