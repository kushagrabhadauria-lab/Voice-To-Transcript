import os
import csv
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from call_summary_util import CallSummaryPipeline
from helper_functions import AudioDownloader
import csv
import json
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


class CSVCallProcessorJSON:
    def __init__(self, csv_file_path, gemini_key, max_workers=20):
        self.csv_file_path = csv_file_path
        self.summary_pipeline = CallSummaryPipeline(gemini_key)
        self.audio_downloader = AudioDownloader()
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        os.makedirs(self.download_dir, exist_ok=True)

        self.max_workers = max_workers

        # JSON file to store results
        self.json_path = "summaries.json"
        self.summaries_json = {}

    def process_single_row(self, index, url):
        """Handles download + summary for a single row."""
        saved_file = None
        try:
            logging.info(f"[{index}] Downloading... {url}")
            saved_file = self.audio_downloader.download(url, f"audio_{index}")

            if not saved_file:
                raise RuntimeError("Download failed (None returned).")

            self.summary_pipeline.set_file_path(saved_file)
            summary = self.summary_pipeline.run()

            if summary is None:
                summary = ""

            logging.info(f"[{index}] Summary generated.")

            # Return index + summary to store in JSON
            return index, summary

        except Exception as e:
            logging.error(f"[{index}] ERROR: {e}")
            return index, f"[ERROR] {e}"

        finally:
            os.remove(os.getcwd()+f"/downloads/audio_{index}.mp3")

    def save_json(self):
        """Writes the in-memory dictionary to disk."""
        with open(self.json_path, "w", encoding="utf-8") as jf:
            json.dump(self.summaries_json, jf, indent=4)
        logging.info("JSON updated.")

    def run(self):
        # Read CSV
        with open(self.csv_file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if "Recording url" not in rows[0]:
            raise ValueError("CSV must contain 'Recording URL' column")

        logging.info(f"Total rows: {len(rows)}")

        # Thread pool processing
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.process_single_row, idx, row["Recording url"]): idx
                for idx, row in enumerate(rows)
                if row.get("Recording url")
            }

            for fut in as_completed(futures):
                idx, summary = fut.result()
                self.summaries_json[str(idx)] = summary  # Store string index
                logging.info(f"[{idx}] Stored in JSON.")

                self.save_json()  # Save after every completion


def update_csv_with_summary(csv_file, json_file, output_file):
    # Load JSON (idx → summary)
    with open(json_file, "r") as jf:
        summary_map = json.load(jf)

    rows = []
    
    # Read CSV
    with open(csv_file, "r", newline="", encoding="utf-8") as cf:
        reader = csv.reader(cf)
        header = next(reader)

        # Add summary column if not exists
        if "summary" not in header:
            header.append("summary")

        for idx, row in enumerate(reader):
            # Ensure row has enough columns
            while len(row) < len(header):
                row.append("")

            # If this index has a summary, add it
            if str(idx) in summary_map:
                row[-1] = summary_map[str(idx)]

            rows.append(row)

    # Write updated CSV
    with open(output_file, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(header)
        writer.writerows(rows)

    print("CSV updated successfully!")



if __name__ == "__main__":
    CSV_FILE = "temp/Calling Data [Recording Url] - 100 - Data.csv"
    GEMINI_KEY = os.getenv("GEMINI_KEY")

    # processor = CSVCallProcessorJSON(CSV_FILE, GEMINI_KEY, max_workers=8)
    # processor.run()
    # update_csv_with_summary(
    # csv_file="temp/Calling Data [Recording Url] - 100 - Data.csv",
    # json_file="summaries.json",
    # output_file="updated.csv"
    # )

    import pandas as pd

    df = pd.read_csv("updated.csv")
    print(df.head())
    
