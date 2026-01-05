"""Script to clean up article-style entries from the database"""
import re
from app.database import SessionLocal
from app.models import Content, LibraryItem

def is_article_title(title):
    if not title:
        return True
    
    article_patterns = [
        r'\d{4}\s+movies',
        r'\d{4}\s*-\s*$',
        r'best\s+(upcoming|new|films|movies|tv|of)',
        r'top\s+\d+',
        r'the\s+\d+\s+best',
        r'the\s+(ten|twenty|best|top)\s+(best|movies)',
        r'release\s+dates',
        r'ranked\s+by',
        r'updated\s+weekly',
        r'school\s+year',
        r'trailers?\s*\)',
        r'so\s+far',
        r'r/movies',
        r'r/television',
        r'winter\s+\d{4}',
        r'letterboxd',
        r'tomatometer',
        r'most\s+anticipated',
        r'new\s+and\s+upcoming',
        r'^\s*my\s+top\s+\d+',
        r'^\s*top\s+movies\s+of',
    ]
    
    title_lower = title.lower()
    for pattern in article_patterns:
        if re.search(pattern, title_lower):
            return True
    
    if len(title) > 55:
        return True
    if len(title) < 2:
        return True
    
    return False

def main():
    db = SessionLocal()
    all_content = db.query(Content).all()
    deleted_count = 0

    for content in all_content:
        if is_article_title(content.title):
            # Check if any library items reference this
            library_refs = db.query(LibraryItem).filter(LibraryItem.content_id == content.id).count()
            
            if library_refs == 0:
                print(f'Deleting: {content.title}')
                db.delete(content)
                deleted_count += 1
            else:
                print(f'Skipping (in library): {content.title}')

    db.commit()
    print(f'\nCleaned up {deleted_count} article-style entries')
    db.close()

if __name__ == "__main__":
    main()

