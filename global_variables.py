import os


class EnviromentVariable:
    HUBSPOT_TOKEN = os.getenv("HUBSPOT_TOKEN")
    OUTPUT_DIR = os.getenv("OUTPUT_DIR")
    GEMINI_KEY = os.getenv("GEMINI_KEY")

