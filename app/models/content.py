"""
Content model for movies, TV shows, and books
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now():
    """Get current UTC time (timezone-aware)"""
    return datetime.now(timezone.utc)


class Content(Base):
    """Entertainment content model (movies, TV shows, books)"""
    __tablename__ = "content"
    
    id = Column(Integer, primary_key=True)
    
    # Basic info
    title = Column(String(200), nullable=False, index=True)
    content_type = Column(String(20), nullable=False, index=True)  # 'movie', 'tv_show', 'book'
    description = Column(Text, nullable=True)
    genres = Column(Text, nullable=True)  # JSON string
    
    # External IDs
    external_id = Column(String(50), nullable=True)
    tmdb_id = Column(Integer, nullable=True, index=True)
    imdb_id = Column(String(20), nullable=True)
    isbn = Column(String(20), nullable=True)
    
    # Media
    poster_url = Column(String(500), nullable=True)
    backdrop_url = Column(String(500), nullable=True)
    trailer_url = Column(String(500), nullable=True)
    
    # Details
    release_date = Column(String(20), nullable=True)
    runtime = Column(Integer, nullable=True)  # In minutes
    rating = Column(Float, nullable=True)  # Average rating
    
    # Book specific
    author = Column(String(200), nullable=True)
    page_count = Column(Integer, nullable=True)
    
    # Movie specific
    director = Column(String(200), nullable=True)
    budget = Column(Integer, nullable=True)
    
    # TV specific
    seasons = Column(Integer, nullable=True)
    episodes = Column(Integer, nullable=True)
    status = Column(String(50), nullable=True)  # 'Returning Series', 'Ended', etc.
    network = Column(String(100), nullable=True)
    
    # Adaptation tracking (for book-to-screen adaptations)
    is_adaptation = Column(Boolean, default=False)
    adapted_from_id = Column(Integer, nullable=True)  # FK to another Content (book)
    adaptation_status = Column(String(50), nullable=True)  # 'announced', 'in_production', 'released'
    
    # Scheduling (for upcoming releases)
    next_episode_date = Column(DateTime, nullable=True)
    premiere_date = Column(DateTime, nullable=True)
    
    # Timestamps (timezone-aware)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    
    # Relationships
    library_items = relationship("LibraryItem", back_populates="content")
    recommendations = relationship("Recommendation", back_populates="content")
    gossip_items = relationship("Gossip", back_populates="related_content")
    
    def __repr__(self):
        return f"<Content {self.title} ({self.content_type})>"

