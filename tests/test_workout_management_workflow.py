from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from adapters.discord.normalization import (
    DiscordComponentSnapshot,
    DiscordSlashSnapshot,
    DiscordUserSnapshot,
    component_to_event,
    slash_to_event,
)
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
        event = self._treenit_event("event-list", "user-1", "listaa")

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("Löysin 2 treeniä:", text)
        self.assertIn("1. 13.6.2026 19:00 - Evening run", text)
        self.assertIn("2. 13.6.2026 10:00 - Morning run", text)
        self.assertIn("Juoksu, 6 km, 35:00, keskisyke 132, nousu 30 m", text)
        self.assertIn("Voit viitata treeniin numerolla, päivämäärällä tai nimellä.", text)
        self.assertIn("Morning run", text)
        self.assertIn("Evening run", text)
        self.assertNotIn("workout-1", text)
        self.assertNotIn("workout-2", text)
        self.assertNotIn("Other user run", text)

    def test_treenit_listaa_uses_singular_count_for_one_workout(self) -> None:
        self._seed_single_workout()
        event = self._treenit_event("event-list", "user-1", "listaa")

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("Löysin 1 treenin:", text)
        self.assertIn("1. 13.6.2026 10:00 - Morning run", text)
        self.assertNotIn("workout-1", text)

    def test_treenit_nayta_rejects_other_users_workout(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-show", "user-1", "nayta", {"viite": "workout-3"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))
        text = _render_first(result)

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(text, "En löytänyt pyynnölle sopivaa treeniä.")

    def test_treenit_nayta_sets_shown_workout_active(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-show", "user-1", "nayta", {"viite": "2"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(active.workout_id, "workout-1")

    def test_treenit_listaa_marks_active_workout(self) -> None:
        self._seed_workouts()
        with UnitOfWork(self.connection) as repositories:
            repositories.active_workouts.set(
                user_id="user-1",
                workout_id="workout-2",
                updated_at="2026-06-13T20:00:00Z",
            )

        result = self.dispatcher.dispatch(
            self._treenit_event("event-list", "user-1", "listaa"),
            DispatchContext(UnitOfWork(self.connection)),
        )
        text = _render_first(result)

        self.assertIn("1. 13.6.2026 19:00 - Evening run *", text)
        self.assertIn("2. 13.6.2026 10:00 - Morning run", text)

    def test_treenit_aseta_aktiivinen_sets_owned_active_workout(self) -> None:
        self._seed_workouts()
        event = self._treenit_event(
            "event-active-set",
            "user-1",
            "aseta_aktiivinen",
            {"viite": "workout-2"},
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
            "aseta_aktiivinen",
            {"viite": "1"},
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(active.workout_id, "workout-2")

    def test_treenit_nayta_reports_ambiguous_reference(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-show", "user-1", "nayta", {"viite": "run"})

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
                "aseta_aktiivinen",
                {"viite": "workout-2"},
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        result = self.dispatcher.dispatch(
            self._treenit_event("event-active", "user-1", "aktiivinen"),
            DispatchContext(UnitOfWork(self.connection)),
        )
        text = _render_first(result)

        self.assertIn("Evening run", text)
        self.assertIn("Matka: 6 km", text)
        self.assertIn("Keskisyke: 132", text)
        self.assertIn("Nousu: 30 m", text)

    def test_treenit_nimea_renames_owned_workout_and_sets_active(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-rename", "user-1", "nimea", {"viite": "2", "nimi": "Sipoo Running"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(_render_first(result), "Nimesin treenin uudelleen: Sipoo Running.")
        with UnitOfWork(self.connection) as repositories:
            workout = repositories.workouts.get_for_user("user-1", "workout-1")
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(workout.title, "Sipoo Running")
        self.assertEqual(active.workout_id, "workout-1")

    def test_treenit_nimea_rejects_other_users_workout(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-rename", "user-1", "nimea", {"viite": "workout-3", "nimi": "Nope"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        with UnitOfWork(self.connection) as repositories:
            workout = repositories.workouts.get_for_user("user-2", "workout-3")
        self.assertEqual(workout.title, "Other user run")

    def test_treenit_tagaa_adds_and_removes_owned_tag(self) -> None:
        self._seed_workouts()

        add_result = self.dispatcher.dispatch(
            self._treenit_event("event-tag", "user-1", "tagaa", {"viite": "workout-1", "tagi": "Trail Run"}),
            DispatchContext(UnitOfWork(self.connection)),
        )
        remove_result = self.dispatcher.dispatch(
            self._treenit_event("event-untag", "user-1", "poista_tagi", {"viite": "workout-1", "tagi": "trail-run"}),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(_render_first(add_result), "Lisäsin tagin trail-run treenille: Morning run.")
        self.assertEqual(_render_first(remove_result), "Poistin tagin trail-run treeniltä: Morning run.")
        with UnitOfWork(self.connection) as repositories:
            tags = repositories.workouts.tags_for_workout("user-1", "workout-1")
        self.assertEqual(tags, ())

    def test_treenit_tagaa_rejects_invalid_tag(self) -> None:
        self._seed_workouts()
        event = self._treenit_event("event-tag", "user-1", "tagaa", {"viite": "workout-1", "tagi": "bad/tag"})

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(_render_first(result), "Tagin muoto ei kelpaa.")

    def test_treenit_poista_requires_confirmation_before_deleting_owned_workout(self) -> None:
        self._seed_workouts()
        start = datetime(2026, 6, 13, 21, 0, tzinfo=timezone.utc)

        pending_result = self.dispatcher.dispatch(
            self._treenit_event("event-delete", "user-1", "poista", {"viite": "workout-1"}, created_at=start),
            DispatchContext(UnitOfWork(self.connection)),
        )

        pending_text = _render_first(pending_result)
        self.assertIn("Poisto vaatii vahvistuksen.", pending_text)
        self.assertIn("Poistettava treeni: Morning run", pending_text)
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNotNone(repositories.workouts.get_for_user("user-1", "workout-1"))
            pending = repositories.pending_workout_deletes.latest_for_user("user-1")
        self.assertEqual(pending.workout_id, "workout-1")
        self.assertEqual([component.label for component in pending_result.messages[0].components], ["Poista", "Peruuta"])

        result = self.dispatcher.dispatch(
            self._component_event(
                "event-delete-confirm",
                "user-1",
                pending_result.messages[0].components[0].component_id,
                created_at=start + timedelta(seconds=30),
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(_render_first(result), "Poistin treenin: Morning run.")
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNone(repositories.workouts.get_for_user("user-1", "workout-1"))
            self.assertIsNotNone(repositories.workouts.get_for_user("user-2", "workout-3"))
            self.assertIsNone(repositories.pending_workout_deletes.latest_for_user("user-1"))

    def test_treenit_poista_rejects_confirmation_without_pending_delete(self) -> None:
        self._seed_workouts()
        result = self.dispatcher.dispatch(
            self._component_event(
                "event-delete-confirm",
                "user-1",
                "treenit:workout_delete_confirm:event-delete:pending-delete",
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertIn("vahvistus ei täsmää", _render_first(result))
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNotNone(repositories.workouts.get_for_user("user-1", "workout-1"))

    def test_treenit_poista_cancel_button_clears_pending_delete(self) -> None:
        self._seed_workouts()
        pending_result = self.dispatcher.dispatch(
            self._treenit_event("event-delete", "user-1", "poista", {"viite": "workout-1"}),
            DispatchContext(UnitOfWork(self.connection)),
        )

        result = self.dispatcher.dispatch(
            self._component_event(
                "event-delete-cancel",
                "user-1",
                pending_result.messages[0].components[1].component_id,
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(_render_first(result), "Peruin poiston.")
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNotNone(repositories.workouts.get_for_user("user-1", "workout-1"))
            self.assertIsNone(repositories.pending_workout_deletes.latest_for_user("user-1"))

    def test_treenit_poista_rejects_expired_confirmation(self) -> None:
        self._seed_workouts()
        start = datetime(2026, 6, 13, 21, 0, tzinfo=timezone.utc)
        self.dispatcher.dispatch(
            self._treenit_event("event-delete", "user-1", "poista", {"viite": "workout-1"}, created_at=start),
            DispatchContext(UnitOfWork(self.connection)),
        )
        with UnitOfWork(self.connection) as repositories:
            pending = repositories.pending_workout_deletes.latest_for_user("user-1")

        result = self.dispatcher.dispatch(
            self._component_event(
                "event-delete-confirm",
                "user-1",
                f"treenit:workout_delete_confirm:{pending.pending_id}",
                created_at=start + timedelta(seconds=61),
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertIn("vahvistus vanheni", _render_first(result))
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNotNone(repositories.workouts.get_for_user("user-1", "workout-1"))

    def test_asetukset_sykerajat_update_and_show(self) -> None:
        update = self._asetukset_event(
            "event-zones-update",
            "user-1",
            "sykerajat",
            {
                "zones": "114,133,152,171,190",
            },
        )

        update_result = self.dispatcher.dispatch(update, DispatchContext(UnitOfWork(self.connection)))
        list_result = self.dispatcher.dispatch(
            self._asetukset_event("event-zones-list", "user-1", "nayta"),
            DispatchContext(UnitOfWork(self.connection)),
        )
        text = _render_first(list_result)

        self.assertEqual(_render_first(update_result), "Päivitin sykerajat.")
        self.assertIn("Asetuksesi:", text)
        self.assertIn("- pk1: -114 bpm", text)
        self.assertIn("- pk2: 115-133 bpm", text)
        self.assertIn("- vk1: 134-152 bpm", text)
        self.assertIn("- vk2: 153-171 bpm", text)
        self.assertIn("- mk: 172-190 bpm", text)

    def test_asetukset_sykerajat_calculates_limits_from_max_heart_rate(self) -> None:
        update = self._asetukset_event(
            "event-zones-update",
            "user-1",
            "sykerajat",
            {
                "zones": "190",
            },
        )

        update_result = self.dispatcher.dispatch(update, DispatchContext(UnitOfWork(self.connection)))
        list_result = self.dispatcher.dispatch(
            self._asetukset_event("event-zones-list", "user-1", "nayta"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(_render_first(update_result), "Päivitin sykerajat.")
        text = _render_first(list_result)
        self.assertIn("- pk1: -114 bpm", text)
        self.assertIn("- pk2: 115-133 bpm", text)
        self.assertIn("- vk1: 134-152 bpm", text)
        self.assertIn("- vk2: 153-171 bpm", text)
        self.assertIn("- mk: 172-190 bpm", text)

    def test_asetukset_sykerajat_invalid_limits_return_user_error(self) -> None:
        event = self._asetukset_event(
            "event-zones-invalid",
            "user-1",
            "sykerajat",
            {"zones": "130,120"},
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(
            _render_first(result),
            "Sykerajojen muoto ei kelpaa. Anna maksimisyke tai viisi nousevaa ylärajaa, "
            "esim. 190 tai 114,133,152,171,190.",
        )

    def test_asetukset_nayta_returns_empty_settings_summary(self) -> None:
        result = self.dispatcher.dispatch(
            self._asetukset_event("event-settings", "user-1", "nayta"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(_render_first(result), "Asetuksesi:\nSykerajat: ei asetettu.")

    def _treenit_event(
        self,
        interaction_id: str,
        user_id: str,
        subcommand: str,
        options: dict[str, object] | None = None,
        *,
        created_at: datetime | None = None,
    ):
        return slash_to_event(
            DiscordSlashSnapshot(
                interaction_id=interaction_id,
                guild_id="guild-1",
                channel_id="channel-1",
                user=DiscordUserSnapshot(user_id=user_id, user_name=f"name-{user_id}"),
                command_name="treenit",
                subcommand=subcommand,
                options=options or {},
                created_at=created_at or datetime.now(timezone.utc),
            )
        )

    def _asetukset_event(
        self,
        interaction_id: str,
        user_id: str,
        subcommand: str,
        options: dict[str, object] | None = None,
    ):
        return slash_to_event(
            DiscordSlashSnapshot(
                interaction_id=interaction_id,
                guild_id="guild-1",
                channel_id="channel-1",
                user=DiscordUserSnapshot(user_id=user_id, user_name=f"name-{user_id}"),
                command_name="asetukset",
                subcommand=subcommand,
                options=options or {},
                created_at=datetime.now(timezone.utc),
            )
        )

    def _component_event(
        self,
        interaction_id: str,
        user_id: str,
        component_id: str,
        *,
        created_at: datetime | None = None,
    ):
        command_name, subcommand, pending_id = component_id.split(":", 2)
        return component_to_event(
            DiscordComponentSnapshot(
                interaction_id=interaction_id,
                guild_id="guild-1",
                channel_id="channel-1",
                user=DiscordUserSnapshot(user_id=user_id, user_name=f"name-{user_id}"),
                component_id=component_id,
                command_name=command_name,
                subcommand=subcommand,
                pending_id=pending_id,
                created_at=created_at or datetime.now(timezone.utc),
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

    def _seed_single_workout(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            repositories.workouts.add(
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
                )
            )


def _render_first(result):
    return outgoing_to_discord(result.messages[0], Translator(SupportedLanguage.FI)).text


if __name__ == "__main__":
    unittest.main()
