// Main JavaScript functionality for EntertainmentAI

document.addEventListener('DOMContentLoaded', function() {
    // Initialize all components
    initializeTooltips();
    initializeModals();
    initializeFormValidation();
    initializeStarRatings();
    initializeSearchFunctionality();
    initializeNotifications();
});

// Initialize Bootstrap tooltips
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// Initialize Bootstrap modals
function initializeModals() {
    const modalTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="modal"]'));
    modalTriggerList.map(function(modalTriggerEl) {
        return new bootstrap.Modal(modalTriggerEl);
    });
}

// Form validation enhancement
function initializeFormValidation() {
    const forms = document.querySelectorAll('.needs-validation');
    
    Array.prototype.slice.call(forms).forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            } else {
                // Add loading state to submit button
                const submitBtn = form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.classList.add('loading');
                    submitBtn.disabled = true;
                }
            }
            form.classList.add('was-validated');
        }, false);
    });
}

// Star rating functionality
function initializeStarRatings() {
    const starContainers = document.querySelectorAll('.rating-stars');
    
    starContainers.forEach(container => {
        const stars = container.querySelectorAll('.star-label');
        const inputs = container.querySelectorAll('input[type="radio"]');
        
        // Handle hover effects
        stars.forEach((star, index) => {
            star.addEventListener('mouseenter', function() {
                highlightStars(container, index + 1);
            });
            
            star.addEventListener('click', function() {
                const input = star.querySelector('input');
                input.checked = true;
                highlightStars(container, index + 1, true);
            });
        });
        
        // Reset on mouse leave
        container.addEventListener('mouseleave', function() {
            const checkedInput = container.querySelector('input:checked');
            const rating = checkedInput ? checkedInput.value : 0;
            highlightStars(container, rating, true);
        });
        
        // Initialize with current value
        const checkedInput = container.querySelector('input:checked');
        if (checkedInput) {
            highlightStars(container, checkedInput.value, true);
        }
    });
}

function highlightStars(container, rating, permanent = false) {
    const stars = container.querySelectorAll('.star-input');
    
    stars.forEach((star, index) => {
        if (index < rating) {
            star.style.color = '#ffc107';
        } else {
            star.style.color = permanent ? '#6c757d' : '#6c757d';
        }
    });
}

// Search functionality with debouncing
function initializeSearchFunctionality() {
    const searchInputs = document.querySelectorAll('input[type="search"], .search-input');
    
    searchInputs.forEach(input => {
        let debounceTimer;
        
        input.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                handleSearchInput(this);
            }, 300);
        });
    });
}

function handleSearchInput(input) {
    const query = input.value.trim();
    
    if (query.length >= 3) {
        // Add visual feedback
        input.classList.add('searching');
        
        // In a real implementation, you might want to add instant search
        // For now, we'll just provide visual feedback
        setTimeout(() => {
            input.classList.remove('searching');
        }, 1000);
    }
}

// Notification system
function initializeNotifications() {
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
}

// Library filtering functionality
function filterLibraryItems() {
    const typeFilter = document.getElementById('typeFilter');
    const statusFilter = document.getElementById('statusFilter');
    const sortFilter = document.getElementById('sortFilter');
    
    if (!typeFilter || !statusFilter) return;
    
    const items = document.querySelectorAll('.library-item');
    const selectedType = typeFilter.value;
    const selectedStatus = statusFilter.value;
    const selectedSort = sortFilter ? sortFilter.value : 'updated';
    
    // Filter items
    const visibleItems = [];
    
    items.forEach(item => {
        const itemType = item.dataset.type;
        const itemStatus = item.dataset.status;
        
        const typeMatch = selectedType === 'all' || itemType === selectedType;
        const statusMatch = selectedStatus === 'all' || itemStatus === selectedStatus;
        
        if (typeMatch && statusMatch) {
            item.style.display = 'block';
            visibleItems.push(item);
        } else {
            item.style.display = 'none';
        }
    });
    
    // Sort visible items
    if (sortFilter) {
        sortLibraryItems(visibleItems, selectedSort);
    }
}

function sortLibraryItems(items, sortBy) {
    const container = document.querySelector('.library-grid');
    if (!container) return;
    
    const sortedItems = Array.from(items).sort((a, b) => {
        switch (sortBy) {
            case 'title':
                const titleA = a.querySelector('h5').textContent.toLowerCase();
                const titleB = b.querySelector('h5').textContent.toLowerCase();
                return titleA.localeCompare(titleB);
                
            case 'rating':
                const ratingA = a.querySelectorAll('.star.filled').length;
                const ratingB = b.querySelectorAll('.star.filled').length;
                return ratingB - ratingA;
                
            case 'added':
            case 'updated':
            default:
                // Default sorting by DOM order (already sorted by updated date)
                return 0;
        }
    });
    
    // Reorder in DOM
    sortedItems.forEach(item => {
        container.appendChild(item);
    });
}

// Recommendation actions
function handleRecommendationAction(button, action) {
    const card = button.closest('.recommendation-card');
    
    // Add visual feedback
    card.style.opacity = '0.6';
    button.disabled = true;
    
    // In a real implementation, this would make an AJAX call
    // For now, we'll just provide visual feedback
    setTimeout(() => {
        if (action === 'dismiss') {
            card.style.display = 'none';
        } else {
            card.style.opacity = '1';
            button.disabled = false;
            
            // Show success message
            showNotification(`Added to library as ${action}!`, 'success');
        }
    }, 500);
}

// Utility function to show notifications
function showNotification(message, type = 'info') {
    const alertContainer = document.querySelector('.container');
    if (!alertContainer) return;
    
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    alertContainer.insertBefore(alertDiv, alertContainer.firstChild);
    
    // Auto-dismiss after 3 seconds
    setTimeout(() => {
        const bsAlert = new bootstrap.Alert(alertDiv);
        bsAlert.close();
    }, 3000);
}

// Progress tracking for TV shows
function updateProgress(itemId, currentEpisode, totalEpisodes) {
    const progressBars = document.querySelectorAll(`[data-item-id="${itemId}"] .progress-bar`);
    
    progressBars.forEach(bar => {
        const percentage = (currentEpisode / totalEpisodes) * 100;
        bar.style.width = `${percentage}%`;
        bar.setAttribute('aria-valuenow', percentage);
    });
}

// Theme toggle functionality (for future implementation)
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    html.setAttribute('data-bs-theme', newTheme);
    localStorage.setItem('theme', newTheme);
}

// Load saved theme preference
function loadThemePreference() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-bs-theme', savedTheme);
}

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + K for search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[name="query"]');
        if (searchInput) {
            searchInput.focus();
        }
    }
    
    // Escape to close modals
    if (e.key === 'Escape') {
        const openModals = document.querySelectorAll('.modal.show');
        openModals.forEach(modal => {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
        });
    }
});

// Smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Form auto-save functionality (for settings)
function initializeAutoSave() {
    const autoSaveForms = document.querySelectorAll('.auto-save');
    
    autoSaveForms.forEach(form => {
        const inputs = form.querySelectorAll('input, select, textarea');
        
        inputs.forEach(input => {
            input.addEventListener('change', function() {
                debounce(() => {
                    saveFormData(form);
                }, 1000)();
            });
        });
    });
}

function saveFormData(form) {
    const formData = new FormData(form);
    const data = Object.fromEntries(formData);
    
    // Save to localStorage as backup
    localStorage.setItem('formBackup', JSON.stringify(data));
    
    // In a real implementation, you would send this to the server
    console.log('Auto-saving form data:', data);
}

// Debounce utility function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Initialize auto-save on page load
document.addEventListener('DOMContentLoaded', function() {
    initializeAutoSave();
    loadThemePreference();
});

// Performance monitoring
function trackPageLoad() {
    window.addEventListener('load', function() {
        const loadTime = performance.now();
        console.log(`Page loaded in ${loadTime.toFixed(2)}ms`);
        
        // In a real implementation, you might send this to analytics
    });
}

trackPageLoad();

// Export functions for use in other scripts
window.EntertainmentAI = {
    filterLibraryItems,
    handleRecommendationAction,
    showNotification,
    updateProgress,
    toggleTheme
};
