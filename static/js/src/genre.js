/**
 * Genre Selector with Visual Feedback
 */
export function initGenreSelector() {
    const genreLabels = document.querySelectorAll('label:has(input[name="genres"])');

    genreLabels.forEach(label => {
        const checkbox = label.querySelector('input[type="checkbox"]');
        if (!checkbox) return;

        checkbox.addEventListener('change', () => {
            label.classList.toggle('ring-2', checkbox.checked);
            label.classList.toggle('ring-primary', checkbox.checked);
            label.classList.toggle('bg-primary/10', checkbox.checked);

            // Update check icon
            const iconContainer = label.querySelector('.w-4.h-4.rounded');
            if (iconContainer) {
                iconContainer.classList.toggle('bg-primary', checkbox.checked);
                iconContainer.classList.toggle('border-primary', checkbox.checked);
                iconContainer.innerHTML = checkbox.checked
                    ? '<i data-lucide="check" class="w-3 h-3 text-white"></i>'
                    : '';
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            }
        });
    });
}
