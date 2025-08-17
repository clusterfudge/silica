from cyclopts import App
from dotenv import load_dotenv

from silica.remote.cli.main import app as remote_app
from silica.developer.hdev import cyclopts_main as developer_app, attach_tools
from silica.cron.entrypoint import app as cron_app

app = App()
app.command(remote_app, name="remote")
app.command(cron_app, name="cron")
attach_tools(app)
app.default(developer_app)

load_dotenv()


def main():
    app()
