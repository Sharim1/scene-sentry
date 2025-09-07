from flask import render_template, request, redirect, url_for, flash, session, jsonify
from app import app, db
from models import User, Content, LibraryItem, Recommendation, Reminder
from werkzeug.security import generate_password_hash, check_password_hash
from langraph_agents import discovery_graph
from content_apis import TMDbAPI, search_content_online
import json
import asyncio
import logging
from datetime import datetime, timedelta

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        search_api = request.form.get('search_api', 'tavily')
        
        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return render_template('register.html')
        
        # Create new user
        user = User(
            username=username,
            email=email,
            search_api_preference=search_api
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        session['user_id'] = user.id
        session['username'] = user.username
        
        flash('Registration successful!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Get recent recommendations
    recent_recommendations = db.session.query(Recommendation).filter_by(
        user_id=user_id, dismissed=False
    ).order_by(Recommendation.confidence_score.desc()).limit(10).all()
    
    # Get library stats
    library_stats = {
        'confirmed': LibraryItem.query.filter_by(user_id=user_id, status='confirmed').count(),
        'in_progress': LibraryItem.query.filter_by(user_id=user_id, status='in_progress').count(),
        'finished': LibraryItem.query.filter_by(user_id=user_id, status='finished').count(),
        'maybe': LibraryItem.query.filter_by(user_id=user_id, status='maybe').count()
    }
    
    # Get upcoming reminders
    upcoming_reminders = Reminder.query.filter_by(
        user_id=user_id, sent=False
    ).filter(
        Reminder.scheduled_time <= datetime.utcnow() + timedelta(days=7)
    ).order_by(Reminder.scheduled_time).limit(5).all()
    
    return render_template('dashboard.html', 
                         recommendations=recent_recommendations,
                         library_stats=library_stats,
                         upcoming_reminders=upcoming_reminders)

@app.route('/library')
def library():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    content_type = request.args.get('type', 'all')
    status = request.args.get('status', 'all')
    
    query = db.session.query(LibraryItem).filter_by(user_id=user_id)
    
    if content_type != 'all':
        query = query.join(Content).filter(Content.content_type == content_type)
    
    if status != 'all':
        query = query.filter(LibraryItem.status == status)
    
    library_items = query.order_by(LibraryItem.updated_at.desc()).all()
    
    return render_template('library.html', 
                         library_items=library_items,
                         current_type=content_type,
                         current_status=status)

@app.route('/update_library_item', methods=['POST'])
def update_library_item():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    item_id = request.form['item_id']
    new_status = request.form['status']
    
    library_item = LibraryItem.query.filter_by(
        id=item_id, user_id=session['user_id']
    ).first()
    
    if library_item:
        library_item.status = new_status
        library_item.updated_at = datetime.utcnow()
        
        # Handle weekly release tracking
        if new_status == 'in_progress' and 'weekly_release' in request.form:
            library_item.weekly_release = True
            # Set next episode reminder (this is simplified)
            next_date = datetime.utcnow() + timedelta(days=7)
            reminder = Reminder(
                user_id=session['user_id'],
                library_item_id=library_item.id,
                reminder_type='next_episode',
                scheduled_time=next_date,
                message=f"New episode of {library_item.content.title} should be available!"
            )
            db.session.add(reminder)
        
        db.session.commit()
        flash('Library item updated successfully!', 'success')
    
    return redirect(url_for('library'))

@app.route('/add_to_library', methods=['POST'])
def add_to_library():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    recommendation_id = request.form['recommendation_id']
    status = request.form['status']
    
    recommendation = Recommendation.query.filter_by(
        id=recommendation_id, user_id=session['user_id']
    ).first()
    
    if recommendation:
        # Check if already in library
        existing = LibraryItem.query.filter_by(
            user_id=session['user_id'],
            content_id=recommendation.content_id
        ).first()
        
        if existing:
            existing.status = status
            existing.updated_at = datetime.utcnow()
        else:
            library_item = LibraryItem(
                user_id=session['user_id'],
                content_id=recommendation.content_id,
                status=status
            )
            db.session.add(library_item)
        
        # Mark recommendation as viewed
        recommendation.viewed = True
        db.session.commit()
        
        flash('Added to library successfully!', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/dismiss_recommendation', methods=['POST'])
def dismiss_recommendation():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    recommendation_id = request.form['recommendation_id']
    
    recommendation = Recommendation.query.filter_by(
        id=recommendation_id, user_id=session['user_id']
    ).first()
    
    if recommendation:
        recommendation.dismissed = True
        db.session.commit()
        flash('Recommendation dismissed', 'info')
    
    return redirect(url_for('dashboard'))

@app.route('/search_content', methods=['POST'])
def search_content():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    query = request.form['query']
    user_id = session['user_id']
    
    try:
        # Use the new LangGraph-based discovery system with timeout
        async def run_with_timeout():
            return await discovery_graph.run_discovery(user_id, search_query=query)
        
        results = asyncio.run(asyncio.wait_for(run_with_timeout(), timeout=18.0))
        
        flash(f'Search completed! Found {len(results)} potential recommendations using advanced AI reasoning.', 'success')
    except asyncio.TimeoutError:
        logging.warning(f"Search timeout for user {user_id}, query: {query}")
        flash('Search is taking longer than expected. Check back shortly for results.', 'warning')
    except Exception as e:
        logging.error(f"Error in search_content: {e}")
        flash('Search temporarily unavailable. Please try again later.', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/force_discovery', methods=['POST'])
def force_discovery():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    try:
        # Use the new LangGraph-based discovery system with timeout protection
        import asyncio
        
        async def run_with_timeout():
            return await discovery_graph.run_discovery(user_id)
        
        # Set a reasonable timeout (20 seconds with optimized workflow)
        results = asyncio.run(asyncio.wait_for(run_with_timeout(), timeout=20.0))
        
        if results:
            flash(f'Discovery completed! Found {len(results)} new recommendations using advanced AI agent orchestration.', 'success')
        else:
            flash('No new recommendations found at this time. Try adjusting your preferences or try again later.', 'info')
    except asyncio.TimeoutError:
        logging.warning(f"Discovery timeout for user {user_id}")
        flash('Discovery is taking longer than expected. Check back in a few minutes for results.', 'warning')
    except Exception as e:
        logging.error(f"Error in force discovery: {e}")
        flash('Discovery temporarily unavailable. Please try again later.', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        user.search_api_preference = request.form.get('search_api', 'tavily')
        preferred_genres = request.form.getlist('genres')
        user.preferred_genres = json.dumps(preferred_genres)
        user.discovery_frequency = int(request.form.get('discovery_frequency', 30))
        
        db.session.commit()
        flash('Settings updated successfully!', 'success')
        return redirect(url_for('settings'))
    
    # Parse current preferences
    current_genres = []
    if user.preferred_genres:
        try:
            current_genres = json.loads(user.preferred_genres)
        except:
            current_genres = []
    
    available_genres = [
        'Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary',
        'Drama', 'Family', 'Fantasy', 'History', 'Horror', 'Music', 'Mystery',
        'Romance', 'Science Fiction', 'Thriller', 'War', 'Western'
    ]
    
    return render_template('settings.html', 
                         user=user,
                         current_genres=current_genres,
                         available_genres=available_genres)
