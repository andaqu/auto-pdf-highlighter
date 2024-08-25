import os
import sys
import time
import re
import json
import pymupdf
from openai import OpenAI
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from dotenv import load_dotenv
from utils import get_bounding_boxes, find_words_to_highlight_v2
from tqdm import tqdm
import logging
import servicemanager
import win32event
import win32service
import win32serviceutil
import traceback

# Set up logging
logging.basicConfig(filename='pdf_processor_service.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASST_ID = os.getenv("OPENAI_ASST_ID")

if not OPENAI_API_KEY or not OPENAI_ASST_ID:
    logging.error("OpenAI API key or Assistant ID not found in .env file")
    raise ValueError("Missing OpenAI credentials")

# Initialize OpenAI client
try:
    client = OpenAI(api_key=OPENAI_API_KEY)
    thread = client.beta.threads.create()
    logging.info("OpenAI client initialized successfully")
except Exception as e:
    logging.error(f"Error initializing OpenAI client: {e}")
    raise

class PDFHandler(FileSystemEventHandler):
    def __init__(self, main_folder):
        self.main_folder = main_folder
        self.papers_folder = os.path.join(main_folder, "raw")
        self.highlighted_folder = os.path.join(main_folder, "highlighted")
        self.processing_folder = os.path.join(main_folder, "highlighted_processing")

        # Ensure folders exist
        for folder in [self.papers_folder, self.highlighted_folder]:
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
            
            # Rename the highlighted folder to highlighted_processing
            if os.path.exists(self.highlighted_folder):
                os.rename(self.highlighted_folder, self.processing_folder)
                logging.info(f"Renamed {self.highlighted_folder} to {self.processing_folder}")
            else:
                os.makedirs(self.processing_folder)
                logging.info(f"Created folder: {self.processing_folder}")

            # Process the PDF
            doc = pymupdf.open(file_path)
            all_highlights = []
            all_summaries = []

            for page_num, page in enumerate(tqdm(doc), start=1):
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
                    else:
                        logging.error(f"OpenAI run failed with status: {run.status}")
                        continue
                except Exception as e:
                    logging.error(f"Error in OpenAI API call: {e}")
                    continue

                all_highlights.extend(highlights)
                all_summaries.append(summary)

                failed_highlights = []
                for sentence_to_highlight in highlights:
                    try:
                        rects = page.search_for(sentence_to_highlight)
                        if rects:
                            page.add_highlight_annot(rects)
                            continue

                        words_to_highlight = find_words_to_highlight_v2(sentence_to_highlight, word_tuples)
                        if not words_to_highlight:
                            failed_highlights.append(sentence_to_highlight)
                            continue

                        line_bounding_boxes = get_bounding_boxes(words_to_highlight)
                        for line_index, bounding_box in line_bounding_boxes.items():
                            min_x, min_y, max_x, max_y = bounding_box
                            p1 = pymupdf.Point(min_x, min_y)
                            p2 = pymupdf.Point(max_x, max_y)
                            page.add_highlight_annot(quads=[p1, p2])
                    except Exception as e:
                        logging.error(f"Error highlighting sentence: {e}")
                        failed_highlights.append(sentence_to_highlight)

                if failed_highlights:
                    logging.warning(f"Failed to highlight {len(failed_highlights)}/{len(highlights)} sentences on page {page_num}")
                    logging.debug(f"Failed highlights: {failed_highlights}")

                try:
                    page.add_text_annot((10, 10), "Summary: " + summary, icon="Comment")
                except Exception as e:
                    logging.error(f"Error adding summary annotation: {e}")

                if stop:
                    logging.info("Stopping processing as requested by OpenAI response")
                    break

            output_path = os.path.join(self.processing_folder, os.path.basename(file_path))
            doc.save(output_path)
            logging.info(f"Saved processed PDF to: {output_path}")

        except Exception as e:
            logging.error(f"Error processing PDF {file_path}: {e}")

        finally:
            # Rename the folder back to "highlighted"
            if os.path.exists(self.processing_folder):
                os.rename(self.processing_folder, self.highlighted_folder)
                logging.info(f"Renamed {self.processing_folder} back to {self.highlighted_folder}")

class PDFProcessorService(win32serviceutil.ServiceFramework):
    _svc_name_ = "PDFProcessorService"
    _svc_display_name_ = "PDF Processor Service"

    def __init__(self, args):
        logging.info("PDFProcessorService __init__ started")
        try:
            win32serviceutil.ServiceFramework.__init__(self, args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self.observer = None
            logging.info("PDFProcessorService initialized successfully")
        except Exception as e:
            logging.error(f"Error in PDFProcessorService __init__: {str(e)}")
            logging.error(traceback.format_exc())
            raise

    def SvcStop(self):
        logging.info("SvcStop called")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)
        if self.observer:
            self.observer.stop()
        logging.info('Service stop pending...')

    def SvcDoRun(self):
        logging.info('SvcDoRun started')
        try:
            # Existing code
            self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
            logging.info('Service start pending...')
            self.main()
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            logging.info('Service running...')
            win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
        except Exception as e:
            logging.error(f"Error in SvcDoRun: {str(e)}")
            logging.error(traceback.format_exc())
            self.SvcStop()

    def main(self):
        logging.info("Entering main method")
        try:
            # Existing code
            main_folder = os.getenv("MAIN_PATH")
            logging.info(f"Main folder set to: {main_folder}")
            event_handler = PDFHandler(main_folder)
            logging.info("PDFHandler created")
            self.observer = Observer()
            logging.info("Observer created")
            watch_folder = os.path.join(main_folder, "raw")
            self.observer.schedule(event_handler, watch_folder, recursive=False)
            logging.info(f"Observer scheduled to watch folder: {watch_folder}")
            self.observer.start()
            logging.info("Observer started")
            logging.info("Main method completed successfully")
        except Exception as e:
            logging.error(f"Error in main method: {str(e)}")
            logging.error(traceback.format_exc())
            raise

if __name__ == '__main__':
    logging.info("Script started")
    if len(sys.argv) == 1:
        logging.info("Starting service")
        try:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(PDFProcessorService)
            servicemanager.StartServiceCtrlDispatcher()
        except Exception as e:
            logging.error(f"Error starting service: {str(e)}")
            logging.error(traceback.format_exc())
    else:
        logging.info(f"Handling command: {sys.argv[1]}")
        win32serviceutil.HandleCommandLine(PDFProcessorService)