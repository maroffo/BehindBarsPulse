# ABOUTME: Google Gemini AI service for content generation.
# ABOUTME: Handles all LLM interactions for newsletter generation pipeline.

import html
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
    FIRST_ISSUE_INTRO,
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
            if not self.settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required")
            self._client = genai.Client(
                api_key=self.settings.gemini_api_key.get_secret_value(),
            )
        return self._client

    def _generate_content_config(
        self,
        system_prompt: str,
        response_mime_type: str = "application/json",
        response_schema: dict[str, Any] | None = None,
    ) -> types.GenerateContentConfig:
        """Create generation config with safety settings disabled."""
        config = types.GenerateContentConfig(
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
        if response_schema:
            config.response_json_schema = response_schema
        return config

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
        response_schema: dict[str, Any] | None = None,
        sleep_after: bool = True,
    ) -> str:
        """Generate content using the Gemini model.

        Includes retry logic with exponential backoff for rate limiting (429).

        Args:
            prompt: User prompt to send.
            system_prompt: System instructions.
            model: Model name override. Defaults to settings value.
            response_mime_type: Expected response format.
            response_schema: JSON schema for structured output (guarantees valid JSON).
            sleep_after: Whether to sleep after the call for rate limiting.

        Returns:
            Generated text response.
        """
        model = model or self.settings.gemini_model
        log.debug(
            "generating_content",
            model=model,
            prompt_length=len(prompt),
            system_prompt_length=len(system_prompt),
        )

        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            ),
        ]

        config = self._generate_content_config(system_prompt, response_mime_type, response_schema)
        result = ""
        chunk_count = 0
        finish_reason = None

        for chunk in self.client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            chunk_count += 1

            # Check for safety blocks or other issues
            if hasattr(chunk, "candidates") and chunk.candidates:
                candidate = chunk.candidates[0]
                if hasattr(candidate, "finish_reason") and candidate.finish_reason:
                    finish_reason = candidate.finish_reason

            if chunk.text:
                result += chunk.text

        log.debug(
            "generation_complete",
            chunk_count=chunk_count,
            result_length=len(result),
            finish_reason=str(finish_reason) if finish_reason else None,
        )

        # Log warning if empty response
        if not result.strip():
            log.warning(
                "empty_generation_result",
                chunk_count=chunk_count,
                finish_reason=str(finish_reason) if finish_reason else "unknown",
                prompt_preview=prompt[:200] if len(prompt) > 200 else prompt,
            )

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

    def _fix_json_trailing_commas(self, text: str) -> str:
        """Remove trailing commas from JSON (common LLM error).

        Args:
            text: JSON text that may have trailing commas.

        Returns:
            JSON text with trailing commas removed.
        """
        # Remove trailing commas before } or ]
        text = re.sub(r",\s*}", "}", text)
        text = re.sub(r",\s*]", "]", text)
        return text

    def _unescape_html_entities(self, data: Any) -> Any:
        """Recursively unescape HTML entities in parsed JSON data.

        LLMs sometimes return HTML-escaped content like &#39; instead of '.

        Args:
            data: Parsed JSON data (dict, list, or primitive).

        Returns:
            Data with all string values unescaped.
        """
        if isinstance(data, str):
            return html.unescape(data)
        if isinstance(data, dict):
            return {k: self._unescape_html_entities(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._unescape_html_entities(item) for item in data]
        return data

    def _parse_json_response(self, response: str) -> Any:
        """Parse JSON from LLM response, handling common issues.

        Handles:
        - Empty responses
        - Markdown code fences (```json ... ```)
        - Trailing commas (common LLM error)

        Args:
            response: Raw LLM response text.

        Returns:
            Parsed JSON data.

        Raises:
            ValueError: If response is empty.
            json.JSONDecodeError: If response is not valid JSON after fixes.
        """
        if not response or not response.strip():
            log.error("empty_llm_response")
            raise ValueError("LLM returned empty response")

        cleaned = self._strip_markdown_fences(response)
        cleaned = self._fix_json_trailing_commas(cleaned)

        try:
            data = json.loads(cleaned)
            # Unescape HTML entities (LLMs sometimes return &#39; instead of ')
            return self._unescape_html_entities(data)
        except json.JSONDecodeError as e:
            # Log the problematic response for debugging
            log.error(
                "json_parse_failed",
                error=str(e),
                response_preview=cleaned[:500] if len(cleaned) > 500 else cleaned,
            )
            raise

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
        from pydantic import TypeAdapter

        log.info("generating_press_review", article_count=len(articles))

        articles_json = json.dumps(
            {url: article.model_dump(mode="json") for url, article in articles.items()},
            indent=2,
        )

        # Use structured output with JSON schema for guaranteed valid JSON
        schema = TypeAdapter(list[PressReviewCategory]).json_schema()

        response = self._generate(
            prompt=articles_json,
            system_prompt=PRESS_REVIEW_PROMPT,
            response_schema=schema,
        )

        # With structured output, response is guaranteed valid JSON
        raw_categories = json.loads(response)
        return [PressReviewCategory(**cat) for cat in raw_categories]

    def generate_newsletter_content(
        self,
        articles: dict[str, EnrichedArticle],
        previous_issues: list[str],
        narrative_context: object | None = None,
        first_issue: bool = False,
    ) -> NewsletterContent:
        """Generate newsletter title, subtitle, opening, and closing.

        Args:
            articles: Dictionary of enriched articles.
            previous_issues: List of previous newsletter texts for context.
            narrative_context: Optional NarrativeContext for story/character awareness.
            first_issue: If True, include introductory text explaining the newsletter.

        Returns:
            NewsletterContent with generated fields.
        """
        feed_content = self._aggregate_articles_content(articles)

        # Add narrative context if available
        if narrative_context:
            feed_content += self._format_narrative_context(narrative_context)

        if previous_issues:
            feed_content += "\n\nPrevious newsletter issues:"
            for issue in previous_issues:
                feed_content += "\n\n" + issue

        # Build system prompt, prepending first issue intro if needed
        system_prompt = NEWSLETTER_CONTENT_PROMPT
        if first_issue:
            system_prompt = FIRST_ISSUE_INTRO + system_prompt

        log.info(
            "generating_newsletter_content",
            article_count=len(articles),
            prompt_chars=len(feed_content),
            previous_issues_count=len(previous_issues) if previous_issues else 0,
            has_narrative_context=narrative_context is not None,
            first_issue=first_issue,
        )

        response = self._generate(
            prompt=feed_content,
            system_prompt=system_prompt,
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
        failed_count = 0

        for url, article in articles.items():
            log.info("enriching_article", title=article.title[:30])

            try:
                info = self.extract_article_info(article.content)
                author = info.author
                source = info.source
                summary = info.summary
            except Exception as e:
                # If enrichment fails for any reason (API error, parsing, etc.), use defaults
                error_type = type(e).__name__
                log.warning(
                    "article_enrichment_failed",
                    title=article.title[:30],
                    error_type=error_type,
                    error=str(e)[:100],
                )
                author = "Sconosciuto"
                source = "Ristretti Orizzonti"
                summary = ""
                failed_count += 1

                # If we hit rate limiting, add extra delay before next attempt
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    log.warning("rate_limit_hit_adding_delay", delay=60)
                    sleep(60)

            enriched[url] = EnrichedArticle(
                title=article.title,
                link=article.link,
                content=article.content,
                author=author,
                source=source,
                summary=summary,
            )

        if failed_count > 0:
            log.warning(
                "enrichment_completed_with_failures", failed=failed_count, total=len(articles)
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
