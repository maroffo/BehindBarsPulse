# ABOUTME: Vertex AI Batch Inference service for newsletter generation.
# ABOUTME: Handles JSONL creation, GCS upload, and batch job submission.

import json
import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

import structlog
from google.cloud import storage
from pydantic import TypeAdapter

from behind_bars_pulse.ai.prompts import (
    CAPACITY_EXTRACTION_PROMPT,
    ENTITY_EXTRACTION_PROMPT,
    EXTRACT_INFO_PROMPT,
    FOLLOWUP_DETECTION_PROMPT,
    INCIDENT_EXTRACTION_PROMPT,
    NEWSLETTER_CONTENT_PROMPT,
    PRESS_REVIEW_PROMPT,
    STORY_EXTRACTION_PROMPT,
)
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.models import (
    Article,
    EnrichedArticle,
    NewsletterContent,
    PressReviewCategory,
)

log = structlog.get_logger()


def _dereference_schema(schema: dict[str, Any], max_depth: int = 50) -> dict[str, Any]:
    """Inline all $ref references in a JSON schema.

    Vertex AI batch prediction doesn't support $defs/$ref in schemas,
    so we need to expand all references inline.

    Args:
        schema: JSON schema with potential $defs and $ref.
        max_depth: Maximum recursion depth to prevent infinite loops.

    Raises:
        RecursionError: If max_depth is exceeded (circular reference detected).
    """
    defs = schema.pop("$defs", {})

    def resolve(obj: Any, depth: int = 0) -> Any:
        if depth > max_depth:
            raise RecursionError(
                f"Schema dereferencing exceeded max depth {max_depth}. "
                "Possible circular reference in schema."
            )
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_path = obj["$ref"]  # e.g., "#/$defs/Importance"
                ref_name = ref_path.split("/")[-1]
                if ref_name in defs:
                    return resolve(defs[ref_name].copy(), depth + 1)
                return obj
            return {k: resolve(v, depth) for k, v in obj.items()}
        if isinstance(obj, list):
            return [resolve(item, depth) for item in obj]
        return obj

    return resolve(schema)


class BatchPromptType(str, Enum):
    """Types of prompts in a batch job."""

    NEWSLETTER_CONTENT = "newsletter_content"
    REVIEW_CONTENT = "review_content"
    PRESS_REVIEW = "press_review"
    ENRICH_ARTICLE = "enrich_article"
    EXTRACT_STORIES = "extract_stories"
    EXTRACT_ENTITIES = "extract_entities"
    DETECT_FOLLOWUPS = "detect_followups"
    EXTRACT_EVENTS = "extract_events"
    EXTRACT_CAPACITY = "extract_capacity"


@dataclass
class BatchRequest:
    """A single request in a batch job."""

    prompt_type: BatchPromptType
    prompt: str
    system_prompt: str
    response_schema: dict[str, Any] | None = None
    custom_id: str | None = None

    def __post_init__(self) -> None:
        if not self.custom_id:
            self.custom_id = f"{self.prompt_type.value}_{uuid.uuid4().hex[:8]}"


@dataclass
class BatchJobResult:
    """Result of a batch job submission."""

    job_name: str
    input_uri: str
    output_uri: str
    status: str


class BatchInferenceService:
    """Service for Vertex AI batch inference."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._storage_client: storage.Client | None = None

    @property
    def storage_client(self) -> storage.Client:
        """Lazy-initialized GCS client."""
        if self._storage_client is None:
            self._storage_client = storage.Client()
        return self._storage_client

    @property
    def bucket_name(self) -> str:
        """GCS bucket for batch files."""
        if not self.settings.gcs_bucket:
            raise ValueError("GCS bucket not configured (gcs_bucket setting)")
        return self.settings.gcs_bucket

    def _build_jsonl_request(self, request: BatchRequest) -> dict[str, Any]:
        """Build a single JSONL request for Vertex AI batch inference.

        Args:
            request: BatchRequest with prompt details.

        Returns:
            Dictionary in Vertex AI batch format.
        """
        contents = [{"role": "user", "parts": [{"text": request.prompt}]}]

        generation_config: dict[str, Any] = {
            "temperature": self.settings.ai_temperature,
            "topP": self.settings.ai_top_p,
            "maxOutputTokens": self.settings.ai_max_output_tokens,
            "responseMimeType": "application/json",
        }

        if request.response_schema:
            generation_config["responseSchema"] = request.response_schema

        return {
            "request": {
                "contents": contents,
                "systemInstruction": {"parts": [{"text": request.system_prompt}]},
                "generationConfig": generation_config,
            },
            "custom_id": request.custom_id,
        }

    def build_newsletter_batch(
        self,
        articles: dict[str, EnrichedArticle],
        previous_issues: list[str],
        narrative_context: object | None = None,
        first_issue: bool = False,
    ) -> list[BatchRequest]:
        """Build batch requests for newsletter generation.

        Args:
            articles: Dictionary of enriched articles.
            previous_issues: List of previous newsletter texts.
            narrative_context: Optional NarrativeContext for story awareness.
            first_issue: If True, include introductory text.

        Returns:
            List of BatchRequest objects for the batch job.
        """
        requests: list[BatchRequest] = []

        # 1. Newsletter content prompt
        content_prompt = self._build_content_prompt(articles, previous_issues, narrative_context)
        system_prompt = NEWSLETTER_CONTENT_PROMPT
        if first_issue:
            from behind_bars_pulse.ai.prompts import FIRST_ISSUE_INTRO

            system_prompt = FIRST_ISSUE_INTRO + system_prompt

        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.NEWSLETTER_CONTENT,
                prompt=content_prompt,
                system_prompt=system_prompt,
            )
        )

        # 2. Press review prompt
        articles_json = json.dumps(
            {
                url: {"title": a.title, "link": str(a.link), "content": a.content}
                for url, a in articles.items()
            },
            indent=2,
            ensure_ascii=False,
        )

        # Dereference schema to inline $refs (Vertex AI batch doesn't support $defs)
        press_review_schema = _dereference_schema(
            TypeAdapter(list[PressReviewCategory]).json_schema()
        )
        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.PRESS_REVIEW,
                prompt=articles_json,
                system_prompt=PRESS_REVIEW_PROMPT,
                response_schema=press_review_schema,
            )
        )

        return requests

    def _build_content_prompt(
        self,
        articles: dict[str, EnrichedArticle],
        previous_issues: list[str],
        narrative_context: object | None = None,
    ) -> str:
        """Build the prompt for newsletter content generation."""
        feed_content = ""

        for article in articles.values():
            feed_content += f"Titolo: {article.title}\n"
            feed_content += f"Link: {article.link}\n"
            feed_content += f"Autore: {article.author}\n"
            feed_content += f"Fonte: {article.source}\n"
            feed_content += f"Contenuto: ```{article.content}```\n"
            feed_content += "---\n"

        # Add narrative context if available
        if narrative_context:
            feed_content += self._format_narrative_context(narrative_context)

        if previous_issues:
            feed_content += "\n\nPrevious newsletter issues:"
            for issue in previous_issues:
                feed_content += "\n\n" + issue

        return feed_content

    def _format_narrative_context(self, context: object) -> str:
        """Format narrative context for inclusion in prompts."""
        from datetime import date as date_type

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
        due = context.get_due_followups(date_type.today())
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

    def upload_batch_input(
        self,
        requests: list[BatchRequest],
        issue_date: date,
    ) -> str:
        """Upload batch input JSONL to GCS.

        Args:
            requests: List of BatchRequest objects.
            issue_date: Date for the newsletter.

        Returns:
            GCS URI of the uploaded file (gs://bucket/path).
        """
        # Build JSONL content
        lines = []
        for request in requests:
            jsonl_request = self._build_jsonl_request(request)
            lines.append(json.dumps(jsonl_request, ensure_ascii=False))

        jsonl_content = "\n".join(lines)

        # Upload to GCS
        blob_path = f"batch_jobs/{issue_date.isoformat()}/input.jsonl"
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(jsonl_content, content_type="application/jsonl")

        gcs_uri = f"gs://{self.bucket_name}/{blob_path}"
        log.info(
            "batch_input_uploaded",
            uri=gcs_uri,
            request_count=len(requests),
            size_bytes=len(jsonl_content),
        )

        return gcs_uri

    def submit_batch_job(
        self,
        input_uri: str,
        issue_date: date,
        model: str | None = None,
    ) -> BatchJobResult:
        """Submit a batch job to Vertex AI.

        Args:
            input_uri: GCS URI of the input JSONL file.
            issue_date: Date for the newsletter (used for output path).
            model: Model to use (defaults to settings.gemini_model).

        Returns:
            BatchJobResult with job details.
        """
        from google import genai
        from google.genai.types import CreateBatchJobConfig

        model = model or self.settings.gemini_model

        # Prepare output URI
        output_uri = f"gs://{self.bucket_name}/batch_jobs/{issue_date.isoformat()}/output"

        # Create client (uses Application Default Credentials)
        if not self.settings.google_project_id:
            raise ValueError("google_project_id setting is required for Vertex AI Batch")

        # Use global endpoint for base Gemini models (batch supports global)
        client = genai.Client(
            vertexai=True,
            project=self.settings.google_project_id,
            location="global",
        )

        log.info(
            "submitting_batch_job",
            model=model,
            input_uri=input_uri,
            output_uri=output_uri,
        )

        job = client.batches.create(
            model=model,
            src=input_uri,
            config=CreateBatchJobConfig(dest=output_uri),
        )

        result = BatchJobResult(
            job_name=job.name or "",
            input_uri=input_uri,
            output_uri=output_uri,
            status=str(job.state),
        )

        log.info(
            "batch_job_submitted",
            job_name=result.job_name,
            status=result.status,
        )

        return result

    def get_job_status(self, job_name: str) -> dict[str, Any]:
        """Get the status of a batch job.

        Args:
            job_name: The job name returned from submit_batch_job.

        Returns:
            Dictionary with job status details.
        """
        from google import genai

        # Create client (uses Application Default Credentials)
        if not self.settings.google_project_id:
            raise ValueError("google_project_id setting is required for Vertex AI Batch")

        # Use global endpoint for base Gemini models (batch supports global)
        client = genai.Client(
            vertexai=True,
            project=self.settings.google_project_id,
            location="global",
        )
        job = client.batches.get(name=job_name)

        return {
            "name": job.name,
            "state": str(job.state),
            "create_time": str(job.create_time) if job.create_time else None,
            "update_time": str(job.update_time) if job.update_time else None,
        }

    def download_batch_results(self, output_uri: str) -> list[dict[str, Any]]:
        """Download and parse batch job results from GCS.

        Args:
            output_uri: GCS URI of the output directory.

        Returns:
            List of parsed result dictionaries.
        """
        # Parse GCS URI
        if not output_uri.startswith("gs://"):
            raise ValueError(f"Invalid GCS URI: {output_uri}")

        path = output_uri[5:]  # Remove "gs://"
        bucket_name = path.split("/")[0]
        prefix = "/".join(path.split("/")[1:])

        bucket = self.storage_client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)

        results = []
        for blob in blobs:
            if blob.name.endswith(".jsonl"):
                content = blob.download_as_text()
                for line in content.strip().split("\n"):
                    if line:
                        results.append(json.loads(line))

        log.info("batch_results_downloaded", result_count=len(results))
        return results

    def parse_batch_results(
        self, results: list[dict[str, Any]]
    ) -> tuple[NewsletterContent | None, list[PressReviewCategory] | None]:
        """Parse batch results into newsletter components.

        Args:
            results: List of result dictionaries from download_batch_results.

        Returns:
            Tuple of (NewsletterContent, press_review categories).
        """
        newsletter_content: NewsletterContent | None = None
        press_review: list[PressReviewCategory] | None = None

        for result in results:
            custom_id = result.get("custom_id", "")
            response = result.get("response", {})

            # Extract text from response
            candidates = response.get("candidates", [])
            if not candidates:
                log.warning("empty_batch_response", custom_id=custom_id)
                continue

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if not parts:
                continue

            text = parts[0].get("text", "")
            if not text:
                continue

            try:
                parsed = json.loads(text)

                if custom_id.startswith(BatchPromptType.NEWSLETTER_CONTENT.value):
                    newsletter_content = NewsletterContent(**parsed)
                    log.info("parsed_newsletter_content", title=newsletter_content.title[:50])

                elif custom_id.startswith(BatchPromptType.PRESS_REVIEW.value):
                    press_review = [PressReviewCategory(**cat) for cat in parsed]
                    log.info("parsed_press_review", category_count=len(press_review))

            except (json.JSONDecodeError, TypeError) as e:
                log.error(
                    "batch_result_parse_error",
                    custom_id=custom_id,
                    error=str(e),
                )

        return newsletter_content, press_review

    def build_collector_batch(
        self,
        articles: dict[str, Article],
        existing_stories: list[dict[str, Any]],
        existing_characters: list[dict[str, Any]],
        story_ids: list[str],
        existing_events: list[dict[str, Any]],
        existing_snapshots: list[dict[str, Any]],
    ) -> list[BatchRequest]:
        """Build batch requests for collector enrichment pipeline.

        Creates N+5 requests: 1 enrichment per article + 1 each for
        stories, entities, followups, events, capacity.

        Args:
            articles: Raw articles keyed by URL.
            existing_stories: Existing story dicts for story extraction.
            existing_characters: Existing character dicts for entity extraction.
            story_ids: Active story IDs for followup detection.
            existing_events: Recent events for dedup in event extraction.
            existing_snapshots: Recent snapshots for dedup in capacity extraction.

        Returns:
            List of BatchRequest objects for the batch job.
        """
        requests: list[BatchRequest] = []

        # Build shared articles payload (used by stories/entities/followups/events/capacity)
        articles_for_extraction = {
            url: {
                "title": a.title,
                "link": str(a.link),
                "content": a.content[:2000],
            }
            for url, a in articles.items()
        }

        # 1. One enrichment request per article
        for url, article in articles.items():
            # Use URL hash for stable custom_id
            url_hash = uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]
            requests.append(
                BatchRequest(
                    prompt_type=BatchPromptType.ENRICH_ARTICLE,
                    prompt=article.content,
                    system_prompt=EXTRACT_INFO_PROMPT,
                    custom_id=f"{BatchPromptType.ENRICH_ARTICLE.value}_{url_hash}",
                )
            )

        # 2. Story extraction
        story_prompt = json.dumps(
            {
                "articles": {
                    url: {
                        **articles_for_extraction[url],
                        "summary": "",
                        "content": a.content[:1000],
                    }
                    for url, a in articles.items()
                },
                "existing_stories": existing_stories,
            },
            indent=2,
            ensure_ascii=False,
        )
        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.EXTRACT_STORIES,
                prompt=story_prompt,
                system_prompt=STORY_EXTRACTION_PROMPT,
            )
        )

        # 3. Entity extraction
        entity_prompt = json.dumps(
            {
                "articles": {
                    url: {**articles_for_extraction[url], "content": a.content[:1500]}
                    for url, a in articles.items()
                },
                "existing_characters": existing_characters,
            },
            indent=2,
            ensure_ascii=False,
        )
        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.EXTRACT_ENTITIES,
                prompt=entity_prompt,
                system_prompt=ENTITY_EXTRACTION_PROMPT,
            )
        )

        # 4. Followup detection
        followup_prompt = json.dumps(
            {
                "articles": {
                    url: {**articles_for_extraction[url], "content": a.content[:1500]}
                    for url, a in articles.items()
                },
                "existing_story_ids": story_ids,
            },
            indent=2,
            ensure_ascii=False,
        )
        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.DETECT_FOLLOWUPS,
                prompt=followup_prompt,
                system_prompt=FOLLOWUP_DETECTION_PROMPT,
            )
        )

        # 5. Event extraction
        event_prompt = json.dumps(
            {
                "articles": {
                    url: {
                        **articles_for_extraction[url],
                        "source": "",  # Raw articles don't have source yet
                    }
                    for url, a in articles.items()
                },
                "existing_events": existing_events,
            },
            indent=2,
            ensure_ascii=False,
        )
        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.EXTRACT_EVENTS,
                prompt=event_prompt,
                system_prompt=INCIDENT_EXTRACTION_PROMPT,
            )
        )

        # 6. Capacity extraction
        capacity_prompt = json.dumps(
            {
                "articles": {
                    url: {
                        **articles_for_extraction[url],
                        "source": "",
                    }
                    for url, a in articles.items()
                },
                "existing_snapshots": existing_snapshots,
            },
            indent=2,
            ensure_ascii=False,
        )
        requests.append(
            BatchRequest(
                prompt_type=BatchPromptType.EXTRACT_CAPACITY,
                prompt=capacity_prompt,
                system_prompt=CAPACITY_EXTRACTION_PROMPT,
            )
        )

        log.info(
            "collector_batch_built",
            total_requests=len(requests),
            enrichment_requests=len(articles),
            extraction_requests=5,
        )

        return requests

    def upload_collector_artifacts(
        self,
        articles: dict[str, Article],
        collection_date: date,
    ) -> str:
        """Upload raw articles to GCS for Cloud Function to access later.

        Args:
            articles: Raw articles keyed by URL.
            collection_date: Date of collection.

        Returns:
            GCS URI of the uploaded raw articles file.
        """
        articles_data = {url: article.model_dump(mode="json") for url, article in articles.items()}
        raw_json = json.dumps(articles_data, indent=2, ensure_ascii=False)

        blob_path = f"batch_jobs/collect/{collection_date.isoformat()}/raw_articles.json"
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(raw_json, content_type="application/json")

        gcs_uri = f"gs://{self.bucket_name}/{blob_path}"
        log.info(
            "raw_articles_uploaded",
            uri=gcs_uri,
            article_count=len(articles),
        )
        return gcs_uri

    def upload_collector_batch_input(
        self,
        requests: list[BatchRequest],
        collection_date: date,
    ) -> str:
        """Upload collector batch input JSONL to GCS.

        Uses a separate path from newsletter batches:
        batch_jobs/collect/{date}/input.jsonl

        Args:
            requests: List of BatchRequest objects.
            collection_date: Date of collection.

        Returns:
            GCS URI of the uploaded file.
        """
        lines = []
        for request in requests:
            jsonl_request = self._build_jsonl_request(request)
            lines.append(json.dumps(jsonl_request, ensure_ascii=False))

        jsonl_content = "\n".join(lines)

        blob_path = f"batch_jobs/collect/{collection_date.isoformat()}/input.jsonl"
        bucket = self.storage_client.bucket(self.bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(jsonl_content, content_type="application/jsonl")

        gcs_uri = f"gs://{self.bucket_name}/{blob_path}"
        log.info(
            "collector_batch_input_uploaded",
            uri=gcs_uri,
            request_count=len(requests),
            size_bytes=len(jsonl_content),
        )
        return gcs_uri

    def submit_collector_batch_job(
        self,
        input_uri: str,
        collection_date: date,
        model: str | None = None,
    ) -> BatchJobResult:
        """Submit a collector batch job to Vertex AI.

        Args:
            input_uri: GCS URI of the input JSONL file.
            collection_date: Date of collection (used for output path).
            model: Model to use (defaults to settings.gemini_model).

        Returns:
            BatchJobResult with job details.
        """
        from google import genai
        from google.genai.types import CreateBatchJobConfig

        model = model or self.settings.gemini_model

        output_uri = (
            f"gs://{self.bucket_name}/batch_jobs/collect/{collection_date.isoformat()}/output"
        )

        if not self.settings.google_project_id:
            raise ValueError("google_project_id setting is required for Vertex AI Batch")

        client = genai.Client(
            vertexai=True,
            project=self.settings.google_project_id,
            location="global",
        )

        log.info(
            "submitting_collector_batch_job",
            model=model,
            input_uri=input_uri,
            output_uri=output_uri,
        )

        job = client.batches.create(
            model=model,
            src=input_uri,
            config=CreateBatchJobConfig(dest=output_uri),
        )

        result = BatchJobResult(
            job_name=job.name or "",
            input_uri=input_uri,
            output_uri=output_uri,
            status=str(job.state),
        )

        log.info(
            "collector_batch_job_submitted",
            job_name=result.job_name,
            status=result.status,
        )

        return result

    @staticmethod
    def _extract_text_from_result(result: dict[str, Any]) -> str | None:
        """Extract text content from a single batch result entry.

        Args:
            result: A single result dict from batch output JSONL.

        Returns:
            Extracted text string, or None if not available.
        """
        response = result.get("response", {})
        candidates = response.get("candidates", [])
        if not candidates:
            return None
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            return None
        text = parts[0].get("text", "")
        return text if text else None

    def parse_collector_results(
        self,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Parse collector batch results into structured components.

        Groups results by custom_id prefix and parses each into the
        appropriate data structure.

        Args:
            results: List of result dicts from download_batch_results.

        Returns:
            Dictionary with keys:
              - enrichments: dict mapping url_hash -> ArticleInfo dict
              - stories: dict with updated_stories/new_stories
              - entities: dict with updated_characters/new_characters
              - followups: dict with followups list
              - events: dict with events list
              - capacity: dict with snapshots list
        """
        parsed: dict[str, Any] = {
            "enrichments": {},
            "stories": {"updated_stories": [], "new_stories": []},
            "entities": {"updated_characters": [], "new_characters": []},
            "followups": {"followups": []},
            "events": {"events": []},
            "capacity": {"snapshots": []},
        }

        for result in results:
            custom_id = result.get("custom_id", "")
            text = self._extract_text_from_result(result)
            if not text:
                log.warning("empty_collector_batch_response", custom_id=custom_id)
                continue

            try:
                data = json.loads(text)

                if custom_id.startswith(BatchPromptType.ENRICH_ARTICLE.value):
                    # Extract url_hash from custom_id: "enrich_article_{hash}"
                    url_hash = custom_id[len(BatchPromptType.ENRICH_ARTICLE.value) + 1 :]
                    # data is a list with one item (EXTRACT_INFO_PROMPT returns array)
                    if isinstance(data, list) and data:
                        parsed["enrichments"][url_hash] = data[0]
                    else:
                        parsed["enrichments"][url_hash] = data
                    log.debug("parsed_enrichment", url_hash=url_hash)

                elif custom_id.startswith(BatchPromptType.EXTRACT_STORIES.value):
                    parsed["stories"] = data
                    log.info(
                        "parsed_stories",
                        updated=len(data.get("updated_stories", [])),
                        new=len(data.get("new_stories", [])),
                    )

                elif custom_id.startswith(BatchPromptType.EXTRACT_ENTITIES.value):
                    parsed["entities"] = data
                    log.info(
                        "parsed_entities",
                        updated=len(data.get("updated_characters", [])),
                        new=len(data.get("new_characters", [])),
                    )

                elif custom_id.startswith(BatchPromptType.DETECT_FOLLOWUPS.value):
                    parsed["followups"] = data
                    log.info("parsed_followups", count=len(data.get("followups", [])))

                elif custom_id.startswith(BatchPromptType.EXTRACT_EVENTS.value):
                    parsed["events"] = data
                    log.info("parsed_events", count=len(data.get("events", [])))

                elif custom_id.startswith(BatchPromptType.EXTRACT_CAPACITY.value):
                    parsed["capacity"] = data
                    log.info("parsed_capacity", count=len(data.get("snapshots", [])))

            except (json.JSONDecodeError, TypeError) as e:
                log.error(
                    "collector_batch_result_parse_error",
                    custom_id=custom_id,
                    error=str(e),
                )

        log.info(
            "collector_results_parsed",
            enrichments=len(parsed["enrichments"]),
            stories_updated=len(parsed["stories"].get("updated_stories", [])),
            stories_new=len(parsed["stories"].get("new_stories", [])),
            events=len(parsed["events"].get("events", [])),
            snapshots=len(parsed["capacity"].get("snapshots", [])),
        )

        return parsed
