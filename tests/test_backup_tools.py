"""Containerized PostgreSQL clients preserve archive streaming and secret boundaries."""

import subprocess

import pytest

from scripts import restore_verify as backup


def environment():
    return {
        "RECALLTRACE_PG_TOOLS_IMAGE": "recalltrace:database-tools",
        "RECALLTRACE_PG_TOOLS_NETWORK": "recall-trace_default",
        "RECALLTRACE_PG_TOOLS_HOST": "postgres",
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
        "PGUSER": "operator",
        "PGPASSWORD": "synthetic-test-password",
        "PGDATABASE": "recalltrace",
    }


def test_dump_streams_to_private_host_file_without_secret_argv(tmp_path, monkeypatch):
    target = tmp_path / "archive.dump"
    env = environment()
    called = []

    def client(command, **kwargs):
        called.append((command, kwargs))
        assert env["PGPASSWORD"] not in command
        assert kwargs["env"]["PGPASSWORD"] == env["PGPASSWORD"]
        assert kwargs["env"]["PGHOST"] == "postgres"
        assert "--entrypoint" in command and "pg_dump" in command
        assert "--file=" + str(target) not in command
        assert "shell" not in kwargs
        kwargs["stdout"].write(b"synthetic archive stream")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(backup.subprocess, "run", client)
    backup.run_private(["pg_dump", "--format=custom", "--file=" + str(target)], env)
    assert target.read_bytes() == b"synthetic archive stream"
    assert len(called) == 1


def test_restore_streams_stdin_and_mounts_tls_readonly(tmp_path, monkeypatch):
    archive = tmp_path / "archive.dump"
    archive.write_bytes(b"synthetic archive")
    ca = tmp_path / "ca.pem"
    ca.write_text("synthetic public CA fixture")
    env = environment() | {"PGSSLMODE": "verify-full", "PGSSLROOTCERT": str(ca)}

    def client(command, **kwargs):
        assert kwargs["stdin"].read() == b"synthetic archive"
        assert str(archive) not in command
        mount = command[command.index("--mount") + 1]
        assert "readonly" in mount and str(ca) in mount
        assert kwargs["env"]["PGSSLMODE"] == "verify-full"
        assert kwargs["env"]["PGSSLROOTCERT"] == "/run/recalltrace-pgsslrootcert.pem"
        assert "synthetic public CA fixture" not in command
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(backup.subprocess, "run", client)
    backup.run_private(["pg_restore", "--dbname", "isolated_restore", str(archive)], env)


@pytest.mark.parametrize(
    "change",
    [
        {"RECALLTRACE_PG_TOOLS_IMAGE": "--privileged"},
        {"RECALLTRACE_PG_TOOLS_NETWORK": "host"},
        {"RECALLTRACE_PG_TOOLS_NETWORK": "container:unrelated"},
    ],
)
def test_operator_settings_cannot_be_reinterpreted_as_cli_options(tmp_path, change):
    with pytest.raises(backup.BackupError):
        backup.run_private(
            ["pg_dump", "--file=" + str(tmp_path / "unused.dump")], environment() | change
        )


def test_tool_failure_redacts_stderr(tmp_path, monkeypatch):
    env = environment()
    monkeypatch.setattr(
        backup.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 2, stderr=env["PGPASSWORD"].encode()
        ),
    )
    with pytest.raises(backup.BackupError) as caught:
        backup.run_private(["pg_dump", "--file=" + str(tmp_path / "archive.dump")], env)
    assert env["PGPASSWORD"] not in str(caught.value)
