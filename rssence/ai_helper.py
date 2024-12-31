from google import genai
from google.genai import types


def generate_comment(text) -> str:
    system_prompt = """You are a professional commentator and analyst for a daily newsletter focused on the Italian prison system and justice as a whole. Your readers are well-informed about the ongoing crisis in the prison system, so avoid providing obvious or redundant information. Instead, focus on delivering insightful, engaging commentary that highlights the most relevant and thought-provoking themes of the day.
        Your commentary should:
        - Be written in Italian and structured as an engaging introduction to the newsletter.
        - Synthesize the key themes and notable events from the day's articles, going beyond the surface to offer fresh perspectives or raise important questions.
        - Connect topics related to the prison system with broader issues in the justice system, such as judicial reforms, human rights, or legislative developments.
        - Be concise (10-12 sentences), avoiding unnecessary details or overly general statements.
        - Use a reflective, neutral, and professional tone, while sparking curiosity for the articles summarized in the newsletter.
        - End the commentary with an invitation to explore the rest of the newsletter, such as: 'Continua a leggere per scoprire i dettagli degli articoli più significativi di oggi nella seconda parte della newsletter.'"""
    return generate_with_llm(system_prompt, text, "text/plain")


def extract_infos(text) -> str:
    json_schema = {}

    system_prompt = """You are an assistant specialized in summarizing articles for a daily newsletter written in Italian. 
    Your task is to summarize articles concisely, including essential information. Each summary must:
	1.	Highlight the key points and main message of the article.
	2.	Be written in clear and simple Italian, using a neutral and informative tone.
	3.	Include the author’s name, if available, and cite the original source, specifying if the article was published on another website or newspaper.
	4.	Be no longer than 3-5 sentences, avoiding unnecessary details or repetitive information.
	5.	Conclude with a reflection or call to action, if relevant (e.g., ‘This highlights a critical issue for the Italian penal system’).

    Example structure for the summary:
	•	Author: [Author Name, if available]
	•	Source: [Name of the original newspaper or website]
	•	Summary: [Article summary]
	
	The output must be an array of JSON objects, one for each translated sentence. Do not add any extra comments or text besides the requested data. Below is an example of the output format:
    [{
        "author": "Author Name, if available",
        "source": "Name of the original source newspaper or website",
        "summary": "Article summary",
      }]"""

    return generate_with_llm(system_prompt, text, "application/json")


def generate_with_llm(system_prompt, text, response_mime_type) -> str:
    result = ""
    text1_1 = types.Part.from_text(f"\"{text}\"")
    client = genai.Client(
        vertexai=True,
        project="iungo-ai",
        location="us-central1"
    )
    model = "gemini-2.0-flash-exp"
    # model = "gemini-1.5-flash-002"
    contents = [
        types.Content(
            role="user",
            parts=[
                text1_1
            ]
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        temperature=1,
        top_p=0.95,
        max_output_tokens=8192,
        response_modalities=["TEXT"],
        safety_settings=[types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="OFF"
        ), types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="OFF"
        ), types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="OFF"
        ), types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="OFF"
        )],
        response_mime_type=response_mime_type,
        # response_schema=json_schema,
        system_instruction=[types.Part.from_text(system_prompt)],
    )
    for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=generate_content_config,
    ):
        result += chunk.text
    return result
