import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_apscheduler import APScheduler

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
scheduler = APScheduler()

# create the app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-in-production")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# configure logging
logging.basicConfig(level=logging.DEBUG)

# configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///entertainment_discovery.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# APScheduler configuration
app.config['SCHEDULER_API_ENABLED'] = True

# initialize extensions
db.init_app(app)
scheduler.init_app(app)

with app.app_context():
    # Import models to ensure tables are created
    import models  # noqa: F401
    db.create_all()

# Add template filter for JSON parsing
import json

@app.template_filter('from_json')
def from_json_filter(value):
    try:
        return json.loads(value) if value else []
    except:
        return []

# Import routes after app initialization
import routes  # noqa: F401

if __name__ == '__main__':
    scheduler.start()
    app.run(host='0.0.0.0', port=5000, debug=True)
