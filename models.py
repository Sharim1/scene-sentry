from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # User preferences
    preferred_genres = db.Column(db.Text)  # JSON string of preferred genres
    search_api_preference = db.Column(db.String(20), default='tavily')  # 'tavily' or 'brightdata'
    discovery_frequency = db.Column(db.Integer, default=30)  # Minutes between AI searches
    
    # Relationships
    library_items = db.relationship('LibraryItem', backref='user', lazy=True, cascade='all, delete-orphan')
    recommendations = db.relationship('Recommendation', backref='user', lazy=True, cascade='all, delete-orphan')
    reminders = db.relationship('Reminder', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Content(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content_type = db.Column(db.String(20), nullable=False)  # 'movie', 'tv_show', 'book'
    external_id = db.Column(db.String(50))  # TMDb ID, ISBN, etc.
    description = db.Column(db.Text)
    genres = db.Column(db.Text)  # JSON string
    release_date = db.Column(db.String(20))
    poster_url = db.Column(db.String(500))
    imdb_id = db.Column(db.String(20))
    tmdb_id = db.Column(db.Integer)
    isbn = db.Column(db.String(20))
    author = db.Column(db.String(200))  # For books
    director = db.Column(db.String(200))  # For movies
    seasons = db.Column(db.Integer)  # For TV shows
    episodes = db.Column(db.Integer)  # For TV shows
    runtime = db.Column(db.Integer)  # In minutes
    rating = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    library_items = db.relationship('LibraryItem', backref='content', lazy=True)
    recommendations = db.relationship('Recommendation', backref='content', lazy=True)

class LibraryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content_id = db.Column(db.Integer, db.ForeignKey('content.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'confirmed', 'maybe', 'in_progress', 'finished', 'removed'
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    progress = db.Column(db.Integer, default=0)  # For tracking episodes/chapters
    rating = db.Column(db.Integer)  # User's personal rating 1-5
    notes = db.Column(db.Text)
    
    # For TV shows with weekly releases
    weekly_release = db.Column(db.Boolean, default=False)
    next_episode_date = db.Column(db.DateTime)

class Recommendation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content_id = db.Column(db.Integer, db.ForeignKey('content.id'), nullable=False)
    confidence_score = db.Column(db.Float, default=0.5)  # 0-1 confidence in recommendation
    reasoning = db.Column(db.Text)  # Why this was recommended
    source_urls = db.Column(db.Text)  # JSON array of source URLs
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    viewed = db.Column(db.Boolean, default=False)
    dismissed = db.Column(db.Boolean, default=False)

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    library_item_id = db.Column(db.Integer, db.ForeignKey('library_item.id'), nullable=False)
    reminder_type = db.Column(db.String(20), nullable=False)  # 'watch', 'read', 'next_episode'
    scheduled_time = db.Column(db.DateTime, nullable=False)
    message = db.Column(db.Text)
    sent = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    library_item = db.relationship('LibraryItem', backref='reminders')

class SearchLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    query = db.Column(db.String(500), nullable=False)
    api_used = db.Column(db.String(20), nullable=False)  # 'tavily', 'brightdata', 'tmdb'
    results_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    execution_time = db.Column(db.Float)  # In seconds
