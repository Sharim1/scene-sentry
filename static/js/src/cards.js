/**
 * Card Hover Interactions
 */
export function initCardInteractions() {
    // Movie cards - hover effects are handled by CSS
    const movieCards = document.querySelectorAll('.group:has(.aspect-\\[2\\/3\\])');

    movieCards.forEach(card => {
        card.addEventListener('mouseenter', () => {
            card.style.zIndex = '10';
        });

        card.addEventListener('mouseleave', () => {
            card.style.zIndex = '';
        });
    });
}
