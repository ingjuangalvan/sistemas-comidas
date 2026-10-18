(() => {
    const grid = document.getElementById('public-menu-grid');
    const tabs = document.getElementById('public-category-tabs');
    const status = document.getElementById('public-menu-status');
    let menuData = null;
    let activeCategory = 'all';
    let requestId = 0;

    async function loadMenu() {
        const currentRequest = ++requestId;
        try {
            const data = await window.app.request('/api/menu/', {cache: 'no-store'});
            if (currentRequest !== requestId) return;
            menuData = data;
            window.BUSINESS_CURRENCY_SYMBOL = data.symbol;
            renderTabs();
            renderProducts();
            status.textContent = 'Carta actualizada automáticamente';
        } catch (error) {
            if (currentRequest !== requestId) return;
            status.textContent = 'No se pudo actualizar la carta';
            grid.innerHTML = `<p class="alert-message">${window.app.escape(error.message || 'Intenta actualizar la página.')}</p>`;
        }
    }

    function renderTabs() {
        tabs.innerHTML = `<button class="category-tab ${activeCategory === 'all' ? 'is-active' : ''}" data-category="all">Todo</button>` +
            menuData.categories.map(category =>
                `<button class="category-tab ${activeCategory === String(category.id) ? 'is-active' : ''}" data-category="${category.id}">${window.app.escape(category.name)}</button>`
            ).join('');
    }

    function renderProducts() {
        const categories = activeCategory === 'all'
            ? menuData.categories
            : menuData.categories.filter(category => String(category.id) === activeCategory);
        const products = categories.flatMap(category =>
            category.products.map(product => ({...product, categoryName: category.name}))
        );
        grid.innerHTML = products.length ? products.map(product => {
            const inventory = product.stock_tracked
                ? product.stock_quantity === null
                    ? 'Existencias por configurar'
                    : `Disponibles: ${product.stock_quantity}`
                : '';
            return `<article class="product-card">
                <div class="product-top"><div><div class="product-tag">${product.featured ? 'FAVORITO DE LA CASA' : 'DE NUESTRA COCINA'}</div><h3>${window.app.escape(product.name)}</h3></div><span class="product-price">${window.app.money(product.price)}</span></div>
                <p>${window.app.escape(product.description || 'Preparado con ingredientes de la casa.')}</p>
                ${inventory ? `<small class="stock-notice">${window.app.escape(inventory)}</small>` : ''}
                <div class="product-bottom"><span class="eyebrow">${window.app.escape(product.categoryName)}</span></div>
            </article>`;
        }).join('') : '<p class="empty-state">No hay productos disponibles en esta categoría por ahora.</p>';
    }

    tabs.addEventListener('click', event => {
        const button = event.target.closest('[data-category]');
        if (!button) return;
        activeCategory = button.dataset.category;
        renderTabs();
        renderProducts();
    });

    loadMenu();
    window.setInterval(loadMenu, 30000);
})();
