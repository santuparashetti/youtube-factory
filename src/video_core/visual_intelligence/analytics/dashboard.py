"""Dashboard API — provider-agnostic dashboard builder."""

from __future__ import annotations

from video_core.visual_intelligence.analytics.collector import AnalyticsCollector
from video_core.visual_intelligence.analytics.models import DashboardModel


def build_dashboard(collector: AnalyticsCollector) -> DashboardModel:
    return collector.build_dashboard()
