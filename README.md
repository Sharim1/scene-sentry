# Entertainment Discovery AI App

## Overview

This is a Flask-based entertainment discovery application that uses AI agents to continuously search and recommend movies, TV shows, and books tailored to user preferences. The system runs background processes that analyze user behavior and search across multiple sources to provide personalized content recommendations. Users can manage their discoveries through a library system with status tracking (confirmed, in progress, finished, maybe) and receive intelligent reminders.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Backend Architecture
- **Framework**: Flask web application with SQLAlchemy ORM for database operations
- **Database**: SQLite for development with configurable database URI (designed to support PostgreSQL in production)
- **Background Processing**: APScheduler for running continuous discovery tasks and reminder notifications
- **AI Integration**: Google Gemini API for content analysis and recommendation generation

### Core Components
- **AI Agents** (`ai_agents.py`): RecommendationAgent that analyzes user preferences and generates personalized recommendations
- **Content APIs** (`content_apis.py`): TMDbAPI integration for fetching movie/TV show metadata and web scraping capabilities
- **Background Tasks** (`background_tasks.py`): Scheduled jobs for continuous content discovery and reminder system
- **Models** (`models.py`): Database schema including User, Content, LibraryItem, Recommendation, and Reminder entities

### Data Models
- **User**: Authentication, preferences, and API choice configuration
- **Content**: Unified content model supporting movies, TV shows, and books with metadata
- **LibraryItem**: User-content relationship with status tracking and ratings
- **Recommendation**: AI-generated suggestions with confidence scoring
- **Reminder**: Scheduled notifications for user engagement

### Frontend Architecture
- **Template Engine**: Jinja2 templates with Bootstrap 5 dark theme
- **JavaScript**: Vanilla JS for interactive features including star ratings, modals, and search
- **Responsive Design**: Mobile-first approach with component-based CSS architecture

### Authentication & Session Management
- **Security**: Werkzeug password hashing with Flask sessions
- **User Management**: Registration with API preference selection and profile management

## External Dependencies

### AI & Search APIs
- **Google Gemini API**: Primary AI service for content analysis and recommendation generation
- **TMDb API**: Movie and TV show metadata, poster images, and detailed content information
- **Tavily/Bright Data APIs**: Web search capabilities for content discovery (user-configurable)

### Infrastructure Services
- **Database**: SQLite (development) with PostgreSQL compatibility for production
- **Background Jobs**: APScheduler for task scheduling and execution
- **Web Scraping**: Trafilatura library for content extraction from web sources

### Frontend Dependencies
- **Bootstrap 5**: UI framework with dark theme support
- **Feather Icons**: Icon system for consistent visual elements
- **Custom CSS**: Component-based styling with CSS variables and gradients

### Development Tools
- **Flask-SQLAlchemy**: ORM with relationship management and migrations
- **Werkzeug**: WSGI utilities and security features
- **Logging**: Built-in Python logging for debugging and monitoring