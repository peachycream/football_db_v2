"""football_db v2 web app. Blueprints read mart_* views only (REBUILD_DESIGN 2.2);
the only tables they write are app_* (user-entered state).

Run with the 3.13 interpreter (bare `python` is 3.14 with no Flask):
    <Python313>/python.exe -m app          # http://127.0.0.1:5001/  (APP_PORT; ops/start_app.bat serves :5000)
"""
from pathlib import Path

from flask import Flask


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"), static_url_path="/static")
    from .ownership import bp as ownership_bp
    from .matchups import bp as matchups_bp
    from .env import bp as env_bp
    from .viz import bp as viz_bp
    from .dashboard import bp as dashboard_bp
    from .matchup_card import bp as matchup_card_bp
    app.register_blueprint(ownership_bp)
    app.register_blueprint(matchups_bp)
    app.register_blueprint(env_bp)
    app.register_blueprint(viz_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(matchup_card_bp)
    from .shell import hub_html
    app.add_url_rule("/", "home", hub_html)
    return app
