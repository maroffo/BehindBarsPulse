# ABOUTME: Google Gemini AI service for content generation via Vertex AI.
# ABOUTME: Handles all LLM interactions for newsletter generation pipeline.

import json
import re
from time import sleep
from typing import Any

import structlog
from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from behind_bars_pulse.ai.prompts import (
    ENTITY_EXTRACTION_PROMPT,
    EXTRACT_INFO_PROMPT,
    FOLLOWUP_DETECTION_PROMPT,
    NEWSLETTER_CONTENT_PROMPT,
    PRESS_REVIEW_PROMPT,
    REVIEW_CONTENT_PROMPT,
    STORY_EXTRACTION_PROMPT,
)
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.models import (
    Article,
    ArticleInfo,
    EnrichedArticle,
    NewsletterContent,
    PressReviewCategory,
)

log = structlog.get_logger()


class AIService:
    """Service for interacting with Google Gemini AI."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        """Lazy-initialized Gemini client."""
        if self._client is None:
            self._client = genai.Client(
                vertexai=True,
                project=self.settings.gcp_project,
                location=self.settings.gcp_location,
            )
        return self._client

    def _generate_content_config(
        self,
        system_prompt: str,
        response_mime_type: str = "application/json",
    ) -> types.GenerateContentConfig:
        """Create generation config with safety settings disabled."""
        return types.GenerateContentConfig(
            temperature=self.settings.ai_temperature,
            top_p=self.settings.ai_top_p,
            max_output_tokens=self.settings.ai_max_output_tokens,
            response_modalities=["TEXT"],
            safety_settings=[
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
                types.SafetySetting(
                    category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                    threshold=types.HarmBlockThreshold.OFF,
                ),
            ],
            response_mime_type=response_mime_type,
            system_instruction=[types.Part.from_text(text=system_prompt)],
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        before_sleep=lambda retry_state: log.warning(
            "api_retry",
            attempt=retry_state.attempt_number,
            wait=retry_state.next_action.sleep,
        ),
        reraise=True,
    )
    def _generate(
        self,
        prompt: str,
        system_prompt: str,
        model: str | None = None,
        response_mime_type: str = "application/json",
        sleep_after: bool = True,
    ) -> str:
        """Generate content using the Gemini model.

        Includes retry logic with exponential backoff for rate limiting (429).

        Args:
            prompt: User prompt to send.
            system_prompt: System instructions.
            model: Model name override. Defaults to settings value.
            response_mime_type: Expected response format.
            sleep_after: Whether to sleep after the call for rate limiting.

        Returns:
            Generated text response.
        """
        model = model or self.settings.gemini_model
        log.debug("generating_content", model=model)

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=f'"{prompt}"')],
            ),
        ]

        config = self._generate_content_config(system_prompt, response_mime_type)
        result = ""

        for chunk in self.client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                result += chunk.text

        if sleep_after and self.settings.ai_sleep_between_calls > 0:
            sleep(self.settings.ai_sleep_between_calls)

        return result

    def _strip_markdown_fences(self, text: str) -> str:
        """Strip markdown code fences from LLM response.

        Gemini often wraps JSON responses in ```json ... ``` blocks.
        This method removes those fences to allow clean JSON parsing.

        Args:
            text: Raw LLM response text.

        Returns:
            Text with markdown code fences removed.
        """
        # Match ```json or ``` at start and ``` at end
        pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
        match = re.match(pattern, text.strip(), re.DOTALL)
        if match:
            return match.group(1).strip()
        return text.strip()

    def _parse_json_response(self, response: str) -> Any:
        """Parse JSON from LLM response, handling markdown fences.

        Args:
            response: Raw LLM response text.

        Returns:
            Parsed JSON data.

        Raises:
            json.JSONDecodeError: If response is not valid JSON.
        """
        cleaned = self._strip_markdown_fences(response)
        return json.loads(cleaned)

    def generate_press_review(
        self,
        articles: dict[str, Article],
    ) -> list[PressReviewCategory]:
        """Generate categorized press review from articles.

        Args:
            articles: Dictionary mapping URLs to Article objects.

        Returns:
            List of PressReviewCategory objects.
        """
        log.info("generating_press_review", article_count=len(articles))

        articles_json = json.dumps(
            {url: article.model_dump(mode="json") for url, article in articles.items()},
            indent=2,
        )

        response = self._generate(
            prompt=articles_json,
            system_prompt=PRESS_REVIEW_PROMPT,
        )

        raw_categories = self._parse_json_response(response)
        return [PressReviewCategory(**cat) for cat in raw_categories]

    def generate_newsletter_content(
        self,
        articles: dict[str, EnrichedArticle],
        previous_issues: list[str],
        narrative_context: object | None = None,
    ) -> NewsletterContent:
        """Generate newsletter title, subtitle, opening, and closing.

        Args:
            articles: Dictionary of enriched articles.
            previous_issues: List of previous newsletter texts for context.
            narrative_context: Optional NarrativeContext for story/character awareness.

        Returns:
            NewsletterContent with generated fields.
        """
        log.info("generating_newsletter_content")

        feed_content = self._aggregate_articles_content(articles)

        # Add narrative context if available
        if narrative_context:
            feed_content += self._format_narrative_context(narrative_context)

        if previous_issues:
            feed_content += "\n\nPrevious newsletter issues:"
            for issue in previous_issues:
                feed_content += "\n\n" + issue

        response = self._generate(
            prompt=feed_content,
            system_prompt=NEWSLETTER_CONTENT_PROMPT,
        )

        return NewsletterContent(**self._parse_json_response(response))

    def _format_narrative_context(self, context: object) -> str:
        """Format narrative context for inclusion in prompts.

        Args:
            context: NarrativeContext object (typed as object for import flexibility).

        Returns:
            Formatted string with narrative context information.
        """
        from datetime import date

        from behind_bars_pulse.narrative.models import NarrativeContext

        if not isinstance(context, NarrativeContext):
            return ""

        sections = ["\n\n=== CONTESTO NARRATIVO ==="]

        # Active stories
        active_stories = context.get_active_stories()
        if active_stories:
            sections.append("\n\nSTORIE IN CORSO (da seguire e collegare):")
            for story in sorted(active_stories, key=lambda s: s.mention_count, reverse=True)[:5]:
                sections.append(f"\n- {story.topic}: {story.summary}")
                if story.mention_count > 1:
                    sections.append(
                        f"  (Menzioni: {story.mention_count}, Impatto: {story.impact_score:.1f})"
                    )

        # Key characters
        if context.key_characters:
            sections.append("\n\nPERSONAGGI CHIAVE (riferimenti e posizioni recenti):")
            for char in context.key_characters[:5]:
                sections.append(f"\n- {char.name} ({char.role})")
                if char.positions:
                    latest = char.positions[-1]
                    sections.append(f"  Ultima posizione: {latest.stance}")

        # Due follow-ups
        due = context.get_due_followups(date.today())
        if due:
            sections.append("\n\nEVENTI DA MENZIONARE (scadenze raggiunte o imminenti):")
            for fu in due:
                sections.append(f"\n- {fu.event} (previsto: {fu.expected_date})")

        # Pending follow-ups
        pending = [f for f in context.get_pending_followups() if f not in due][:3]
        if pending:
            sections.append("\n\nEVENTI FUTURI (da anticipare ai lettori):")
            for fu in pending:
                sections.append(f"\n- {fu.event} (previsto: {fu.expected_date})")

        sections.append("\n\n=== FINE CONTESTO NARRATIVO ===")

        return "".join(sections)

    def review_newsletter_content(
        self,
        content: NewsletterContent,
        previous_issues: list[str],
    ) -> NewsletterContent:
        """Polish and refine newsletter content for style consistency.

        Args:
            content: Draft newsletter content.
            previous_issues: Previous newsletters for style reference.

        Returns:
            Refined NewsletterContent.
        """
        log.info("reviewing_newsletter_content")

        prompt = content.model_dump_json(indent=2)

        if previous_issues:
            prompt += "\n\nPrevious newsletter issues:"
            for issue in previous_issues:
                prompt += "\n\n" + issue

        response = self._generate(
            prompt=prompt,
            system_prompt=REVIEW_CONTENT_PROMPT,
        )

        return NewsletterContent(**self._parse_json_response(response))

    def extract_article_info(self, content: str) -> ArticleInfo:
        """Extract author, source, and summary from article content.

        Args:
            content: Raw article text.

        Returns:
            ArticleInfo with extracted metadata.
        """
        log.debug("extracting_article_info", content_preview=content[:50])

        response = self._generate(
            prompt=content,
            system_prompt=EXTRACT_INFO_PROMPT,
            model=self.settings.gemini_fallback_model,
            sleep_after=False,
        )

        infos = self._parse_json_response(response)
        return ArticleInfo(**infos[0])

    def enrich_articles(
        self,
        articles: dict[str, Article],
    ) -> dict[str, EnrichedArticle]:
        """Enrich articles with AI-extracted metadata.

        Args:
            articles: Dictionary mapping URLs to Article objects.

        Returns:
            Dictionary mapping URLs to EnrichedArticle objects.
        """
        log.info("enriching_articles", count=len(articles))

        enriched: dict[str, EnrichedArticle] = {}

        for url, article in articles.items():
            log.info("enriching_article", title=article.title[:30])

            info = self.extract_article_info(article.content)

            enriched[url] = EnrichedArticle(
                title=article.title,
                link=article.link,
                content=article.content,
                author=info.author,
                source=info.source,
                summary=info.summary,
            )

        return enriched

    def _aggregate_articles_content(self, articles: dict[str, EnrichedArticle]) -> str:
        """Aggregate article content into a single text for AI processing."""
        feed_content = ""

        for article in articles.values():
            feed_content += f"Titolo: {article.title}\n"
            feed_content += f"Link: {article.link}\n"
            feed_content += f"Autore: {article.author}\n"
            feed_content += f"Fonte: {article.source}\n"
            feed_content += f"Contenuto: ```{article.content}```\n"
            feed_content += "---\n"

        return feed_content

    def extract_stories(
        self,
        articles: dict[str, EnrichedArticle],
        existing_stories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract new and updated story threads from articles.

        Args:
            articles: Dictionary of enriched articles.
            existing_stories: List of existing story dicts with id, topic, summary, keywords.

        Returns:
            Dictionary with 'updated_stories' and 'new_stories' lists.
        """
        log.info("extracting_stories", article_count=len(articles))

        prompt_data = {
            "articles": {
                url: {
                    "title": a.title,
                    "link": str(a.link),
                    "summary": a.summary,
                    "content": a.content[:1000],
                }
                for url, a in articles.items()
            },
            "existing_stories": existing_stories,
        }

        response = self._generate(
            prompt=json.dumps(prompt_data, indent=2, ensure_ascii=False),
            system_prompt=STORY_EXTRACTION_PROMPT,
        )

        return self._parse_json_response(response)

    def extract_entities(
        self,
        articles: dict[str, EnrichedArticle],
        existing_characters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Extract new and updated character information from articles.

        Args:
            articles: Dictionary of enriched articles.
            existing_characters: List of existing character dicts with name, role, aliases.

        Returns:
            Dictionary with 'updated_characters' and 'new_characters' lists.
        """
        log.info("extracting_entities", article_count=len(articles))

        prompt_data = {
            "articles": {
                url: {
                    "title": a.title,
                    "link": str(a.link),
                    "content": a.content[:1500],
                }
                for url, a in articles.items()
            },
            "existing_characters": existing_characters,
        }

        response = self._generate(
            prompt=json.dumps(prompt_data, indent=2, ensure_ascii=False),
            system_prompt=ENTITY_EXTRACTION_PROMPT,
        )

        return self._parse_json_response(response)

    def detect_followups(
        self,
        articles: dict[str, EnrichedArticle],
        story_ids: list[str],
    ) -> dict[str, Any]:
        """Detect upcoming events and deadlines from articles.

        Args:
            articles: Dictionary of enriched articles.
            story_ids: List of existing story IDs for linking.

        Returns:
            Dictionary with 'followups' list.
        """
        log.info("detecting_followups", article_count=len(articles))

        prompt_data = {
            "articles": {
                url: {
                    "title": a.title,
                    "link": str(a.link),
                    "content": a.content[:1500],
                }
                for url, a in articles.items()
            },
            "existing_story_ids": story_ids,
        }

        response = self._generate(
            prompt=json.dumps(prompt_data, indent=2, ensure_ascii=False),
            system_prompt=FOLLOWUP_DETECTION_PROMPT,
        )

        return self._parse_json_response(response)
