# ABOUTME: Analytical services for prison data correlation and anomaly detection.
# ABOUTME: Calculates Pearson correlation coefficients and rolling Z-score anomalies.

import math
import structlog
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent

log = structlog.get_logger()


class AnalyticsService:
    """Service for running advanced statistics on prison incidents and capacity."""

    async def calculate_facility_anomalies(
        self,
        session: AsyncSession,
        lookback_days: int = 180,
        active_days: int = 30,
        z_threshold: float = 1.5,
        min_active_incidents: int = 2,
    ) -> list[dict[str, Any]]:
        """Identify facilities with an anomalous spike in incidents.

        Uses a rolling Z-score approach: compares incident rates in the active period
        (e.g., last 30 days) with weekly baseline rates over the preceding period
        (e.g., previous 150 days).

        Args:
            session: Active AsyncSession.
            lookback_days: Total days of history to analyze (default 180).
            active_days: The current period under observation (default 30).
            z_threshold: Z-score threshold to classify as an anomaly (default 1.5).
            min_active_incidents: Minimum incidents in active period to trigger alert (default 2).

        Returns:
            List of dictionaries for anomalous facilities with statistics and alert levels.
        """
        log.info("calculating_facility_anomalies", lookback_days=lookback_days, active_days=active_days)
        
        today_date = date.today()
        active_cutoff = today_date - timedelta(days=active_days)
        baseline_cutoff = today_date - timedelta(days=lookback_days)

        # 1. Query events in the entire lookback window
        result = await session.execute(
            select(PrisonEvent)
            .where(PrisonEvent.event_date >= baseline_cutoff)
            .where(PrisonEvent.facility.isnot(None))
        )
        events = result.scalars().all()

        if not events:
            log.info("no_events_found_for_anomaly_calculation")
            return []

        # 2. Group events by facility and count them in active/baseline periods
        # We'll divide the baseline period into weekly bins (7-day blocks) to calculate baseline std dev
        facility_active_counts = defaultdict(int)
        facility_baseline_weekly_bins = defaultdict(lambda: defaultdict(int))
        facility_regions = {}

        for e in events:
            facility = e.facility
            if not facility:
                continue
            
            facility_regions[facility] = e.region or "Sconosciuta"
            event_date = e.event_date
            if not event_date:
                continue

            count = e.count if e.count is not None else 1

            if event_date >= active_cutoff:
                # Active period (last 30 days)
                facility_active_counts[facility] += count
            else:
                # Baseline period (previous 150 days)
                # Compute week index relative to baseline cutoff
                days_since_cutoff = (event_date - baseline_cutoff).days
                week_index = days_since_cutoff // 7
                facility_baseline_weekly_bins[facility][week_index] += count

        # 3. Compute statistics for each facility
        anomalies = []
        baseline_weeks_count = (lookback_days - active_days) / 7.0

        for facility, active_count in facility_active_counts.items():
            # Only analyze if active count meets minimum threshold
            if active_count < min_active_incidents:
                continue

            bins = facility_baseline_weekly_bins[facility]
            
            # Fill in 0s for weeks where no events occurred
            weekly_counts = []
            for w in range(int(baseline_weeks_count)):
                weekly_counts.append(bins.get(w, 0))

            # Compute mean and standard deviation of baseline weekly counts
            n = len(weekly_counts)
            if n < 2:
                # Not enough baseline data to compute variance
                continue

            baseline_mean = sum(weekly_counts) / n
            baseline_variance = sum((x - baseline_mean) ** 2 for x in weekly_counts) / (n - 1)
            baseline_stddev = math.sqrt(baseline_variance)

            # Compute active period equivalent weekly rate
            active_weekly_rate = active_count / (active_days / 7.0)

            # Calculate Z-score
            if baseline_stddev > 0:
                z_score = (active_weekly_rate - baseline_mean) / baseline_stddev
            else:
                # If baseline std dev is 0, it means the count was perfectly flat.
                # If active rate is higher than that flat count, it is an anomaly
                if active_weekly_rate > baseline_mean:
                    z_score = 3.0  # Assign a standard high score
                else:
                    z_score = 0.0

            is_anomaly = z_score >= z_threshold

            # Calculate average monthly counts for display
            active_monthly_rate = active_count * (30.0 / active_days)
            baseline_monthly_rate = (sum(weekly_counts) / baseline_weeks_count) * (30.0 / 7.0)

            # Assign an severity level based on Z-score
            severity = "Bassa"
            if z_score >= 3.0:
                severity = "Critica"
            elif z_score >= 2.0:
                severity = "Alta"
            elif z_score >= 1.5:
                severity = "Media"

            anomalies.append({
                "facility": facility,
                "region": facility_regions[facility],
                "active_count": active_count,
                "active_monthly_rate": round(active_monthly_rate, 1),
                "baseline_monthly_rate": round(baseline_monthly_rate, 1),
                "z_score": round(z_score, 2),
                "severity": severity,
                "is_anomaly": is_anomaly,
            })

        # Sort anomalies by z-score descending (most critical first)
        anomalies.sort(key=lambda x: x["z_score"], reverse=True)
        return anomalies

    def calculate_facility_anomalies_sync(
        self,
        lookback_days: int = 180,
        active_days: int = 30,
        z_threshold: float = 1.5,
        min_active_incidents: int = 2,
    ) -> list[dict[str, Any]]:
        """Synchronously identify facilities with an anomalous spike in incidents.

        Perfect for synchronous pipelines like the daily BulletinGenerator.
        """
        log.info("calculating_facility_anomalies_sync", lookback_days=lookback_days, active_days=active_days)
        
        from behind_bars_pulse.config import get_settings
        settings = get_settings()
        if not settings.database_url:
            log.warning("no_database_url_configured_for_sync_anomalies")
            return []

        today_date = date.today()
        active_cutoff = today_date - timedelta(days=active_days)
        baseline_cutoff = today_date - timedelta(days=lookback_days)

        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from behind_bars_pulse.config import make_sync_url

            sync_url = make_sync_url(settings.database_url)
            engine = create_engine(sync_url)

            with Session(engine) as session:
                result = session.execute(
                    select(PrisonEvent)
                    .where(PrisonEvent.event_date >= baseline_cutoff)
                    .where(PrisonEvent.facility.isnot(None))
                )
                events = result.scalars().all()

            if not events:
                return []

            facility_active_counts = defaultdict(int)
            facility_baseline_weekly_bins = defaultdict(lambda: defaultdict(int))
            facility_regions = {}

            for e in events:
                facility = e.facility
                if not facility:
                    continue
                
                facility_regions[facility] = e.region or "Sconosciuta"
                event_date = e.event_date
                if not event_date:
                    continue

                count = e.count if e.count is not None else 1

                if event_date >= active_cutoff:
                    facility_active_counts[facility] += count
                else:
                    days_since_cutoff = (event_date - baseline_cutoff).days
                    week_index = days_since_cutoff // 7
                    facility_baseline_weekly_bins[facility][week_index] += count

            anomalies = []
            baseline_weeks_count = (lookback_days - active_days) / 7.0

            for facility, active_count in facility_active_counts.items():
                if active_count < min_active_incidents:
                    continue

                bins = facility_baseline_weekly_bins[facility]
                weekly_counts = []
                for w in range(int(baseline_weeks_count)):
                    weekly_counts.append(bins.get(w, 0))

                n = len(weekly_counts)
                if n < 2:
                    continue

                baseline_mean = sum(weekly_counts) / n
                baseline_variance = sum((x - baseline_mean) ** 2 for x in weekly_counts) / (n - 1)
                baseline_stddev = math.sqrt(baseline_variance)

                active_weekly_rate = active_count / (active_days / 7.0)

                if baseline_stddev > 0:
                    z_score = (active_weekly_rate - baseline_mean) / baseline_stddev
                else:
                    if active_weekly_rate > baseline_mean:
                        z_score = 3.0
                    else:
                        z_score = 0.0

                is_anomaly = z_score >= z_threshold

                active_monthly_rate = active_count * (30.0 / active_days)
                baseline_monthly_rate = (sum(weekly_counts) / baseline_weeks_count) * (30.0 / 7.0)

                severity = "Bassa"
                if z_score >= 3.0:
                    severity = "Critica"
                elif z_score >= 2.0:
                    severity = "Alta"
                elif z_score >= 1.5:
                    severity = "Media"

                anomalies.append({
                    "facility": facility,
                    "region": facility_regions[facility],
                    "active_count": active_count,
                    "active_monthly_rate": round(active_monthly_rate, 1),
                    "baseline_monthly_rate": round(baseline_monthly_rate, 1),
                    "z_score": round(z_score, 2),
                    "severity": severity,
                    "is_anomaly": is_anomaly,
                })

            anomalies.sort(key=lambda x: x["z_score"], reverse=True)
            return anomalies

        except Exception as e:
            log.exception("calculating_facility_anomalies_sync_failed", error=str(e))
            return []

    async def calculate_occupancy_incident_correlation(
        self,
        session: AsyncSession,
        lookback_days: int = 180,
    ) -> dict[str, Any]:
        """Calculate the Pearson correlation coefficient between occupancy rates and incidents.

        For each facility, aggregates the average occupancy rate and total incidents over the
        lookback period, then computes the Pearson correlation coefficient over all facilities.

        Args:
            session: Active AsyncSession.
            lookback_days: Days of history to analyze (default 180).

        Returns:
            Dictionary containing correlation coefficient, scatter plot data points,
            and an analytical text description.
        """
        log.info("calculating_occupancy_incident_correlation", lookback_days=lookback_days)
        
        cutoff_date = date.today() - timedelta(days=lookback_days)

        # 1. Fetch capacity snapshots
        snapshots_result = await session.execute(
            select(FacilitySnapshot)
            .where(FacilitySnapshot.snapshot_date >= cutoff_date)
            .where(FacilitySnapshot.occupancy_rate.isnot(None))
        )
        snapshots = snapshots_result.scalars().all()

        # 2. Fetch prison events
        events_result = await session.execute(
            select(PrisonEvent)
            .where(PrisonEvent.event_date >= cutoff_date)
            .where(PrisonEvent.facility.isnot(None))
        )
        events = events_result.scalars().all()

        if not snapshots:
            log.warning("no_capacity_snapshots_found_for_correlation")
            return {
                "correlation_coefficient": 0.0,
                "data_points": [],
                "message": "Nessun dato di capienza disponibile per il calcolo.",
            }

        # 3. Calculate average occupancy rate per facility
        facility_occupancy_sums = defaultdict(float)
        facility_occupancy_counts = defaultdict(int)
        facility_regions = {}

        for s in snapshots:
            facility = s.facility
            if not facility:
                continue
            facility_occupancy_sums[facility] += s.occupancy_rate
            facility_occupancy_counts[facility] += 1
            if s.region:
                facility_regions[facility] = s.region

        facility_avg_occupancy = {}
        for facility, total_sum in facility_occupancy_sums.items():
            count = facility_occupancy_counts[facility]
            facility_avg_occupancy[facility] = total_sum / count

        # 4. Calculate total incidents per facility
        facility_incident_counts = defaultdict(int)
        for e in events:
            facility = e.facility
            if not facility:
                continue
            count = e.count if e.count is not None else 1
            facility_incident_counts[facility] += count
            if e.region and facility not in facility_regions:
                facility_regions[facility] = e.region

        # 5. Build data points list
        # We align facilities that have occupancy data (assigning 0 events if none found)
        data_points = []
        for facility, avg_occupancy in facility_avg_occupancy.items():
            incident_count = facility_incident_counts.get(facility, 0)
            data_points.append({
                "facility": facility,
                "region": facility_regions.get(facility, "Sconosciuta"),
                "occupancy_rate": round(avg_occupancy, 1),
                "incident_count": incident_count,
            })

        if len(data_points) < 3:
            return {
                "correlation_coefficient": 0.0,
                "data_points": data_points,
                "message": "Dati insufficienti per calcolare una correlazione statistica significativa (minimo 3 istituti richiesti).",
            }

        # 6. Calculate Pearson Correlation Coefficient
        x_values = [p["occupancy_rate"] for p in data_points]
        y_values = [p["incident_count"] for p in data_points]

        n = len(data_points)
        mean_x = sum(x_values) / n
        mean_y = sum(y_values) / n

        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
        den_x = sum((x - mean_x) ** 2 for x in x_values)
        den_y = sum((y - mean_y) ** 2 for y in y_values)

        if den_x > 0 and den_y > 0:
            r = num / math.sqrt(den_x * den_y)
        else:
            r = 0.0

        # 7. Generate a descriptive message in Italian
        r_abs = abs(r)
        strength = "nessuna"
        direction = "positiva" if r >= 0 else "negativa"

        if r_abs >= 0.7:
            strength = "forte"
        elif r_abs >= 0.4:
            strength = "moderata"
        elif r_abs >= 0.2:
            strength = "debole"

        if strength == "nessuna":
            message = (
                f"Non è stata rilevata alcuna correlazione lineare significativa (r = {r:.2f}) "
                "tra il sovraffollamento degli istituti e la frequenza degli incidenti nei dati attuali."
            )
        else:
            message = (
                f"I dati mostrano una **{strength} correlazione {direction}** (r = {r:.2f}) "
                f"tra il tasso di occupazione medio e il numero di eventi critici registrati negli istituti. "
                "Questo indica statistica alla mano che gli istituti con maggior affollamento tendono ad avere un numero più elevato di incidenti."
            )

        return {
            "correlation_coefficient": round(r, 3),
            "data_points": sorted(data_points, key=lambda x: x["occupancy_rate"], reverse=True),
            "message": message,
        }

    async def calculate_semantic_trends(
        self,
        session: AsyncSession,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Calculate monthly semantic centroids and consecutive drift (cosine distance).

        Uses local JSON file-based caching (data/semantic_trends.json) to store
        calculated monthly keywords and average embedding centroids, dramatically reducing
        Gemini API costs.

        Args:
            session: Active AsyncSession.
            force_refresh: If True, recalculates all values bypassing cache.

        Returns:
            List of monthly trend dictionaries with keywords, similarity, and drift.
        """
        import json
        import os
        from datetime import datetime
        from pathlib import Path
        from behind_bars_pulse.config import get_settings
        from behind_bars_pulse.db.models import Article
        from behind_bars_pulse.ai.service import AIService

        # Set up cache path inside data/
        settings = get_settings()
        cache_dir = Path(settings.templates_dir).parent / "data"
        cache_path = cache_dir / "semantic_trends.json"

        # Check cache validity (re-use if younger than 24 hours and force_refresh is false)
        if not force_refresh and cache_path.exists():
            try:
                # We check age of file
                mtime = os.path.getmtime(cache_path)
                age = datetime.now().timestamp() - mtime
                if age < 86400:  # 24 hours
                    with open(cache_path, "r", encoding="utf-8") as f:
                        cached_data = json.load(f)
                        log.info("loaded_semantic_trends_from_cache", path=str(cache_path))
                        # Strip out raw centroid lists for API payload to save bandwidth
                        return [{k: v for k, v in m.items() if k != "centroid"} for m in cached_data]
            except Exception as e:
                log.warning("failed_to_load_semantic_trends_cache", error=str(e))

        log.info("recalculating_semantic_trends")

        # 1. Load old cache to preserve historical months' keywords (avoids redundant Gemini calls)
        old_cache = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    for m in json.load(f):
                        if "month" in m and "keywords" in m:
                            old_cache[m["month"]] = m["keywords"]
            except Exception:
                pass

        # 2. Query all embedded articles from database
        result = await session.execute(
            select(Article.published_date, Article.title, Article.embedding)
            .where(Article.embedding.isnot(None))
        )
        articles_data = result.all()

        if not articles_data:
            log.warning("no_embedded_articles_found_for_trends")
            return []

        # 3. Group by month in Python: month_key = "YYYY-MM"
        monthly_embeddings = defaultdict(list)
        monthly_titles = defaultdict(list)

        for pub_date, title, embedding in articles_data:
            if not pub_date or not embedding:
                continue
            month_key = f"{pub_date.year}-{pub_date.month:02d}"
            monthly_embeddings[month_key].append(embedding)
            monthly_titles[month_key].append(title)

        # 4. Sort months chronologically
        sorted_months = sorted(monthly_embeddings.keys())
        if len(sorted_months) == 0:
            return []

        # 5. Compute centroids for each month
        monthly_centroids = {}
        for m in sorted_months:
            embeddings_list = monthly_embeddings[m]
            n = len(embeddings_list)
            dim = len(embeddings_list[0])
            
            # Average vector dimensions
            centroid = [0.0] * dim
            for emb in embeddings_list:
                for i in range(dim):
                    centroid[i] += emb[i]
            
            centroid = [val / n for val in centroid]
            monthly_centroids[m] = centroid

        # 6. Compute drift and generate keywords
        ai_svc = AIService(settings)
        trend_records = []

        italian_month_names = {
            "01": "Gennaio", "02": "Febbraio", "03": "Marzo", "04": "Aprile",
            "05": "Maggio", "06": "Giugno", "07": "Luglio", "08": "Agosto",
            "09": "Settembre", "10": "Ottobre", "11": "Novembre", "12": "Dicembre"
        }

        for idx, m in enumerate(sorted_months):
            centroid = monthly_centroids[m]
            
            # Similarity and drift relative to the previous month
            if idx == 0:
                similarity = 1.0
                drift = 0.0
            else:
                prev_m = sorted_months[idx - 1]
                prev_centroid = monthly_centroids[prev_m]
                similarity = self._cosine_similarity(centroid, prev_centroid)
                drift = 1.0 - similarity

            # Resolve monthly human-readable label
            year_part, month_part = m.split("-")
            month_name = italian_month_names.get(month_part, month_part)
            label = f"{month_name} {year_part}"

            # Reuse cached keywords if available, otherwise query Gemini
            if m in old_cache and not force_refresh:
                keywords = old_cache[m]
            else:
                titles = monthly_titles[m]
                keywords = ai_svc.generate_monthly_themes(month_label=label, titles=titles)

            trend_records.append({
                "month": m,
                "label": label,
                "article_count": len(monthly_titles[m]),
                "keywords": keywords,
                "similarity": round(similarity, 4),
                "drift": round(drift, 4),
                "centroid": centroid,  # Saved to cache but stripped in response
            })

        # Save complete computed records with centroids to local cache file
        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(trend_records, f, indent=2, ensure_ascii=False)
            log.info("saved_semantic_trends_to_cache", path=str(cache_path))
        except Exception as e:
            log.error("failed_to_write_semantic_trends_cache", error=str(e))

        # Return stripped records to save bandwidth
        return [{k: v for k, v in r.items() if k != "centroid"} for r in trend_records]

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        """Calculate cosine similarity between two numeric vectors."""
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 > 0 and norm2 > 0:
            return dot / (norm1 * norm2)
        return 0.0
