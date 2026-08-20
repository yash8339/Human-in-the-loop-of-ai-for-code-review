from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ReviewFinding:
    title: str
    description: str
    severity: str
    confidence: float
    source: str
    accepted: Optional[bool] = None


@dataclass
class ReviewResult:
    findings: List[ReviewFinding] = field(default_factory=list)
    summary: str = ""
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    false_positive_rate: float = 0.0
    review_time: float = 0.0
