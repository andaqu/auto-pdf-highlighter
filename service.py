from utils import get_bounding_boxes, find_words_to_highlight_v2, GoogleDriveHelper
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from notion_client import Client
from dotenv import load_dotenv
from openai import OpenAI
import traceback
import datetime
import pymupdf
import logging
import json
import time
import csv
import os

# Load environment variables
load_dotenv()

MAIN_PATH = os.getenv("MAIN_PATH") + "\papers"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASST_ID = os.getenv("OPENAI_ASST_ID")
OPENAI_ASST2_ID = os.getenv("OPENAI_ASST2_ID")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Set up logging
log_file_path = os.path.join(MAIN_PATH, "service.log")
logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if not OPENAI_API_KEY or not OPENAI_ASST_ID:
    logging.error("OpenAI API key or Assistant ID not found in .env file")
    raise ValueError("Missing OpenAI credentials")

# Initialize OpenAI client
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    logging.info("OpenAI client initialized successfully")
except Exception as e:
    logging.error(f"Error initializing OpenAI client: {e}")
    raise

# Initialize Google Drive helper
google_drive_helper = GoogleDriveHelper()
google_drive_helper.authenticate_google_drive()

# Initialize Notion client
notion = Client(auth=NOTION_API_KEY)

class PDFHandler(FileSystemEventHandler):
    def __init__(self, main_folder):
        self.main_folder = main_folder
        self.papers_folder = os.path.join(main_folder, "raw")
        self.highlighted_folder = os.path.join(main_folder, "highlighted")
        self.processing_folder = os.path.join(main_folder, "highlighted_processing")
        self.summaries_folder = os.path.join(main_folder, "summaries")

        # Ensure folders exist
        for folder in [self.papers_folder, self.highlighted_folder, self.summaries_folder]:
            if not os.path.exists(folder):
                os.makedirs(folder)
                logging.info(f"Created folder: {folder}")

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.pdf') and os.path.dirname(event.src_path) == self.papers_folder:
            logging.info(f"New PDF detected: {event.src_path}")
            self.process_pdf(event.src_path)

    def process_pdf(self, file_path):
        try:
            logging.info(f"Starting to process: {file_path}")
            
            thread = client.beta.threads.create()
            thread_id = thread.id
            
            # Rename the highlighted folder to highlighted_processing
            if os.path.exists(self.highlighted_folder):
                os.rename(self.highlighted_folder, self.processing_folder)
                logging.info(f"Renamed {self.highlighted_folder} to {self.processing_folder}")
            else:
                os.makedirs(self.processing_folder)
                logging.info(f"Created folder: {self.processing_folder}")

            # Process the PDF
            doc = pymupdf.open(file_path)
            all_highlights_success = {}
            all_highlights_fail = {}
            all_summaries = {}
            total_prompt_tokens = 0
            total_completion_tokens = 0
            highlights_success_count = 0
            highlights_fail_count = 0

            # Get the first page content
            first_page = doc[0]
            first_page_text = first_page.get_text("text")
            first_page_text = first_page_text.replace("\n", " ").replace("- ", "")

            # Generate title using GPT-4
            prompt = f"Give me a lowercase name given the following content. It must be in the format of '{{first_author_surname}}_{{year_the_paper_was_published}}_{{main_singular_key_word}}'. Only return the file name. Content:\n\n{first_page_text}"
            
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}]
                )
                new_title = response.choices[0].message.content
                total_prompt_tokens += response.usage.prompt_tokens
                total_completion_tokens += response.usage.completion_tokens
                logging.info(f"Generated new title: {new_title}")
            except Exception as e:
                logging.error(f"Error generating title: {e}")
                new_title = os.path.basename(file_path)  # Use original filename if title generation fails

            for page_num, page in enumerate(doc, start=1):
                logging.info(f"Processing page {page_num}")
                text = page.get_text("text")
                text = text.replace("\n", " ").replace("- ", "")
                word_tuples = page.get_text("words", flags=pymupdf.TEXT_DEHYPHENATE)

                try:
                    message = client.beta.threads.messages.create(
                        thread_id=thread.id,
                        role="user",
                        content=text
                    )

                    for attempt in range(2):
                        run = client.beta.threads.runs.create_and_poll(
                            thread_id=thread.id,
                            assistant_id=OPENAI_ASST_ID
                        )

                        if run.status == 'completed':
                            messages = client.beta.threads.messages.list(
                                thread_id=thread.id
                            )
                            response = json.loads(messages.data[0].content[0].text.value)
                            
                            summary = response["summary"]
                            highlights = response["highlights"]
                            stop = response["stop"]
                            total_completion_tokens += run.usage.completion_tokens
                            total_prompt_tokens += run.usage.prompt_tokens
                            break

                        else:
                            if attempt == 0:
                                logging.warning(f"OpenAI run failed with status: {run.status}. Retrying in 2 seconds...")
                                time.sleep(2)
                            else:
                                logging.error(f"OpenAI run failed again with status: {run.status}. Skipping this page.")
                                continue
                    else:
                        # This will execute if the for loop completes without breaking
                        logging.error("Failed to get a completed run after two attempts. Skipping this page.")
                        continue
                except Exception as e:
                    logging.error(f"Error in OpenAI API call: {e}")
                    continue

                all_summaries[page_num] = summary

                highlights_success = []
                highlights_fail = []
                for sentence_to_highlight in highlights:
                    try:
                        rects = page.search_for(sentence_to_highlight)
                        if rects:
                            page.add_highlight_annot(rects)
                            highlights_success.append(sentence_to_highlight)
                            highlights_success_count += 1
                            continue

                        words_to_highlight = find_words_to_highlight_v2(sentence_to_highlight, word_tuples)
                        if not words_to_highlight:
                            highlights_fail.append(sentence_to_highlight)
                            highlights_fail_count += 1
                            continue

                        line_bounding_boxes = get_bounding_boxes(words_to_highlight)
                        for line_index, bounding_box in line_bounding_boxes.items():
                            min_x, min_y, max_x, max_y = bounding_box
                            p1 = pymupdf.Point(min_x, min_y)
                            p2 = pymupdf.Point(max_x, max_y)
                            page.add_highlight_annot(quads=[p1, p2])
                        highlights_success.append(sentence_to_highlight)
                        highlights_success_count += 1
                    except Exception as e:
                        logging.error(f"Error highlighting sentence: {e}")
                        highlights_fail.append(sentence_to_highlight)
                        highlights_fail_count += 1

                all_highlights_success[page_num] = highlights_success
                all_highlights_fail[page_num] = highlights_fail

                if highlights_fail:
                    logging.warning(f"Failed to highlight {len(highlights_fail)}/{len(highlights)} sentences on page {page_num}")
                    logging.debug(f"Failed highlights: {highlights_fail}")

                try:
                    page.add_text_annot((10, 10), "Summary: " + summary, icon="Comment")
                except Exception as e:
                    logging.error(f"Error adding summary annotation: {e}")

                if stop:
                    logging.info("Stopping processing as requested by OpenAI response")
                    break

            file_url = None

            try:
                file_id = google_drive_helper.upload_file_to_drive(doc, new_title, GOOGLE_DRIVE_FOLDER_ID)

                # Make the file shareable and get the shareable link
                file_url = google_drive_helper.make_file_shareable(file_id)
                
                logging.info(f"File uploaded to Google Drive: {file_url}")

            except Exception as e:
                logging.error(f"Error saving to Google Drive: {e}")

            try:
                self.summarise_to_notion(thread_id, new_title, file_url)
            except Exception as e:
                logging.error(f"Error saving to Notion: {e}")

            # Save to CSV
            csv_path = os.path.join(self.main_folder, 'saves.csv')
            with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                if csvfile.tell() == 0:  # File is empty, write header
                    writer.writerow([
                        'filename',
                        'highlights_success',
                        'highlights_fail',
                        'summaries',
                        'highlights_success_count',
                        'highlights_fail_count',
                        'total_completion_tokens',
                        'total_prompt_tokens',
                        'thread_id'
                    ])
                writer.writerow([
                    f"{new_title}.pdf",
                    json.dumps(all_highlights_success),
                    json.dumps(all_highlights_fail),
                    json.dumps(all_summaries),
                    highlights_success_count,
                    highlights_fail_count,
                    total_completion_tokens,
                    total_prompt_tokens,
                    thread_id
                ])
            logging.info(f"Saved data to CSV: {csv_path}")

            # Save summaries to markdown file
            markdown_content = ""
            for page_num, summary in all_summaries.items():
                markdown_content += f"## Page {page_num}\n\n{summary}\n\n"

            markdown_path = os.path.join(self.summaries_folder, f"{new_title}.md")
            with open(markdown_path, 'w', encoding='utf-8') as md_file:
                md_file.write(markdown_content)
            logging.info(f"Saved summaries to markdown file: {markdown_path}")

        except Exception as e:
            logging.error(f"Error processing PDF {file_path}: {str(e)}")
            logging.error(traceback.format_exc())  # Add this line to get the full stack trace

        finally:
            # Rename the folder back to "highlighted"
            if os.path.exists(self.processing_folder):
                os.rename(self.processing_folder, self.highlighted_folder)
                logging.info(f"Renamed {self.processing_folder} back to {self.highlighted_folder}")

    def summarise_to_notion(self, thread_id, file_name, file_url):

        props = {}

        message = client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=" "
        )

        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=OPENAI_ASST2_ID
        )

        if run.status == 'completed': 
            messages = client.beta.threads.messages.list(
                thread_id=thread_id
            )
                
            data = json.loads(messages.data[0].content[0].text.value)

            props["Title"] = {"rich_text": [{"text": {"content": data["title"]}}]}
            props["Goal"] = {"rich_text": [{"text": {"content": data["goal"]}}]}
            props["Method"] = {"rich_text": [{"text": {"content": data["method"]}}]}
            props["Data"] = {"rich_text": [{"text": {"content": data["data"]}}]}
            props["Results"] = {"rich_text": [{"text": {"content": data["results"]}}]}
            props["Pros"] = {"rich_text": [{"text": {"content": data["pros"]}}]}
            props["Cons"] = {"rich_text": [{"text": {"content": data["cons"]}}]}
            props["Implications"] = {"rich_text": [{"text": {"content": data["implications"]}}]}
            props["Limitations"] = {"rich_text": [{"text": {"content": data["limitations"]}}]}
            props["Date"] = {"date": {"start": datetime.datetime.now().isoformat()}}

        if file_url:
            props["Name"] = {"title": [{"text": {"content": file_name, "link": {"url": file_url}}}]}
        else:
            props["Name"] = {"title": [{"text": {"content": file_name}}]}

        notion.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties=props
        )

def main():
    logging.debug("Entering main function")
    try:
        logging.info(f"Main folder set to: {MAIN_PATH}")

        event_handler = PDFHandler(MAIN_PATH)
        logging.info("PDFHandler created")

        observer = Observer()
        logging.info("Observer created")

        watch_folder = os.path.join(MAIN_PATH, "raw")

        observer.schedule(event_handler, watch_folder, recursive=False)
        logging.info(f"Observer scheduled to watch folder: {watch_folder}")

        observer.start()
        logging.info("Observer started")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
        
    except Exception as e:
        logging.error(f"Error in main function: {str(e)}")
        logging.error(traceback.format_exc())
        raise

if __name__ == '__main__':
    logging.info("Script started")
    main()