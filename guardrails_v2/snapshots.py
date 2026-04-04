"""
Snapshot Manager — file-level rollback using pre-change snapshots.

Before any agent writes to a file, create a snapshot. If verification
fails or the user requests rollback, restore from the snapshot.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

import interro_claw.config as _cfg

logger = logging.getLogger(__name__)

_SNAPSHOTS_DIR = os.path.join(_cfg.USER_APP_DIR, "snapshots")


@dataclass
class Snapshot:
    id: str
    session_id: str
    file_path: str
    snapshot_path: str
    agent_name: str
    timestamp: float
    restored: bool = False


class SnapshotManager:
    """Manages file snapshots for rollback capability."""

    def __init__(self, base_dir: str | None = None) -> None:
        self._base = base_dir or _SNAPSHOTS_DIR
        os.makedirs(self._base, exist_ok=True)
        self._snapshots: list[Snapshot] = []
        self._manifest_path = os.path.join(self._base, "manifest.json")
        self._load_manifest()

    def _load_manifest(self) -> None:
        if os.path.exists(self._manifest_path):
            try:
                with open(self._manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._snapshots = [
                    Snapshot(**s) for s in data.get("snapshots", [])
                ]
            except Exception:
                self._snapshots = []

    def _save_manifest(self) -> None:
        data = {
            "snapshots": [
                {
                    "id": s.id, "session_id": s.session_id,
                    "file_path": s.file_path, "snapshot_path": s.snapshot_path,
                    "agent_name": s.agent_name, "timestamp": s.timestamp,
                    "restored": s.restored,
                }
                for s in self._snapshots
            ]
        }
        with open(self._manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def take_snapshot(
        self,
        file_path: str,
        session_id: str,
        agent_name: str,
    ) -> Snapshot | None:
        """Snapshot a file before it's modified. Returns None if file doesn't exist."""
        if not os.path.exists(file_path):
            return None

        snap_id = f"{session_id}_{int(time.time()*1000)}"
        snap_dir = os.path.join(self._base, session_id)
        os.makedirs(snap_dir, exist_ok=True)

        basename = os.path.basename(file_path)
        snap_path = os.path.join(snap_dir, f"{snap_id}_{basename}")

        shutil.copy2(file_path, snap_path)

        snapshot = Snapshot(
            id=snap_id,
            session_id=session_id,
            file_path=file_path,
            snapshot_path=snap_path,
            agent_name=agent_name,
            timestamp=time.time(),
        )
        self._snapshots.append(snapshot)
        self._save_manifest()
        logger.info("Snapshot taken: %s -> %s", file_path, snap_path)
        return snapshot

    def rollback(self, snapshot_id: str) -> bool:
        """Restore a file from a snapshot."""
        for snap in self._snapshots:
            if snap.id == snapshot_id and not snap.restored:
                if os.path.exists(snap.snapshot_path):
                    shutil.copy2(snap.snapshot_path, snap.file_path)
                    snap.restored = True
                    self._save_manifest()
                    logger.info("Rolled back: %s from snapshot %s", snap.file_path, snapshot_id)
                    return True
        return False

    def rollback_session(self, session_id: str) -> int:
        """Rollback all snapshots from a session (most recent first)."""
        session_snaps = [
            s for s in reversed(self._snapshots)
            if s.session_id == session_id and not s.restored
        ]
        count = 0
        for snap in session_snaps:
            if self.rollback(snap.id):
                count += 1
        return count

    def get_snapshots(self, session_id: str | None = None) -> list[Snapshot]:
        if session_id:
            return [s for s in self._snapshots if s.session_id == session_id]
        return list(self._snapshots)

    def cleanup(self, older_than_hours: int = 24) -> int:
        """Remove old snapshots to save disk space."""
        cutoff = time.time() - (older_than_hours * 3600)
        kept: list[Snapshot] = []
        removed = 0
        for snap in self._snapshots:
            if snap.timestamp < cutoff:
                if os.path.exists(snap.snapshot_path):
                    os.remove(snap.snapshot_path)
                removed += 1
            else:
                kept.append(snap)
        self._snapshots = kept
        self._save_manifest()
        return removed


# -- Singleton ---------------------------------------------------------------

_instance: SnapshotManager | None = None


def get_snapshot_manager() -> SnapshotManager:
    global _instance
    if _instance is None:
        _instance = SnapshotManager()
    return _instance
