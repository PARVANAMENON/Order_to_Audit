import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_healthz_reports_database_status(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


@pytest.mark.django_db
def test_backup_db_writes_backup_file(tmp_path):
    call_command("backup_db", output_dir=str(tmp_path), keep=0)

    backups = list(tmp_path.glob("backup-*"))
    assert len(backups) == 1
    assert backups[0].stat().st_size > 0
