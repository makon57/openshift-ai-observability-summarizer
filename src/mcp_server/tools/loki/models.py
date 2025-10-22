"""Data models for Loki query responses."""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class LogQueryResponse:
    """Response structure for log queries."""
    success: bool
    query: str
    logs: Optional[List[Dict[str, Any]]] = None
    total: Optional[int] = None
    time_range: Optional[str] = None
    api_endpoint: Optional[str] = None
    result_type: Optional[str] = None  # "streams" or "matrix"
    error: Optional[str] = None
    loki_url: Optional[str] = None
    error_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LogDetailsResponse:
    """Response structure for log details and metadata."""
    success: bool
    data: Optional[Any] = None  # Can be labels, values, or other metadata
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class LogAnalysisResult:
    """Result structure for log analysis operations."""
    success: bool
    analysis_type: str  # "error_analysis", "performance_analysis", etc.
    summary: Optional[str] = None
    insights: Optional[List[str]] = None
    recommendations: Optional[List[str]] = None
    log_entries: Optional[List[Dict[str, Any]]] = None
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}
