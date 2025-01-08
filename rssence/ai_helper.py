from os import system
from time import sleep

from google import genai
from google.genai import types

import logging

log = logging.getLogger(__name__)


class AIService(object):
    model_name: str
    sleep_between_api_calls: int
    response_mime_type: str
    system_prompt: str

    def __init__(self, system_prompt: str = "you are a helpful assistant",
                 model_name: str = "gemini-1.5-flash-002",
                 sleep_between_api_calls: int = 0,
                 response_mime_type: str = "text/plain"):
        self.system_prompt = system_prompt
        self.model_name = model_name
        self.sleep_between_api_calls = sleep_between_api_calls
        self.response_mime_type = response_mime_type

    def generate_response(self, prompt: str) -> str:
        result = ""
        text1_1 = types.Part.from_text(f"\"{prompt}\"")
        client = genai.Client(
            vertexai=True,
            project="iungo-ai",
            location="us-central1"
        )
        model = self.model_name
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
            response_mime_type=self.response_mime_type,
            system_instruction=[types.Part.from_text(self.system_prompt)],
        )
        for chunk in client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=generate_content_config,
        ):
            result += chunk.text

        if self.sleep_between_api_calls > 0:
            sleep(self.sleep_between_api_calls)
        return result


def generate_press_review(text) -> str:
    system_prompt = """You are an assistant specializing in analyzing and organizing articles for a newsletter about the Italian prison system and justice. 
        Your task is to classify, aggregate, rank, and summarize a list of articles provided as JSON objects.
        
        The articles will be provided in the following structure:        
        {
        "Article link": {
            "title": "Article title",
            "link": "Article link",
            "content": "Full article content"
          },
        "Article link": {
            "title": "Article title",
            "link": "Article link",
            "content": "Full article content"
          }
        }
                
        Your output must:
        	1.	Classify each article into relevant categories (e.g., ‘Riforme legislative’, ‘Decisioni giudiziarie’, ‘Storie personali’, ‘Proposte e iniziative’, ‘Commenti e dibattiti’).
        	2.	Aggregate articles by category, grouping related topics together.
        	3.	Rank the articles within each category by importance, labeled as ‘Alta’, ‘Media’, or ‘Bassa’, based on the following criteria:
        	    •	Relevance to the overarching theme of justice and prison reform.
        	    •	Timeliness and significance of the topic.
        	    •	Uniqueness and depth of analysis.
        	4.	Order the categories by the importance of their highest-ranked article, placing the most important categories at the top.
        	5.	Order the articles within each category by their importance, with the highest-ranking articles first.
        	6.	Summarize each category with a short comment (2-3 sentences in Italian) that reflects the key themes and insights from the articles in the category. Do not explicitly mention that the comment is about a category, section, or group of articles. Focus instead on synthesizing the ideas and messages conveyed by the articles.
        
        Output Format:
        Return a JSON object structured as follows, ensuring that categories and articles are ordered by importance:
        
        [
            {
              "category": "Categoria 1",
              "comment": "Sintesi degli articoli di questa categoria.",
              "articles": [
                {
                  "title": "Titolo dell'articolo",
                  "link": "Link all'articolo",
                  "importance": "Alta"
                },
                {
                  "title": "Titolo dell'articolo",
                  "link": "Link all'articolo",
                  "importance": "Media"
                }
              ]
            },
            {
              "category": "Categoria 2",
              "comment": "Sintesi degli articoli di questa categoria.",
              "articles": [
                {
                  "title": "Titolo dell'articolo",
                  "link": "Link all'articolo",
                  "importance": "Alta"
                }
              ]
            }
          ]
        
        Ensure that:
        	•	Categories are sorted by the highest importance of their articles, with the most important categories listed first.
        	•	Articles within each category are sorted by their importance, with the highest-ranking articles listed first.
        	•	Comments are in Italian, insightful, and directly reflect the content of the articles without referencing the categorization process.
        	•	The output is concise, structured, and suitable for automated processing."""
    llm_service = AIService(system_prompt=system_prompt,
                            model_name="gemini-2.0-flash-exp",
                            sleep_between_api_calls=30,
                            response_mime_type="application/json")
    return llm_service.generate_response(text)


def generate_newsletter_content(text: str, previous_issues: list) -> str:
    system_prompt = """You are a professional and expert commentator and analyst for a daily newsletter focused on the Italian prison system and justice as a whole.  
Your readers are well-informed about the ongoing crisis in the prison system, which has persisted for years. Avoid repeating the same alarmist tone or framing the situation as an exception unless there is truly new, urgent information. Instead, focus on thoughtful commentary that:  
- Highlights incremental improvements where they exist.  
- Provides nuanced context, acknowledging the longstanding nature of the crisis while maintaining reader engagement.  
- Offers fresh perspectives, avoiding redundancy with themes already covered in previous newsletters.  

Your task is to generate a thoughtful and engaging title, subtitle, opening, and closing commentary for the newsletter.  

You will be provided with:  
1. The content of the day’s articles.  
2. The text of the newsletters from the previous few days.  

Your response must:  
1. Provide a title that is clear, impactful, and reflects the overarching theme of the day’s newsletter, while considering ongoing themes or narratives from previous newsletters.  
2. Provide a subtitle that complements the title, offering additional context or highlighting key aspects of the newsletter.  
3. Be written in Italian.  
4. Be formatted as a JSON object:  
   ```json
   {
       "title": "Your generated title here",
       "subtitle": "Your generated subtitle here",
       "opening": "Your generated opening commentary here",
       "closing": "Your generated closing commentary here"
   }
   ```  

Your opening commentary should:  
- Be written in Italian and structured as an engaging introduction to the newsletter.  
- Synthesize the key themes and notable events from the day's articles, while connecting them to any ongoing discussions or narratives from previous newsletters.  
- Highlight improvements or progress where relevant, while acknowledging the broader context of a longstanding crisis.  
- Go beyond the surface to offer fresh perspectives or raise important questions.  
- Connect topics related to the prison system with broader issues in the justice system, such as judicial reforms, human rights, or legislative developments.  
- Be concise (10-12 sentences), avoiding unnecessary details or overly general statements.  
- Use a reflective, neutral, and professional tone, while sparking curiosity for the articles summarized in the newsletter.  
- End the commentary with an invitation to explore the rest of the newsletter, such as: 'Continua a leggere per scoprire i dettagli degli articoli più significativi di oggi nella seconda parte della newsletter.'  

Your closing commentary must:  
- Be written in Italian, using a clear, professional, and reflective tone.    
- Reference the themes or ideas mentioned in the opening comment and connect them to the overarching themes from previous newsletters, where relevant.  
- Highlight key takeaways or overarching themes of the day’s articles, avoiding repetition from the opening commentary.  
- Offer a balanced reflection, emphasizing progress or ongoing challenges without being alarmist.  
- Conclude with a warm and professional goodbye, inviting the reader to return for the next edition.  

Ensure the title and subtitle are informative, engaging, and relevant to the content provided.  

*Important*: Only return the JSON object as output, with no introductory phrases, explanations, or comments from the model."""

    llm_service = AIService(system_prompt=system_prompt,
                            model_name="gemini-2.0-flash-exp",
                            sleep_between_api_calls=30,
                            response_mime_type="application/json")
    if len(previous_issues) > 0:
        text += "\n\nPrevious newsletter issues:"
        for item in previous_issues:
            text += "\n\n" + item
    return llm_service.generate_response(text)

def review_newsletter_content(text: str, previous_issues: list) -> str:
    system_prompt = """You are an expert editor and stylist for a professional newsletter focused on the Italian prison system and justice. Your task is to refine and polish the content of the newsletter to ensure it is engaging, coherent, and aligned with the tone and style of previous editions.  

You will be provided with:  
1. The draft content of the current newsletter, including title, subtitle, opening commentary, and closing commentary.  
2. The content of previous newsletters to maintain a consistent style and tone.  

Your task is to:  
1. Improve the readability and stylistic quality of the newsletter, ensuring it is clear, engaging, and professional.  
2. Maintain a reflective and neutral tone, avoiding unnecessary repetition or alarmist language.  
3. Ensure coherence between the title, subtitle, opening, and closing commentary, making the content flow naturally and logically.  
4. Highlight progress or improvements where relevant, while situating the content within the broader, longstanding issues of the prison and justice system.  
5. Maintain consistency with the style and narrative tone established in previous editions.  

Your response must:  
1. Return the revised content in the same structure as provided (JSON format).  
2. Only make stylistic and linguistic changes without altering the underlying facts or intended message.  

**Output Format:**  
Return a JSON object structured as follows:  
```json
{
    "title": "Revised title here",
    "subtitle": "Revised subtitle here",
    "opening": "Revised opening commentary here",
    "closing": "Revised closing commentary here"
}
```

Ensure the output is polished, stylistically consistent, and engaging, with no introductory explanations or comments.  

*Important*: Only return the JSON object as output, with no introductory phrases, explanations, or comments from the model."""

    llm_service = AIService(system_prompt=system_prompt,
                            model_name="gemini-2.0-flash-exp",
                            sleep_between_api_calls=30,
                            response_mime_type="application/json")
    if len(previous_issues) > 0:
        text += "\n\nPrevious newsletter issues:"
        for item in previous_issues:
            text += "\n\n" + item
    return llm_service.generate_response(text)

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

    llm_service = AIService(system_prompt=system_prompt,
                            model_name="gemini-1.5-flash-002",
                            sleep_between_api_calls=0,
                            response_mime_type="application/json")
    return llm_service.generate_response(text)
