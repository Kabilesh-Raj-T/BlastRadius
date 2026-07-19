"""Risk history storage and trend calculation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from chokepoint.report.risk import RiskReport


class RiskSnapshot(BaseModel):
    """Point-in-time risk report snapshot."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    label: str
    risk_score: int = Field(ge=0, le=100)
    finding_count: int = Field(ge=0)
    report: RiskReport


class RiskTrend(BaseModel):
    """Risk score trend across snapshots."""

    model_config = ConfigDict(frozen=True)

    snapshot_count: int = Field(ge=0)
    first_score: int | None
    latest_score: int | None
    delta: int
    direction: str


class RiskHistoryStore:
    """Persist risk snapshots as newline-delimited JSON."""

    def __init__(self, path: str | Path) -> None:
        """Create a history store.

        Args:
            path: NDJSON history file path.
        """
        self._path = Path(path)

    def append(
        self,
        report: RiskReport,
        *,
        label: str = "default",
        timestamp: datetime | None = None,
    ) -> RiskSnapshot:
        """Append a risk report snapshot."""
        snapshot = RiskSnapshot(
            timestamp=timestamp or datetime.now(tz=UTC),
            label=label,
            risk_score=report.risk_score,
            finding_count=report.finding_count,
            report=report,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(snapshot.model_dump_json())
            stream.write("\n")
        return snapshot

    def load(self) -> tuple[RiskSnapshot, ...]:
        """Load all snapshots from the history file."""
        if not self._path.exists():
            return ()
        snapshots: list[RiskSnapshot] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                snapshots.append(RiskSnapshot.model_validate_json(line))
        return tuple(snapshots)

    def trend(self) -> RiskTrend:
        """Calculate score trend for stored snapshots."""
        snapshots = self.load()
        if not snapshots:
            return RiskTrend(
                snapshot_count=0,
                first_score=None,
                latest_score=None,
                delta=0,
                direction="flat",
            )
        first_score = snapshots[0].risk_score
        latest_score = snapshots[-1].risk_score
        delta = latest_score - first_score
        if delta > 0:
            direction = "worse"
        elif delta < 0:
            direction = "better"
        else:
            direction = "flat"
        return RiskTrend(
            snapshot_count=len(snapshots),
            first_score=first_score,
            latest_score=latest_score,
            delta=delta,
            direction=direction,
        )


def load_risk_history(path: str | Path) -> tuple[RiskSnapshot, ...]:
    """Load risk history snapshots."""
    return RiskHistoryStore(path).load()


def export_risk_history_json(path: str | Path) -> str:
    """Export risk history as a JSON array."""
    snapshots = RiskHistoryStore(path).load()
    payload = [snapshot.model_dump(mode="json") for snapshot in snapshots]
    return json.dumps(payload, indent=2)
