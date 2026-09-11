"""Structured JSONL experiment logger.

Creates one log file per run at ``data/experiments/<run_id>/experiment_log.jsonl``
and a ``summary.json`` on completion.  Writes are flushed immediately so a crash
never loses more than one event.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from .config import DATA_DIR


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".{:03d}Z".format(
        int(time.time() * 1000) % 1000
    )


def _make_run_id() -> str:
    return "run_" + time.strftime("%Y%m%d_%H%M%S")


class ExperimentLogger:
    """Append-only JSONL logger for one experiment run."""

    def __init__(self, root: Path = DATA_DIR / "experiments") -> None:
        self._root = root
        self._run_id: Optional[str] = None
        self._path: Optional[Path] = None
        self._fh = None

    @property
    def run_id(self) -> Optional[str]:
        return self._run_id

    @property
    def log_path(self) -> Optional[Path]:
        return self._path

    def start_run(self, experiment_id: str, experiment_name: str) -> str:
        """Begin a new run: create directory + file, return run_id."""
        self.finish_run()
        self._run_id = _make_run_id()
        run_dir = self._root / self._run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self._path = run_dir / "experiment_log.jsonl"
        self._fh = open(self._path, "w", encoding="utf-8")
        self.append(
            "experiment_started",
            status="RUNNING",
            experiment_id=experiment_id,
            experiment_name=experiment_name,
        )
        return self._run_id

    def append(self, event: str, **fields: Any) -> None:
        """Append one JSONL event line and flush."""
        if self._fh is None:
            return
        record: dict[str, Any] = {"timestamp": _now_iso(), "event": event}
        record.update(fields)
        line = json.dumps(record, default=str) + "\n"
        self._fh.write(line)
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def finish_run(self, **summary_fields: Any) -> None:
        """Write summary.json and close the log file."""
        status = summary_fields.pop("status", "COMPLETED")
        if self._fh is not None:
            self.append("experiment_completed", status=status, **summary_fields)
            self._fh.close()
            self._fh = None
        if self._run_id and self._path:
            summary_path = self._path.parent / "summary.json"
            summary: dict[str, Any] = {"run_id": self._run_id, "status": status}
            summary.update(summary_fields)
            summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        self._run_id = None
        self._path = None

    def close(self) -> None:
        self.finish_run()
