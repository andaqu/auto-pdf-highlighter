# highlight-this-paper

## Project Overview

Having just started my PhD, I've been thinking about the ways I could make my life a bit easier when going through papers. I figured it would be great if I could use an LLM to highlight and summarise the most salient parts for me.

<p align="center">
  <img src="images/robot.png" alt="robot" width="30%">
</p> 


Using the GPT4o-mini model and the new Structured JSON output types, I did exactly that. It highlights and adds a summary as a comment on the top left corner of every page. Here's an example.

| Before | After |
|--------|-------|
| ![Before](images/before.png) | ![After](images/after.png) |

It's certainly far from perfect: there's a few assumptions that I have made + the code is quite messy to say the least, but it seems to work decently well from the ones I have tested. More examples in the `examples` folder.

## Setup

0. Create an OpenAI account, generate an API key, and create an assistant with the prompt and schema found within the `assistant` folder.

1. Install the required dependencies:
```
pip install openai pymupdf watchdog python-dotenv
```

2. Create a `.env` file in the same directory as the executable with the following content. 
   ```
   OPENAI_API_KEY=your_openai_api_key
   OPENAI_ASST_ID=your_openai_assistant_id
   MAIN_PATH=project_directory
   ```

3. Create a folder called `papers/` and within it, create three subfolders: `raw`,  `highlighted`, and `summaries`.

4. Usage:
   - Place PDF papers you want to process in the `raw` folder
   - Run `python service.py`
   - Processed and highlighted papers will appear in the `highlighted` folder and summaries will appear in the `summaries` folder
   - Files will be renamed as `{year}_{author}_{keyword}.pdf`

5. (Optional) Convert `service.py` to an executable:
   - This step is useful if you want to schedule the script to run automatically upon system startup.
   - If you prefer to run it as a Python script, you can skip this step.
   - To convert to an executable:
     - `pip install auto-py-to-exe`
     - Run `auto-py-to-exe` in your terminal within the project directory
     - Select 'One File' and 'Window Based' options
     - Choose `service.py` as the script location
     - Click "Convert .py to .exe"

6. Task Scheduling:
   - To schedule the task to run automatically on system startup:
     - Open Task Scheduler
     - Create a new task
     - Configure the task to start at system startup
     - Set the action to start the program (your executable)
     - Ensure the "Start in" field is set to the project folder
