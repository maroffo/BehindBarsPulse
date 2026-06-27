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
