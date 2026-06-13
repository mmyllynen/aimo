from __future__ import annotations

import unittest

from adapters.discord.normalization import DiscordSlashSnapshot, DiscordUserSnapshot, slash_to_event
from adapters.discord.outgoing import outgoing_to_discord
from app.dispatcher import DispatchContext, Dispatcher
from core.i18n import SupportedLanguage, Translator
from core.workflows import WorkflowStatus
from storage.repositories import WorkoutRecord
from storage.unit_of_work import UnitOfWork, open_database


class WorkoutManagementWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_treenit_listaa_returns_only_current_users_workouts(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-list", "user-1", {"toiminto": "listaa"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("Morning run", text)
        self.assertIn("Evening run", text)
        self.assertNotIn("Other user run", text)

    def test_treenit_nayta_rejects_other_users_workout(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-show", "user-1", {"toiminto": "nayta", "viite": "workout-3"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(text, "En löytänyt pyynnölle sopivaa treeniä.")

    def test_treenit_aseta_aktiivinen_sets_owned_active_workout(self) -> None:
        self._seed_workouts()
        event = self._treenit_event(
            "event-active-set",
            "user-1",
            {"toiminto": "aseta_aktiivinen", "viite": "workout-2"},
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(text, "Asetin aktiiviseksi treeniksi: Evening run.")
        with UnitOfWork(self.connection) as repositories:
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(active.workout_id, "workout-2")

    def test_treenit_aseta_aktiivinen_accepts_list_index_reference(self) -> None:
        self._seed_workouts()
        event = self._treenit_event(
            "event-active-set",
            "user-1",
            {"toiminto": "aseta_aktiivinen", "viite": "1"},
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(active.workout_id, "workout-2")

    def test_treenit_nayta_reports_ambiguous_reference(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-show", "user-1", {"toiminto": "nayta", "viite": "run"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(text, "Löysin useamman mahdollisen treenin. Tarvitsen tarkemman viitteen.")

    def test_treenit_aktiivinen_returns_active_workout_details(self) -> None:
        self._seed_workouts()
        self.dispatcher.dispatch(
            self._treenit_event(
                "event-active-set",
                "user-1",
                {"toiminto": "aseta_aktiivinen", "viite": "workout-2"},
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        result = self.dispatcher.dispatch(
            self._treenit_event("event-active", "user-1", {"toiminto": "aktiivinen"}),
            DispatchContext(UnitOfWork(self.connection)),
        )
        text = _render_first(result)

        self.assertIn("Evening run", text)
        self.assertIn("Matka: 6 km", text)

    def test_treenit_poista_deletes_only_owned_workout(self) -> None:
        self._seed_workouts()
        result = self.dispatcher.dispatch(
            self._treenit_event("event-delete", "user-1", {"toiminto": "poista", "viite": "workout-1"}),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(_render_first(result), "Poistin treenin: Morning run.")
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNone(repositories.workouts.get_for_user("user-1", "workout-1"))
            self.assertIsNotNone(repositories.workouts.get_for_user("user-2", "workout-3"))

    def test_treenit_sykerajat_update_and_list(self) -> None:
        update = self._treenit_event(
            "event-zones-update",
            "user-1",
            {
                "toiminto": "aseta_sykerajat",
                "zones": [
                    {"zone_key": "z1", "label": "Kevyt", "upper_bpm": 130, "sort_order": 1},
                    {"zone_key": "z2", "label": "Reipas", "lower_bpm": 131, "upper_bpm": 150, "sort_order": 2},
                ],
            },
        )

        update_result = self.dispatcher.dispatch(update, DispatchContext(UnitOfWork(self.connection)))
        list_result = self.dispatcher.dispatch(
            self._treenit_event("event-zones-list", "user-1", {"toiminto": "sykerajat"}),
            DispatchContext(UnitOfWork(self.connection)),
        )
        text = _render_first(list_result)

        self.assertEqual(_render_first(update_result), "Päivitin sykerajat.")
        self.assertIn("Kevyt", text)
        self.assertIn("Reipas", text)

    def _treenit_event(self, interaction_id: str, user_id: str, options: dict[str, object]):
        return slash_to_event(
            DiscordSlashSnapshot(
                interaction_id=interaction_id,
                guild_id="guild-1",
                channel_id="channel-1",
                user=DiscordUserSnapshot(user_id=user_id, user_name=f"name-{user_id}"),
                command_name="treenit",
                options=options,
            )
        )

    def _seed_workouts(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            repositories.users.touch(user_id="user-2", seen_at="2026-06-13T09:00:00Z")
            for workout in (
                WorkoutRecord(
                    workout_id="workout-1",
                    owner_user_id="user-1",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Morning run",
                    kind="run",
                    primary_kind="run",
                    start_time_utc="2026-06-13T07:00:00Z",
                    start_time_local="2026-06-13T10:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=5.0,
                    duration_s=1800,
                    pace_s_per_km=360,
                    ascent_m=20,
                    avg_hr_bpm=130,
                    max_hr_bpm=150,
                    point_count=0,
                    created_at="2026-06-13T10:30:00Z",
                ),
                WorkoutRecord(
                    workout_id="workout-2",
                    owner_user_id="user-1",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Evening run",
                    kind="run",
                    primary_kind="run",
                    start_time_utc="2026-06-13T16:00:00Z",
                    start_time_local="2026-06-13T19:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=6.0,
                    duration_s=2100,
                    pace_s_per_km=350,
                    ascent_m=30,
                    avg_hr_bpm=132,
                    max_hr_bpm=152,
                    point_count=0,
                    created_at="2026-06-13T19:40:00Z",
                ),
                WorkoutRecord(
                    workout_id="workout-3",
                    owner_user_id="user-2",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Other user run",
                    kind="run",
                    primary_kind="run",
                    start_time_utc="2026-06-13T17:00:00Z",
                    start_time_local="2026-06-13T20:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=4.0,
                    duration_s=1500,
                    pace_s_per_km=375,
                    ascent_m=15,
                    avg_hr_bpm=125,
                    max_hr_bpm=145,
                    point_count=0,
                    created_at="2026-06-13T20:30:00Z",
                ),
            ):
                repositories.workouts.add(workout)


def _render_first(result):
    return outgoing_to_discord(result.messages[0], Translator(SupportedLanguage.FI)).text


if __name__ == "__main__":
    unittest.main()
