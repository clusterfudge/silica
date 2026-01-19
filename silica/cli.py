from cyclopts import App
from dotenv import load_dotenv

from silica import __version__
from silica.remote.cli.main import app as remote_app
from silica.developer.hdev import (
    cyclopts_main as developer_app,
    attach_tools,
    view_session,
)
from silica.developer.cli.memory_sync import memory_sync_app
from silica.developer.cli.history_sync import history_sync_app
from silica.cron.app import entrypoint as cron_serve
from silica.cron.cli import cron as cron_commands
from silica.serve.cli import serve_app
from silica.voice.cli import voice_app

app = App(version=__version__)
app.command(remote_app, name="remote")
app.command(cron_serve, name="cron-serve")
app.command(cron_commands, name="cron")
app.command(memory_sync_app, name="memory-sync")
app.command(history_sync_app, name="history-sync")
app.command(view_session, name="view")
app.command(serve_app, name="serve")
app.command(voice_app, name="voice")
attach_tools(app)
app.default(developer_app)

load_dotenv()


def main():
    app()
