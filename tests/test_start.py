import os
from unittest.mock import patch

from app.__main__ import main


def test_start_binds_to_port_env(monkeypatch):
    monkeypatch.setenv("PORT", "43181")
    with patch("app.__main__.os.execvp") as execvp:
        main()
    args = execvp.call_args.args
    assert args[1][-2:] == ["--port", "43181"]
    assert "uvicorn" in args[1]


def test_start_defaults_port_when_unset():
    env = {k: v for k, v in os.environ.items() if k != "PORT"}
    with patch.dict(os.environ, env, clear=True), patch("app.__main__.os.execvp") as execvp:
        main()
    assert execvp.call_args.args[1][-2:] == ["--port", "8080"]
