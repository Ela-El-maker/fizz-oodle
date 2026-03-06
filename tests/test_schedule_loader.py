from __future__ import annotations

from pathlib import Path

from celery.schedules import crontab

from celery_app import _load_beat_schedule_from_config, _parse_utc_cron


def test_parse_utc_cron_returns_crontab() -> None:
    schedule = _parse_utc_cron("*/15 * * * *")
    assert isinstance(schedule, crontab)


def test_load_schedule_from_yaml_filters_unknown_tasks(tmp_path: Path) -> None:
    schedule_file = tmp_path / "schedules.yml"
    schedule_file.write_text(
        """
version: 1
timezone: Africa/Nairobi
schedules:
  - schedule_key: good
    task_name: agent_system.ping
    utc_cron: "*/15 * * * *"
    task_kwargs:
      heartbeat: true
  - schedule_key: unknown_task
    task_name: agent_unknown.run
    utc_cron: "0 * * * *"
  - schedule_key: invalid_cron
    task_name: agent_system.ping
    utc_cron: "0 * *"
""".strip(),
        encoding="utf-8",
    )

    schedule = _load_beat_schedule_from_config(str(schedule_file))
    assert list(schedule.keys()) == ["good"]
    assert schedule["good"]["task"] == "agent_system.ping"
    assert schedule["good"]["kwargs"] == {"heartbeat": True}


def test_missing_schedule_file_returns_empty() -> None:
    schedule = _load_beat_schedule_from_config("does/not/exist.yml")
    assert schedule == {}
