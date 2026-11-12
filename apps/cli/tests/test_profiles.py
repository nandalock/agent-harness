from pathlib import Path

import pytest

from agent_platform_cli._profile_worker import owns_export
from agent_platform_cli.profiles import Profile, atomic_write, main
from agent_platform_app_boot import load_config


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
    assert not env["PLUGIN_CONFIG"]
    assert env["MINIDSH_PROFILE_CONFIG"] == str(profile.root / "cordis.yml")
    assert env["MINIDSH_PROFILE_PATCH"] == str(profile.root / "cordis.patch.yml")
    assert env["DATABASE_URL"] == "postgresql://profile"
    assert "PYTHONPATH" not in env
    assert profile.venv != Profile("web").venv
    with pytest.raises(ValueError):
        Profile("../repo")


def test_toggling_writes_profile_patch_and_preserves_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    profile = Profile("web")
    profile.root.mkdir(parents=True)
    root = "plugins: []\n"
    profile.config.write_text(root, encoding="utf-8")
    monkeypatch.setattr(profile, "execute", lambda *args, **kwargs: None)
    for key, value in profile.configuration_environment().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(profile, "worker", lambda action: load_config().model_dump(mode="json"))
    profile.toggle("memory", disabled=True)
    assert profile.config.read_text(encoding="utf-8") == root
    assert profile.patch_document().patches[0].disabled is True
    profile.toggle("memory", disabled=False)
    assert profile.patch_document().patches[0].disabled is False


def test_profile_lock_refuses_an_overlapping_operation(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    profile = Profile("web")
    with profile.exclusive():
        with pytest.raises(RuntimeError, match="Profile is in use"):
            with profile.exclusive():
                pytest.fail("concurrent operation acquired the lock")
    with profile.exclusive():
        assert profile.root.is_dir()


def test_export_must_belong_to_distribution():
    files = {"example/__init__.py", "example/tools.py", "single.py"}
    assert owns_export(files, "example:Plugin")
    assert owns_export(files, "example.tools:plugin")
    assert owns_export(files, "single:factory")
    assert not owns_export(files, "example.other:Plugin")
    assert not owns_export(files, "os:Other")


def test_uninitialized_profile_provides_setup_hint(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MINIDSH_HOME", str(tmp_path))
    assert main(["plugin", "list", "--profile", "missing"]) == 1
    assert "profile init --profile missing" in capsys.readouterr().err
