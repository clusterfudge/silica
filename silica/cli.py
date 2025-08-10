from cyclopts import App
from silica.remote.cli.main import app as remote_app
from silica.developer.hdev import cyclopts_main as developer_app

app = App()
app.command(remote_app, name="remote")
app.default(developer_app)


def main():
    app()
