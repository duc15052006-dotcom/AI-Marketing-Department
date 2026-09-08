"""RED-first contract for durable Mission authority persistence.

Phase 11.2 requires Mission lifetime to survive process restart independently of
one RuntimeContext or chat turn.  This regression deliberately exercises only
one infrastructure invariant: a MissionStore must durably preserve the
canonical MissionRecord and enforce its business/project read authority across
reopen.  Scheduler, wake, retry, and Brain reasoning are outside this slice.
"""

from __future__ import annotations

import importlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any, Tuple, Type

from runtime.mission import MissionRecord, MissionStatus


class TestRuntimeMissionStoreDurabilityV1(unittest.TestCase):
    def _store_api(self) -> Tuple[Type[Any], Type[BaseException]]:
        """Resolve the production boundary without turning absence into ImportError noise."""
        spec = importlib.util.find_spec("runtime.mission_store")
        self.assertIsNotNone(
            spec,
            "MISSION_STORE_DURABILITY_BOUNDARY_MISSING: runtime.mission_store does not exist",
        )
        module = importlib.import_module("runtime.mission_store")
        store_type = getattr(module, "MissionStore", None)
        conflict_type = getattr(module, "MissionStoreAuthorityError", None)
        self.assertIsNotNone(store_type, "MISSION_STORE_CLASS_MISSING")
        self.assertIsNotNone(conflict_type, "MISSION_STORE_AUTHORITY_ERROR_MISSING")
        return store_type, conflict_type

    @staticmethod
    def _mission(
        *,
        mission_id: str = "MISSION-DURABLE-A",
        business_id: str = "BIZ-A",
        project_id: str = "PROJ-A",
    ) -> MissionRecord:
        return MissionRecord(
            mission_id=mission_id,
            objective="Durable MissionStore authority regression",
            business_id=business_id,
            project_id=project_id,
            user_id="USER-A",
        )

    def test_mission_store_boundary_exists_and_is_explicitly_durable(self) -> None:
        MissionStore, _ = self._store_api()
        with tempfile.TemporaryDirectory() as tmp:
            store = MissionStore(database_path=str(Path(tmp) / "missions.sqlite3"))
            try:
                self.assertTrue(store.durable)
            finally:
                store.close()

    def test_mission_survives_fresh_store_reopen_with_authority_intact(self) -> None:
        MissionStore, _ = self._store_api()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "missions.sqlite3")
            mission = self._mission()

            first = MissionStore(database_path=db_path)
            first.save_mission(mission)
            first.close()

            reopened = MissionStore(database_path=db_path)
            try:
                loaded = reopened.get_mission(
                    mission.mission_id,
                    business_id=mission.business_id,
                    project_id=mission.project_id,
                )
                self.assertIsNotNone(loaded)
                self.assertEqual(loaded.model_dump(), mission.model_dump())
                self.assertIsInstance(loaded.status, MissionStatus)
            finally:
                reopened.close()

    def test_foreign_business_cannot_read_mission_by_id(self) -> None:
        MissionStore, _ = self._store_api()
        with tempfile.TemporaryDirectory() as tmp:
            store = MissionStore(database_path=str(Path(tmp) / "missions.sqlite3"))
            try:
                mission = self._mission()
                store.save_mission(mission)
                self.assertIsNone(
                    store.get_mission(
                        mission.mission_id,
                        business_id="BIZ-FOREIGN",
                        project_id=mission.project_id,
                    )
                )
            finally:
                store.close()

    def test_foreign_project_cannot_read_mission_by_id(self) -> None:
        MissionStore, _ = self._store_api()
        with tempfile.TemporaryDirectory() as tmp:
            store = MissionStore(database_path=str(Path(tmp) / "missions.sqlite3"))
            try:
                mission = self._mission()
                store.save_mission(mission)
                self.assertIsNone(
                    store.get_mission(
                        mission.mission_id,
                        business_id=mission.business_id,
                        project_id="PROJ-FOREIGN",
                    )
                )
            finally:
                store.close()

    def test_same_mission_id_cannot_be_rebound_to_foreign_scope(self) -> None:
        MissionStore, MissionStoreAuthorityError = self._store_api()
        with tempfile.TemporaryDirectory() as tmp:
            store = MissionStore(database_path=str(Path(tmp) / "missions.sqlite3"))
            try:
                store.save_mission(self._mission())
                foreign = self._mission(business_id="BIZ-FOREIGN", project_id="PROJ-FOREIGN")
                with self.assertRaises(MissionStoreAuthorityError):
                    store.save_mission(foreign)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
