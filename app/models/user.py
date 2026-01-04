"""
User model
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

from app.database import Base


class User(Base):
    """User account model"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    
    # Clerk integration
    clerk_id = Column(String(255), unique=True, nullable=True, index=True)
    
    # Basic info
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=True)  # Nullable for Clerk-only users
    avatar_url = Column(String(500), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # User preferences
    preferred_genres = Column(Text, nullable=True)  # JSON string of preferred genres
    search_api_preference = Column(String(20), default="tavily")  # 'tavily' or 'brightdata'
    discovery_frequency = Column(Integer, default=30)  # Minutes between AI searches
    
    # Feature flags
    email_notifications = Column(Boolean, default=True)
    gossip_notifications = Column(Boolean, default=True)
    
    # Relationships
    library_items = relationship("LibraryItem", back_populates="user", cascade="all, delete-orphan")
    recommendations = relationship("Recommendation", back_populates="user", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="user", cascade="all, delete-orphan")
    
    def set_password(self, password: str):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password: str) -> bool:
        """Verify password"""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f"<User {self.username}>"

