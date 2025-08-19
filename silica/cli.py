from cyclopts import App
from dotenv import load_dotenv

from silica.remote.cli.main import app as remote_app
from silica.developer.hdev import cyclopts_main as developer_app, attach_tools
from silica.cron.app import entrypoint as cron_serve
from silica.cron.cli import cron as cron_commands

app = App()
app.command(remote_app, name="remote")
app.command(cron_serve, name="cron-serve")
app.command(cron_commands, name="cron")
attach_tools(app)
app.default(developer_app)

load_dotenv()


def main():
    app()
