# highlight-this-paper

Having just started my PhD, I've been thinking about the ways I could make my life a bit easier when going through papers. I figured it would be great if I could use an LLM to highlight and summarise the most salient parts for me.

<div style="text-align: center;">
    <img src="images/robot.png" alt="robot" width="50%">
</div>


Using the  GPT4o-mini model and the new Structured JSON output types, I did exactly that. It highlights and adds a summary as a comment on the top left corner of every page. Here's an example.

| Before | After |
|--------|-------|
| ![Before](images/before.png) | ![After](images/after.png) |

It's certainly far from perfect, and the code is quite messy to say the least, but it seems to work decently well. More examples in the `examples` folder.

(Working with PDFs is a nightmare, and I'll probably never do it again.)

You need to create an assistant yourself. Prompt and schema in the `assistant` folder. Create an `.env` folder and add `OPENAI_API_KEY` and `OPENAI_ASST_ID`.