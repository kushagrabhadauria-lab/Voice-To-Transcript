import time
import schedule
from call_processor import CallProcessor, HUBSPOT_TOKEN, OUTPUT_DIR

def job():
    print("\n⏰ Scheduler triggered! Starting 6-hour processing cycle...\n")
    processor = CallProcessor(HUBSPOT_TOKEN, output_dir=OUTPUT_DIR)
    processor.process_recent_calls(hours=6)
    print("✅ Cycle completed. Waiting for next run...\n")

# Schedule job every 6 hours
schedule.every(6).hours.do(job)

if __name__ == "__main__":
    print("🚀 HubSpot Call Processor Scheduler started (runs every 6 hours).")
    job()  # Run immediately once on start

    while True:
        schedule.run_pending()
        time.sleep(60)
