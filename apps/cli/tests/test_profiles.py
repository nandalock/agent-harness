from pathlib import Path
from zipfile import ZipFile

import pytest

from agent_platform_cli.profiles import Profile, atomic_write, main, wheel_entries


def test_managed_profile_uses_home_and_ignores_repository_plugin_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    monkeypatch.setenv("PLUGIN_CONFIG", "outside.yaml")
    monkeypatch.setenv("PYTHONPATH", str(Path.cwd()))
    profile = Profile("research")
    with profile.exclusive():
        atomic_write(profile.env_file, "DATABASE_URL=postgresql://profile\n")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        env = profile.environment()
    assert profile.root == tmp_path / "profiles" / "research"
    assert env["PLUGIN_CONFIG"] == str(profile.config)
    assert env["DATABASE_URL"] == "postgresql://profile"
    assert "PYTHONPATH" not in env
    assert profile.venv != Profile("web").venv
    with pytest.raises(ValueError):
        Profile("../repo")


def test_profile_lock_refuses_an_overlapping_operation(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    profile = Profile("web")
    with profile.exclusive():
        with pytest.raises(RuntimeError, match="Profile is in use"):
            with profile.exclusive():
                pytest.fail("concurrent operation acquired the lock")
    with profile.exclusive():
        assert profile.root.is_dir()


def test_wheel_entries_are_read_without_importing_plugin(tmp_path):
    wheel = tmp_path / "example_plugin-0.1-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("example_plugin-0.1.dist-info/entry_points.txt",
                         "[agent_platform.plugins]\nexample.echo = echo:Plugin\n")
        archive.writestr("echo.py", "raise AssertionError('must not import')")
    assert wheel_entries(wheel) == ("example.echo",)


def test_uninitialized_profile_provides_setup_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    assert main(["plugin", "list", "--profile", "missing"]) == 1
    assert "profile init --profile missing" in capsys.readouterr().err
