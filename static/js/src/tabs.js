/**
 * Tab Navigation
 */
export function initTabs() {
    const tabContainers = document.querySelectorAll('[data-tabs]');

    tabContainers.forEach(container => {
        const tabs = container.querySelectorAll('[data-tab]');
        const panels = container.querySelectorAll('[data-panel]');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetPanel = tab.dataset.tab;

                // Update tab states
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                // Update panel visibility
                panels.forEach(p => {
                    p.classList.toggle('hidden', p.dataset.panel !== targetPanel);
                });
            });
        });
    });
}
