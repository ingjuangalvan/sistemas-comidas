(() => {
    let orders = [];
    let kitchenOrders = [];
    let orderPagination = {page: 1, pages: 1, total: 0};
    let orderPage = 1;
    let orderRequestId = 0;
    let kitchenRequestId = 0;
    let cashMetricRequestId = 0;
    let reportRequestId = 0;
    let expensesRequestId = 0;
    let profitRequestId = 0;
    let reportAllSelected = false;
    let activeFilter = 'all';
    let currentCash = null;
    let cashHistory = [];
    let products = [];
    let productCategories = [];
    let orderBeingEdited = null;
    let paidReceiptOrder = null;
    const cashDenominations = [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];
    const digitalPaymentMethods = [
        {label: 'Bancolombia', name: 'verified-bancolombia'},
        {label: 'Nequi', name: 'verified-nequi'},
        {label: 'Tarjeta', name: 'verified-card'},
    ];
    const titles = { overview: 'Resumen del día', orders: 'Pedidos', kitchen: 'Cocina', products: 'Carta', cash: 'Caja', reports: 'Informes', expenses: 'Gastos', profits: 'Beneficios' };
    const statusClass = status => `status-${status}`;
    const shortTime = iso => new Intl.DateTimeFormat('es', { hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
    const shortDateTime = iso => new Intl.DateTimeFormat('es', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(iso));
    const today = new Date();
    const todayInputValue = [
        today.getFullYear(),
        String(today.getMonth() + 1).padStart(2, '0'),
        String(today.getDate()).padStart(2, '0'),
    ].join('-');
    const dateLabel = new Intl.DateTimeFormat('es', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(new Date());
    document.getElementById('date-label').textContent = dateLabel.toUpperCase();
    document.getElementById('order-date-from').value = todayInputValue;
    document.getElementById('order-date-to').value = todayInputValue;

    function setView(name) {
        document.querySelectorAll('.nav-item').forEach(button => button.classList.toggle('is-active', button.dataset.view === name));
        document.querySelectorAll('.view-panel').forEach(panel => panel.classList.toggle('is-visible', panel.id === `view-${name}`));
        document.getElementById('page-title').textContent = titles[name];
        document.getElementById('sidebar').classList.remove('is-open');
        if (name === 'products') loadProducts();
        if (name === 'cash') loadCash();
        if (name === 'reports') {
            reportAllSelected = false;
            document.querySelectorAll('[data-report-range]').forEach(button => {
                const selected = button.dataset.reportRange === 'month';
                button.classList.toggle('is-active', selected);
                button.setAttribute('aria-pressed', String(selected));
            });
            loadReport();
        }
        if (name === 'expenses') loadExpenses();
        if (name === 'profits') loadProfits();
    }
    document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
    document.getElementById('mobile-menu').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('is-open'));

    async function loadOrders() {
        const requestId = ++orderRequestId;
        try {
            const params = new URLSearchParams();
            const number = document.getElementById('order-number-filter').value.trim();
            const dateFrom = document.getElementById('order-date-from').value;
            const dateTo = document.getElementById('order-date-to').value;
            if (activeFilter === 'invoices-voided') {
                params.set('invoice_status', 'voided');
            } else if (activeFilter !== 'all') {
                params.set('status', activeFilter);
            }
            if (number) params.set('number', number);
            if (dateFrom) params.set('date_from', dateFrom);
            if (dateTo) params.set('date_to', dateTo);
            params.set('page', String(orderPage));
            const query = params.toString();
            const data = await window.app.request(`/api/orders/${query ? `?${query}` : ''}`, {cache: 'no-store'});
            if (requestId !== orderRequestId) return;
            orders = data.orders;
            orderPagination = data.pagination;
            orderPage = data.pagination.page;
            renderOverview(data.summary);
            renderOrders();
            renderOrderPagination();
            return true;
        } catch (error) {
            if (requestId === orderRequestId) window.app.toast(error.message);
            return false;
        }
    }

    async function loadKitchenOrders() {
        const requestId = ++kitchenRequestId;
        try {
            const data = await window.app.request('/api/orders/?scope=active');
            if (requestId !== kitchenRequestId) return;
            kitchenOrders = data.orders;
            renderKitchen();
            return true;
        } catch (error) {
            if (requestId === kitchenRequestId) window.app.toast(error.message);
            return false;
        }
    }

    async function refreshOperationalViews(manual = false) {
        const refreshButton = document.getElementById('refresh-orders');
        if (manual) {
            refreshButton.disabled = true;
            refreshButton.textContent = '↻ Actualizando...';
        }
        const results = await Promise.all([loadOrders(), loadKitchenOrders()]);
        if (manual) {
            refreshButton.textContent = results.every(Boolean) ? '✓ Actualizado' : '↻ Reintentar';
            window.setTimeout(() => {
                refreshButton.disabled = false;
                refreshButton.textContent = '↻ Actualizar';
            }, 1200);
        }
    }

    async function loadProducts() {
        try {
            const data = await window.app.request('/api/products/');
            products = data.products;
            productCategories = data.categories;
            const categoryFilter = document.getElementById('product-category-filter');
            const selectedCategory = categoryFilter.value;
            categoryFilter.innerHTML = '<option value="">Todas las categorías</option>' +
                productCategories.map(category => `<option value="${category.id}">${window.app.escape(category.name)}${category.active ? '' : ' (inactiva)'}</option>`).join('');
            if (productCategories.some(category => String(category.id) === selectedCategory)) {
                categoryFilter.value = selectedCategory;
            }
            const categorySelect = document.querySelector('#product-form [name="category_id"]');
            categorySelect.innerHTML = productCategories.map(category => `<option value="${category.id}">${window.app.escape(category.name)}${category.active ? '' : ' (inactiva)'}</option>`).join('');
            document.getElementById('product-form-message').innerHTML = productCategories.length
                ? ''
                : 'Primero crea una categoría desde <a href="/django-admin/orders/category/add/" target="_blank">Categorías</a>.';
            document.querySelector('#product-form [type="submit"]').disabled = productCategories.length === 0;
            renderProducts();
        } catch (error) {
            document.getElementById('products-list').innerHTML = `<tr class="product-empty-row"><td colspan="7" class="empty-row">${window.app.escape(error.message)}</td></tr>`;
        }
    }

    function renderProducts() {
        const query = document.getElementById('product-search').value.trim().toLocaleLowerCase();
        const selectedCategory = document.getElementById('product-category-filter').value;
        const filtered = products.filter(product =>
            (!selectedCategory || String(product.category_id) === selectedCategory) &&
            `${product.name} ${product.description} ${product.category_name}`.toLocaleLowerCase().includes(query)
        );
        document.getElementById('product-count').textContent = `${filtered.length} de ${products.length} productos`;
        const groupedProducts = productCategories.map(category => ({
            category,
            products: filtered.filter(product => String(product.category_id) === String(category.id)),
        })).filter(group => group.products.length);
        const groupedRows = groupedProducts.map(({category, products: categoryProducts}) => {
            const productRows = categoryProducts.map(product => `
                <tr>
                    <td data-label="Producto"><div class="product-name-cell"><strong>${window.app.escape(product.name)}${product.featured ? ' · Destacado' : ''}</strong><small>${window.app.escape(product.description || 'Sin descripción')}</small></div></td>
                    <td data-label="Categoría">${window.app.escape(product.category_name)}</td>
                    <td data-label="Precio"><strong>${window.app.money(product.price)}</strong></td>
                    <td data-label="Estado"><span class="status-chip ${product.available ? 'status-ready' : 'status-cancelled'}">${product.available ? 'Disponible' : 'Agotado'}</span></td>
                    <td data-label="Existencias">${product.stock_tracked ? (product.stock_quantity === null ? 'Por configurar' : product.stock_quantity) : 'Sin control'}</td>
                    <td data-label="Ventas">${product.sold_count}</td>
                    <td data-label="Acciones"><div class="product-row-actions"><button class="small-button" type="button" data-product-edit="${product.id}">Editar</button><button class="small-button" type="button" data-product-toggle="${product.id}">${product.available ? 'Marcar agotado' : 'Volver a ofrecer'}</button><button class="small-button product-delete-button" type="button" data-product-delete="${product.id}">Eliminar</button></div></td>
                </tr>`).join('');
            return `
                <tr class="product-category-row"><td colspan="7"><div class="product-category-heading"><strong>${window.app.escape(category.name)}</strong><span>${categoryProducts.length} producto${categoryProducts.length === 1 ? '' : 's'}${category.active ? '' : ' · Categoría inactiva'}</span></div></td></tr>
                ${productRows}`;
        }).join('');
        document.getElementById('products-list').innerHTML = groupedRows ||
            '<tr class="product-empty-row"><td colspan="7" class="empty-row">No se encontraron productos.</td></tr>';
    }

    function openProductDialog(product = null) {
        const form = document.getElementById('product-form');
        form.reset();
        form.dataset.productId = product ? product.id : '';
        document.getElementById('product-dialog-title').textContent = product ? 'Editar producto' : 'Agregar producto';
        document.getElementById('product-form-message').innerHTML = productCategories.length
            ? ''
            : 'Primero crea una categoría desde <a href="/django-admin/orders/category/add/" target="_blank">Categorías</a>.';
        if (product) {
            form.elements.name.value = product.name;
            form.elements.description.value = product.description;
            form.elements.category_id.value = String(product.category_id);
            form.elements.price.value = product.price;
            form.elements.available.checked = product.available;
            form.elements.featured.checked = product.featured;
            form.elements.stock_tracked.checked = product.stock_tracked;
            form.elements.stock_quantity.value = product.stock_quantity ?? '';
        } else {
            form.elements.available.checked = true;
            const selectedCategory = productCategories.find(
                category => String(category.id) === form.elements.category_id.value,
            );
            form.elements.stock_tracked.checked = Boolean(
                selectedCategory && /bebida/i.test(selectedCategory.name),
            );
        }
        updateStockFields();
        document.getElementById('product-dialog').showModal();
    }

    function updateStockFields() {
        const form = document.getElementById('product-form');
        const selectedCategory = productCategories.find(
            category => String(category.id) === form.elements.category_id.value,
        );
        const isBeverage = Boolean(
            selectedCategory && /bebida/i.test(selectedCategory.name),
        );
        const stockSwitch = document.getElementById('stock-tracked-field');
        if (isBeverage) {
            form.elements.stock_tracked.checked = true;
            form.elements.stock_tracked.disabled = true;
        } else {
            form.elements.stock_tracked.disabled = false;
        }
        stockSwitch.hidden = isBeverage;
        const isTracked = isBeverage || form.elements.stock_tracked.checked;
        const quantityField = document.getElementById('stock-quantity-field');
        quantityField.hidden = !isTracked;
        form.elements.stock_quantity.required = isTracked;
    }

    document.getElementById('add-product-button').addEventListener('click', () => openProductDialog());
    document.querySelector('#product-form [name="stock_tracked"]').addEventListener('change', updateStockFields);
    document.querySelector('#product-form [name="category_id"]').addEventListener('change', updateStockFields);
    document.getElementById('product-search').addEventListener('input', renderProducts);
    document.getElementById('product-category-filter').addEventListener('change', renderProducts);
    document.getElementById('products-list').addEventListener('click', async event => {
        const edit = event.target.closest('[data-product-edit]');
        const toggle = event.target.closest('[data-product-toggle]');
        const remove = event.target.closest('[data-product-delete]');
        if (edit) {
            const product = products.find(
                item => item.id === Number(edit.dataset.productEdit),
            );
            if (!product) {
                window.app.toast('No se encontró el producto. Actualizando la lista...');
                await loadProducts();
                return;
            }
            openProductDialog(product);
        }
        if (toggle) {
            const product = products.find(item => item.id === Number(toggle.dataset.productToggle));
            try {
                await window.app.request(`/api/products/${product.id}/`, {method: 'PATCH', body: JSON.stringify({available: !product.available})});
                window.app.toast(product.available ? 'Producto marcado como agotado' : 'Producto disponible en la carta');
                await loadProducts();
            } catch (error) { window.app.toast(error.message); }
        }
        if (remove) {
            const product = products.find(item => item.id === Number(remove.dataset.productDelete));
            const dialog = document.getElementById('product-delete-dialog');
            dialog.dataset.productId = product.id;
            document.getElementById('product-delete-eyebrow').textContent = product.sold_count
                ? 'CONSERVAR HISTORIAL DE VENTAS'
                : 'CONFIRMAR ELIMINACIÓN';
            document.getElementById('product-delete-title').textContent = product.sold_count
                ? 'Retirar producto de la carta'
                : 'Eliminar producto';
            document.getElementById('product-delete-message').textContent = product.sold_count
                ? `“${product.name}” tiene pedidos históricos. Se retirará de la carta y conservará esos registros.`
                : `¿Eliminar “${product.name}”? Esta acción no se puede deshacer.`;
            document.getElementById('confirm-product-delete').textContent = product.sold_count
                ? 'Retirar de la carta'
                : 'Eliminar definitivamente';
            dialog.showModal();
        }
    });

    document.getElementById('product-form').addEventListener('submit', async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const submit = form.querySelector('[type="submit"]');
        const selectedCategory = productCategories.find(
            category => String(category.id) === form.elements.category_id.value,
        );
        const tracksStock = form.elements.stock_tracked.checked ||
            Boolean(selectedCategory && /bebida/i.test(selectedCategory.name));
        const payload = {
            name: form.elements.name.value.trim(),
            category_id: Number(form.elements.category_id.value),
            description: form.elements.description.value.trim(),
            price: form.elements.price.value,
            available: form.elements.available.checked,
            featured: form.elements.featured.checked,
            stock_tracked: tracksStock,
            ...(tracksStock ? {stock_quantity: form.elements.stock_quantity.value} : {}),
        };
        submit.disabled = true;
        try {
            const productId = form.dataset.productId;
            await window.app.request(productId ? `/api/products/${productId}/` : '/api/products/', {
                method: productId ? 'PATCH' : 'POST', body: JSON.stringify(payload),
            });
            document.getElementById('product-dialog').close();
            window.app.toast(productId ? 'Producto actualizado' : 'Producto agregado a la carta');
            await loadProducts();
        } catch (error) {
            document.getElementById('product-form-message').textContent = error.message;
        } finally { submit.disabled = false; }
    });
    document.querySelectorAll('[data-product-cancel]').forEach(button => button.addEventListener('click', () => document.getElementById('product-dialog').close()));
    document.querySelectorAll('[data-product-delete-cancel]').forEach(button => button.addEventListener('click', () => document.getElementById('product-delete-dialog').close()));
    document.getElementById('confirm-product-delete').addEventListener('click', async () => {
        const dialog = document.getElementById('product-delete-dialog');
        try {
            const result = await window.app.request(`/api/products/${dialog.dataset.productId}/`, {method: 'DELETE'});
            dialog.close();
            window.app.toast(result.archived ? 'Producto retirado; se conservaron sus ventas' : 'Producto eliminado');
            await loadProducts();
        } catch (error) { window.app.toast(error.message); }
    });
    function orderActions(order, kitchen = false) {
        const actions = [];
        if (order.status !== 'cancelled') actions.push(`<button class="small-button" data-kitchen-print="${order.id}">Imprimir cocina</button>`);
        if (order.invoice?.status === 'active') {
            actions.push(`<button class="small-button" data-sale-print="${order.id}">Imprimir comprobante</button>`);
            if (!kitchen) actions.push(`<button class="small-button" data-invoice-cancel-open="${order.id}">Anular comprobante</button>`);
        } else if (order.invoice?.status === 'voided') {
            actions.push(`<span class="payment-chip" title="${window.app.escape(order.invoice.void_reason || '')}">Anulado · sin reembolso</span>`);
        }
        if (order.status === 'received') actions.push(`<button class="small-button confirm" data-status="preparing" data-id="${order.id}">Empezar preparación</button>`);
        if (order.status === 'preparing') actions.push(`<button class="small-button confirm" data-status="ready" data-id="${order.id}">Marcar preparado</button>`);
        if (order.status === 'ready') actions.push(`<button class="small-button confirm" data-status="delivered" data-id="${order.id}">Entregar pedido</button>`);
        if (!kitchen && order.status !== 'cancelled' && order.payment_status !== 'paid') actions.push(`<button class="small-button" data-pay-open="${order.id}">Registrar pago</button>`);
        if (!kitchen && order.status === 'received' && order.payment_status === 'pending') {
            actions.push(`<button class="small-button" data-order-edit="${order.id}">Editar productos</button>`);
            actions.push(`<button class="small-button" data-order-delete="${order.id}">Eliminar pedido</button>`);
        }
        if (!kitchen && !['delivered', 'cancelled'].includes(order.status)) actions.push(`<button class="small-button" data-status="cancelled" data-id="${order.id}">Cancelar</button>`);
        return actions.join('');
    }

    function renderOrderEditItems() {
        const list = document.getElementById('order-edit-items');
        const existingRows = orderBeingEdited.items.map(item => `
            <div class="order-edit-row" data-existing-item="${item.id}">
                <strong>${window.app.escape(item.name)}</strong>
                <label class="field-label">Cantidad<input data-item-quantity type="number" min="1" max="30" value="${item.quantity}" required></label>
                <label class="field-label">Instrucciones<input data-item-instructions maxlength="180" value="${window.app.escape(item.instructions || '')}"></label>
                <button class="small-button" type="button" data-remove-order-item>Quitar</button>
            </div>`).join('');
        const newRows = [...list.querySelectorAll('[data-new-item]')].map(row => row.outerHTML).join('');
        list.innerHTML = existingRows + newRows;
    }

    function addNewOrderItemRow() {
        const list = document.getElementById('order-edit-items');
        const options = products.filter(product => product.available)
            .map(product => `<option value="${product.id}">${window.app.escape(product.name)} · ${window.app.money(product.price)}</option>`)
            .join('');
        if (!options) {
            window.app.toast('No hay productos disponibles para agregar.');
            return;
        }
        const row = document.createElement('div');
        row.className = 'order-edit-row';
        row.dataset.newItem = '';
        row.innerHTML = `<label class="field-label">Producto<select data-new-product required>${options}</select></label>
            <label class="field-label">Cantidad<input data-new-quantity type="number" min="1" max="30" value="1" required></label>
            <label class="field-label">Instrucciones<input data-new-instructions maxlength="180"></label>
            <button class="small-button" type="button" data-remove-order-item>Quitar</button>`;
        list.append(row);
    }
    function renderOverview(summary) {
        if (!summary) return;
        document.getElementById('metric-sales').textContent = window.app.money(summary.month_sales_total);
        document.getElementById('metric-sales-note').textContent =
            `${summary.month_paid_order_count} cobros pagados este mes`;
        document.getElementById('metric-orders').textContent = summary.order_count;
        document.getElementById('metric-pending').textContent = `${summary.pending_count} pendientes de pago`;
        document.getElementById('metric-active').textContent = summary.active_count;
        document.getElementById('nav-order-count').textContent = summary.active_count;
        document.getElementById('metric-voided-invoices').textContent = summary.voided_invoice_count;
        document.getElementById('metric-voided-total').textContent =
            `${window.app.money(summary.voided_invoice_total)} · cobrados, sin reembolso`;
        document.getElementById('recent-orders').innerHTML = summary.recent_orders.map(order => `
            <tr>
                <td><span class="order-ref">#${window.app.escape(order.number)}</span></td>
                <td>${window.app.escape(order.customer_name)}</td>
                <td>${window.app.escape(order.kind_label)}</td>
                <td><span class="status-chip ${statusClass(order.status)}">${order.status_label}</span></td>
                <td><b>${window.app.money(order.total)}</b></td>
                <td>${shortTime(order.created_at)}</td>
                <td><button class="small-button" data-jump="orders">Abrir</button></td>
            </tr>`).join('') || '<tr><td colspan="7" class="empty-row">Todavía no hay pedidos.</td></tr>';
        const requestId = ++cashMetricRequestId;
        window.app.request('/api/cash/').then(data => {
            if (requestId !== cashMetricRequestId) return;
            currentCash = data.session;
            document.getElementById('metric-cash').textContent = currentCash ? window.app.money(currentCash.opening_amount) : 'Cerrada';
            document.getElementById('metric-cash-note').textContent = currentCash ? 'Turno en curso' : 'Abre tu turno para empezar';
        }).catch(error => {
            if (requestId === cashMetricRequestId) window.app.toast(error.message);
        });
    }

    function renderOrderCard(order) {
        const items = order.items.map(item => `
            ${item.quantity} × ${window.app.escape(item.name)}
            ${item.instructions ? `<small>(${window.app.escape(item.instructions)})</small>` : ''}`
        ).join('<br>');
        const cancellationReason = order.status === 'cancelled'
            ? `<br><small><strong>Motivo de cancelación:</strong> ${window.app.escape(order.cancellation_reason || 'No registrado.')}</small>`
            : '';
        const invoiceDetails = order.invoice?.status === 'voided'
            ? `<br><small><strong>Comprobante ${window.app.escape(order.invoice.number)} anulado:</strong> ${window.app.escape(order.invoice.void_reason || 'Motivo no registrado.')} · No se registró reembolso.${order.invoice.voided_at ? ` · ${shortDateTime(order.invoice.voided_at)}` : ''}</small>`
            : '';
        const cashDetails = order.invoice?.cash_received !== null && order.invoice?.cash_received !== undefined
            ? `<br><small>Efectivo recibido: ${window.app.money(order.invoice.cash_received)} · Vuelto: ${window.app.money(order.invoice.change_given)}</small>`
            : '';
        return `
            <article class="order-card">
                <div class="order-card-main">
                    <strong><span class="order-ref">#${window.app.escape(order.number)}</span> · ${window.app.escape(order.customer_name)}</strong>
                    <small>${window.app.escape(order.kind_label)}${order.table_number ? ` · Mesa ${window.app.escape(order.table_number)}` : ''}${order.address ? ` · ${window.app.escape(order.address)}` : ''} · ${shortTime(order.created_at)}</small>
                    <span><span class="status-chip ${statusClass(order.status)}">${order.status_label}</span> <span class="payment-chip ${order.payment_status === 'paid' ? 'payment-paid' : ''}">${order.payment_status_label}</span></span>
                </div>
                <div class="order-card-items">
                    ${items}${order.note ? `<br><small>Nota: ${window.app.escape(order.note)}</small>` : ''}
                    ${cancellationReason}${invoiceDetails}${cashDetails}
                    <br><b>${window.app.money(order.total)} · ${window.app.escape(order.payment_method_label)}</b>
                </div>
                <div class="order-card-actions">${orderActions(order)}</div>
            </article>`;
    }

    function renderOrders() {
        document.getElementById('orders-list').innerHTML =
            orders.map(renderOrderCard).join('') ||
            '<div class="empty-row">No hay pedidos en esta vista.</div>';
    }

    function renderOrderPagination() {
        const pagination = document.getElementById('orders-pagination');
        if (!orderPagination.total) {
            pagination.innerHTML = '';
            return;
        }
        pagination.innerHTML = `
            <button class="small-button" type="button" data-order-page="${orderPagination.page - 1}" ${orderPagination.page <= 1 ? 'disabled' : ''}>Anterior</button>
            <span>Página ${orderPagination.page} de ${orderPagination.pages} · ${orderPagination.total} pedidos</span>
            <button class="small-button" type="button" data-order-page="${orderPagination.page + 1}" ${orderPagination.page >= orderPagination.pages ? 'disabled' : ''}>Siguiente</button>`;
    }

    function renderKitchen() {
        const columns = [['received', 'Recibidos'], ['preparing', 'En preparación'], ['ready', 'Preparados']];
        document.getElementById('kitchen-board').innerHTML = columns.map(([status, label]) => {
            const items = kitchenOrders.filter(order => order.status === status);
            const tickets = items.map(order => {
                const minutes = Math.max(
                    0,
                    Math.floor((Date.now() - new Date(order.status_since).getTime()) / 60000),
                );
                const lateAfter = {received: 15, preparing: 30, ready: 10}[status];
                const overdue = minutes >= lateAfter;
                return `
                    <article class="kitchen-ticket ${status === 'ready' ? 'ready' : ''} ${overdue ? 'overdue' : ''}">
                        <div class="ticket-head"><span>#${window.app.escape(order.number)}</span><small>${overdue ? 'Demorado · ' : ''}${minutes} min · ${shortTime(order.created_at)}</small></div>
                        <div class="ticket-meta">${window.app.escape(order.customer_name)} · ${window.app.escape(order.kind_label)}${order.table_number ? ` · Mesa ${window.app.escape(order.table_number)}` : ''}</div>
                        <div class="ticket-items">${order.items.map(item => `<div><b>${item.quantity}×</b>${window.app.escape(item.name)}</div>${item.instructions ? `<small>${window.app.escape(item.instructions)}</small>` : ''}`).join('')}${order.note ? `<small>Nota: ${window.app.escape(order.note)}</small>` : ''}</div>
                        ${orderActions(order, true)}
                    </article>`;
            }).join('');
            return `<section class="kitchen-column"><h3>${label}<b>${items.length}</b></h3>${tickets || '<div class="empty-state">Sin comandas</div>'}</section>`;
        }).join('');
    }
    document.getElementById('order-filters').addEventListener('click', event => {
        const button = event.target.closest('[data-filter]');
        if (!button) return;
        activeFilter = button.dataset.filter;
        orderPage = 1;
        document.querySelectorAll('.filter-tab').forEach(tab => {
            const selected = tab === button;
            tab.classList.toggle('is-active', selected);
            tab.setAttribute('aria-pressed', String(selected));
        });
        if (activeFilter === 'invoices-voided') {
            document.getElementById('order-date-from').value = '';
            document.getElementById('order-date-to').value = '';
        }
        loadOrders();
    });
    let orderSearchTimer;
    document.getElementById('order-number-filter').addEventListener('input', () => {
        orderPage = 1;
        clearTimeout(orderSearchTimer);
        orderSearchTimer = setTimeout(loadOrders, 250);
    });
    ['order-date-from', 'order-date-to'].forEach(id =>
        document.getElementById(id).addEventListener('change', () => {
            orderPage = 1;
            loadOrders();
        })
    );
    document.getElementById('clear-order-filters').addEventListener('click', () => {
        document.getElementById('order-number-filter').value = '';
        document.getElementById('order-date-from').value = '';
        document.getElementById('order-date-to').value = '';
        activeFilter = 'all';
        orderPage = 1;
        document.querySelectorAll('.filter-tab').forEach(tab => {
            const selected = tab.dataset.filter === 'all';
            tab.classList.toggle('is-active', selected);
            tab.setAttribute('aria-pressed', String(selected));
        });
        loadOrders();
    });
    document.getElementById('refresh-orders').addEventListener('click', () => refreshOperationalViews(true));
    document.getElementById('orders-pagination').addEventListener('click', event => {
        const button = event.target.closest('[data-order-page]');
        if (!button || button.disabled) return;
        orderPage = Number(button.dataset.orderPage);
        loadOrders();
    });

    function findOrder(orderId) {
        return [...orders, ...kitchenOrders].find(
            order => String(order.id) === String(orderId),
        );
    }

    function updateCashPaymentFields() {
        const form = document.getElementById('payment-form');
        const isCash = form.elements.payment_method.value === 'cash';
        const cashField = document.getElementById('cash-received-field');
        const cashInput = form.elements.cash_received;
        const changePreview = document.getElementById('cash-change-preview');
        cashField.hidden = !isCash;
        changePreview.hidden = !isCash;
        cashInput.required = isCash;
        if (!isCash) return;

        const totalCents = Math.round(Number(form.dataset.orderTotal) * 100);
        const receivedCents = Math.round(Number(cashInput.value) * 100);
        const hasValue = cashInput.value.trim() !== '' && Number.isFinite(receivedCents);
        const enoughCash = hasValue && receivedCents >= totalCents;
        changePreview.classList.toggle('is-insufficient', hasValue && !enoughCash);
        changePreview.textContent = hasValue
            ? enoughCash
                ? `Vuelto a entregar: ${window.app.money((receivedCents - totalCents) / 100)}`
                : `Faltan: ${window.app.money((totalCents - receivedCents) / 100)}`
            : 'Ingresa el efectivo recibido para calcular el vuelto.';
    }

    document.getElementById('payment-form').elements.payment_method.addEventListener(
        'change',
        updateCashPaymentFields,
    );
    document.getElementById('payment-form').elements.cash_received.addEventListener(
        'input',
        updateCashPaymentFields,
    );
    document.body.addEventListener('click', async event => {
        const jumpButton = event.target.closest('[data-jump]');
        const statusButton = event.target.closest('[data-status]');
        const payOpenButton = event.target.closest('[data-pay-open]');
        const payCancelButton = event.target.closest('[data-pay-cancel]');
        const kitchenPrintButton = event.target.closest('[data-kitchen-print]');
        const salePrintButton = event.target.closest('[data-sale-print]');
        const editOrderButton = event.target.closest('[data-order-edit]');
        const deleteOrderButton = event.target.closest('[data-order-delete]');
        const removeOrderItemButton = event.target.closest('[data-remove-order-item]');
        const addOrderItemButton = event.target.closest('#add-order-item');
        const invoiceCancelButton = event.target.closest('[data-invoice-cancel-open]');
        const receiptCloseButton = event.target.closest('[data-close-paid-receipt]');
        const receiptPrintButton = event.target.closest('#print-paid-receipt');
        if (jumpButton) setView(jumpButton.dataset.jump);
        if (kitchenPrintButton) {
            const order = findOrder(kitchenPrintButton.dataset.kitchenPrint);
            if (order && !window.posReceipt.print(
                order,
                'kitchen',
                document.getElementById('paid-receipt-dialog').dataset.businessName,
            )) {
                window.app.toast('Permite las ventanas emergentes para imprimir la comanda.');
            }
        }
        if (salePrintButton) {
            const order = orders.find(item => String(item.id) === salePrintButton.dataset.salePrint);
            if (order && !window.posReceipt.print(
                order,
                'sale',
                document.getElementById('paid-receipt-dialog').dataset.businessName,
            )) {
                window.app.toast('Permite las ventanas emergentes para imprimir el comprobante.');
            }
        }
        if (editOrderButton) {
            orderBeingEdited = orders.find(item => String(item.id) === editOrderButton.dataset.orderEdit);
            if (!orderBeingEdited) return;
            try {
                if (!products.length) products = (await window.app.request('/api/products/')).products;
                document.getElementById('order-edit-items').innerHTML = '';
                renderOrderEditItems();
                document.getElementById('order-edit-dialog').showModal();
            } catch (error) {
                window.app.toast(error.message);
            }
        }
        if (addOrderItemButton) addNewOrderItemRow();
        if (removeOrderItemButton) removeOrderItemButton.closest('.order-edit-row').remove();
        if (deleteOrderButton) {
            if (!window.confirm('¿Eliminar por completo este pedido pendiente? Esta acción no se puede deshacer.')) return;
            deleteOrderButton.disabled = true;
            try {
                await window.app.request(`/api/orders/${deleteOrderButton.dataset.orderDelete}/`, {method: 'DELETE'});
                window.app.toast('Pedido eliminado');
                await refreshOperationalViews();
            } catch (error) {
                window.app.toast(error.message);
            } finally {
                deleteOrderButton.disabled = false;
            }
        }
        if (invoiceCancelButton) {
            const order = findOrder(invoiceCancelButton.dataset.invoiceCancelOpen);
            if (!order) return;
            const form = document.getElementById('invoice-cancellation-form');
            form.dataset.orderId = order.id;
            document.getElementById('invoice-cancellation-reference').textContent = `Comprobante ${order.invoice.number} · Pedido #${order.number}`;
            form.elements.reason.value = '';
            document.getElementById('invoice-cancellation-message').textContent = '';
            document.getElementById('invoice-cancellation-dialog').showModal();
        }
        if (receiptCloseButton) {
            document.getElementById('paid-receipt-dialog').close();
        }
        if (receiptPrintButton && paidReceiptOrder) {
            if (!window.posReceipt.print(
                paidReceiptOrder,
                'sale',
                document.getElementById('paid-receipt-dialog').dataset.businessName,
            )) {
                window.app.toast('Permite las ventanas emergentes para imprimir el recibo.');
            } else {
                document.getElementById('paid-receipt-dialog').close();
            }
        }
        if (payOpenButton) {
            const order = orders.find(item => String(item.id) === payOpenButton.dataset.payOpen);
            if (!order) return;
            const dialog = document.getElementById('payment-dialog');
            const form = document.getElementById('payment-form');
            form.dataset.paymentForm = order.id;
            form.dataset.orderTotal = order.total;
            form.elements.payment_method.value = order.payment_method;
            form.elements.cash_received.value = '';
            form.elements.cash_received.min = order.total;
            document.getElementById('payment-order-total').textContent = window.app.money(order.total);
            updateCashPaymentFields();
            dialog.showModal();
        }
        if (payCancelButton) {
            document.getElementById('payment-dialog').close();
        }
        if (event.target.closest('[data-order-edit-cancel]')) {
            document.getElementById('order-edit-dialog').close();
        }
        if (event.target.closest('[data-invoice-cancel-cancel]')) {
            document.getElementById('invoice-cancellation-dialog').close();
        }
        if (statusButton) {
            let reason = '';
            if (statusButton.dataset.status === 'cancelled') {
                reason = window.prompt('Indica el motivo para cancelar este pedido:') || '';
                if (!reason.trim()) {
                    window.app.toast('La cancelación requiere un motivo.');
                    return;
                }
            }
            statusButton.disabled = true;
            try {
                await window.app.request(`/api/orders/${statusButton.dataset.id}/status/`, {
                    method: 'POST',
                    body: JSON.stringify({status: statusButton.dataset.status, reason}),
                });
                await refreshOperationalViews();
                window.app.toast('Estado actualizado');
            }
            catch (error) { window.app.toast(error.message); }
        }
    });
    document.body.addEventListener('submit', async event => {
        const editForm = event.target.closest('#order-edit-form');
        const cancellationForm = event.target.closest('#invoice-cancellation-form');
        if (!editForm && !cancellationForm) return;
        event.preventDefault();
        const form = editForm || cancellationForm;
        const submitButton = form.querySelector('[type="submit"]');
        submitButton.disabled = true;
        try {
            if (editForm) {
                const items = [
                    ...editForm.querySelectorAll('[data-existing-item]'),
                ].map(row => ({
                    item_id: Number(row.dataset.existingItem),
                    quantity: Number(row.querySelector('[data-item-quantity]').value),
                    instructions: row.querySelector('[data-item-instructions]').value,
                }));
                items.push(...[...editForm.querySelectorAll('[data-new-item]')].map(row => ({
                    product_id: Number(row.querySelector('[data-new-product]').value),
                    quantity: Number(row.querySelector('[data-new-quantity]').value),
                    instructions: row.querySelector('[data-new-instructions]').value,
                })));
                await window.app.request(`/api/orders/${orderBeingEdited.id}/`, {
                    method: 'PATCH',
                    body: JSON.stringify({items}),
                });
                document.getElementById('order-edit-dialog').close();
                window.app.toast('Pedido actualizado');
            } else {
                const result = await window.app.request(`/api/orders/${form.dataset.orderId}/invoice-cancellation/`, {
                    method: 'POST', body: JSON.stringify({reason: form.elements.reason.value}),
                });
                document.getElementById('invoice-cancellation-dialog').close();
                window.app.toast(`Comprobante ${result.invoice_number} anulado`);
            }
            await refreshOperationalViews();
        } catch (error) {
            if (cancellationForm) {
                document.getElementById('invoice-cancellation-message').textContent = error.message;
            }
            window.app.toast(error.message);
        } finally {
            submitButton.disabled = false;
        }
    });
    document.body.addEventListener('submit', async event => {
        const paymentForm = event.target.closest('[data-payment-form]');
        if (!paymentForm) return;
        event.preventDefault();
        const submitButton = paymentForm.querySelector('[type="submit"]');
        submitButton.disabled = true;
        try {
            const paymentMethod = new FormData(paymentForm).get('payment_method');
            const paymentData = {payment_method: paymentMethod, paid: true};
            if (paymentMethod === 'cash') {
                paymentData.cash_received = paymentForm.elements.cash_received.value;
            }
            const result = await window.app.request(`/api/orders/${paymentForm.dataset.paymentForm}/payment/`, {
                method: 'POST', body: JSON.stringify(paymentData),
            });
            document.getElementById('payment-dialog').close();
            await refreshOperationalViews();
            paidReceiptOrder = result.order;
            document.getElementById('paid-receipt-preview').innerHTML = window.posReceipt.render(
                paidReceiptOrder,
                'sale',
                document.getElementById('paid-receipt-dialog').dataset.businessName,
            );
            document.getElementById('paid-receipt-dialog').showModal();
        } catch (error) {
            window.app.toast(error.message);
        } finally {
            submitButton.disabled = false;
        }
    });

    async function loadCash() {
        const content = document.getElementById('cash-content');
        try {
            const data = await window.app.request('/api/cash/');
            currentCash = data.session;
            cashHistory = data.history;
            document.getElementById('cash-status-chip').textContent = currentCash ? 'Turno abierto' : 'Caja cerrada';
            document.getElementById('cash-status-chip').className = `status-chip ${currentCash ? 'status-ready' : ''}`;
            document.getElementById('cash-history').innerHTML = data.history.map(session => {
                const breakdown = Object.entries(session.counted_denominations || {}).filter(([, count]) => count > 0)
                    .map(([denomination, count]) => `${count} × ${window.app.money(denomination)}`).join(' · ') || 'Sin efectivo contado';
                const reconciliation = session.reconciliation;
                const overall = reconciliation.complete
                    ? `${window.app.escape(reconciliation.status === 'surplus' ? 'Sobrante' : reconciliation.status === 'shortage' ? 'Faltante' : 'Cuadra')} ${formatSignedMoney(reconciliation.difference)}`
                    : 'Conciliación pendiente: cierre anterior sin importes electrónicos verificados.';
                const rows = reconciliation.methods.map(method => {
                    const variance = method.difference === null ? 'Sin verificar' : formatSignedMoney(method.difference);
                    return `<div class="cash-reconcile-item"><b>${window.app.escape(method.method)}</b>: esperado ${window.app.money(method.expected)} · comprobado ${method.actual === null ? 'sin dato' : window.app.money(method.actual)} · ${window.app.escape(variance)}<small>${window.app.escape(method.reason)}</small></div>`;
                }).join('');
                const pendingMethods = reconciliation.methods.filter(method => method.method !== 'Efectivo' && method.actual === null && Number(method.expected) > 0);
                const historicalForm = pendingMethods.length ? `<form class="historical-reconcile-form" data-historical-reconciliation="${session.id}"><p>Completa los importes brutos de los comprobantes de este cierre anterior.</p>${pendingMethods.map(method => `<label class="verification-row"><span>${window.app.escape(method.method)}</span><strong>${window.app.money(method.expected)}</strong><input aria-label="Valor comprobado de ${window.app.escape(method.method)}" data-historical-method="${window.app.escape(method.method)}" type="number" min="0" step="1" required inputmode="numeric"><span></span></label>`).join('')}<button class="small-button confirm" type="submit">Guardar conciliación</button></form>` : '';
                const audit = session.reconciled_at ? `<small class="reconciliation-audit">Verificado por ${window.app.escape(session.reconciled_by || 'administrador')} · ${new Intl.DateTimeFormat('es', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(session.reconciled_at))}</small>` : '';
                return `<tr><td>${new Intl.DateTimeFormat('es', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(session.opened_at))}</td><td>${window.app.money(session.opening_amount)}</td><td>${window.app.money(session.counted_amount)}</td><td><b>${window.app.money(session.difference)}</b></td><td>${window.app.escape(breakdown)}</td><td><details><summary>${overall}</summary>${rows}${historicalForm}${audit}</details></td><td><button class="small-button" type="button" data-print-cash-close="${session.id}">Imprimir</button></td></tr>`;
            }).join('') || '<tr><td colspan="7" class="empty-row">Sin cierres registrados.</td></tr>';
            if (!currentCash) {
                content.innerHTML = '<form id="open-cash-form" class="cash-open-panel"><p>Abre un turno con el fondo inicial en efectivo disponible en la caja.</p><label class="field-label">Fondo inicial<input name="amount" type="number" min="0" step="0.01" required value="0"></label><button class="button button-primary">Abrir caja →</button></form>';
            } else {
                const methods = Object.entries(currentCash.payment_totals);
                const legacyMethods = methods.map(([label]) => label).filter(label => label !== 'Efectivo' && !digitalPaymentMethods.some(method => method.label === label));
                const verifyMethods = [...digitalPaymentMethods, ...legacyMethods.map((label, index) => ({label, name: `verified-legacy-${index}`}))];
                const expectedSalesTotal = methods.reduce((sum, [, value]) => sum + Number(value), 0);
                const verificationRows = verifyMethods.map(method => {
                    const expected = Number(currentCash.payment_totals[method.label] || 0);
                    return `<label class="verification-row"><span>${window.app.escape(method.label)}</span><strong>${window.app.money(expected)}</strong><input aria-label="Valor comprobado de ${window.app.escape(method.label)}" name="${method.name}" data-verified-method="${window.app.escape(method.label)}" data-expected="${expected}" type="number" min="0" step="1" value="${expected === 0 ? '0' : ''}" ${expected > 0 ? 'required' : ''} inputmode="numeric"><output data-method-difference="${window.app.escape(method.label)}">${expected === 0 ? window.app.money(0) : 'Pendiente'}</output></label>`;
                }).join('');
                const denominationRows = values => values.map(value => `<label class="denomination-row"><span class="denomination-kind">${value < 2000 ? 'Moneda' : 'Billete'}</span><strong>${window.app.money(value)}</strong><input aria-label="Cantidad de ${window.app.money(value)}" name="denomination-${value}" data-denomination="${value}" type="number" min="0" step="1" value="0" inputmode="numeric" required><output data-denomination-total="${value}">${window.app.money(0)}</output></label>`).join('');
                content.innerHTML = `<div class="cash-opened-panel"><span class="eyebrow">TURNO ACTIVO</span><h2>La caja está abierta</h2><p class="muted">Apertura: ${new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(currentCash.opened_at))}</p><div class="cash-summary"><div class="cash-summary-item"><span>FONDO INICIAL</span><strong>${window.app.money(currentCash.opening_amount)}</strong></div><div class="cash-summary-item"><span>EFECTIVO ESPERADO</span><strong>${window.app.money(currentCash.expected_cash)}</strong></div><div class="cash-summary-item"><span>VENTAS EN EFECTIVO</span><strong>${window.app.money((currentCash.payment_totals || {}).Efectivo || 0)}</strong></div><div class="cash-summary-item"><span>OTROS PAGOS</span><strong>${window.app.money(methods.filter(([name]) => name !== 'Efectivo').reduce((n, [, v]) => n + Number(v), 0))}</strong></div></div><div class="cash-methods"><b>Ventas agrupadas por método de pago</b>${methods.map(([name, value]) => `<div class="cash-method-row"><span>${window.app.escape(name)}</span><strong>${window.app.money(value)}</strong></div>`).join('') || '<div class="cash-method-row"><span>Aún no hay pagos registrados</span><strong>$0</strong></div>'}</div><form id="close-cash-form" class="cash-close-form"><section class="reconciliation-entry"><div class="denomination-heading"><div><span class="eyebrow">CONCILIACIÓN DEL TURNO</span><h3>Ventas vs. valores comprobados</h3></div><span>Valores brutos en COP</span></div><p class="reconciliation-note">Compara Bancolombia, Nequi y tarjeta con sus comprobantes o datáfono. Registra el valor bruto de ventas, antes de descontar comisiones.</p><div class="verification-table"><div class="verification-head"><span>MEDIO</span><span>ESPERADO</span><span>COMPROBADO</span><span>DIFERENCIA</span></div><div class="verification-row"><span>Efectivo</span><strong>${window.app.money(currentCash.expected_cash)}</strong><span data-cash-actual>${window.app.money(0)}</span><output data-cash-difference>Pendiente de conteo</output></div>${verificationRows}<div class="verification-total"><strong>Total facturado</strong><strong id="reconcile-total-expected">${window.app.money(expectedSalesTotal)}</strong><strong id="reconcile-total-actual">Pendiente</strong><strong id="reconcile-total-difference">Pendiente</strong></div></div><p id="reconcile-explanation" class="reconciliation-explanation">Ingresa las cantidades de efectivo y los valores comprobados para ver si hay sobrante o faltante.</p></section><div class="denomination-counter"><div class="denomination-heading"><div><span class="eyebrow">CONTEO DE EFECTIVO</span><h3>Monedas</h3></div><span>Peso colombiano (COP)</span></div><div class="denomination-list">${denominationRows(cashDenominations.slice(0, 4))}</div><div class="denomination-heading bills-heading"><h3>Billetes</h3></div><div class="denomination-list">${denominationRows(cashDenominations.slice(4))}</div><div class="denomination-grand-total"><span>Total contado</span><strong id="counted-cash-total">${window.app.money(0)}</strong></div></div><button class="button button-primary cash-close-submit" type="submit">Cerrar y guardar turno</button></form></div>`;
                content.querySelector('.verification-total strong').textContent = 'Ventas pagadas';
                content.querySelector('.reconciliation-note').textContent = 'Compara solo los pedidos marcados como Pagado en este turno. Verifica Bancolombia, Nequi y tarjeta con el comprobante o datáfono; ingresa el valor bruto antes de comisiones.';
                updateCashReconciliationPreview();
            }
        } catch (error) { content.innerHTML = `<p class="alert-message">${window.app.escape(error.message)}</p>`; }
    }
    document.getElementById('cash-content').addEventListener('submit', async event => {
        const formElement = event.target.closest('form');
        if (!formElement) return;
        event.preventDefault();
        const form = new FormData(formElement);
        const isOpen = formElement.id === 'open-cash-form';
        const previewWindow = isOpen ? null : window.posReceipt.openCashCloseWindow();
        try {
            const body = isOpen
                ? {action: 'open', amount: form.get('amount')}
                : {
                    action: 'close',
                    denominations: Object.fromEntries(cashDenominations.map(value => [String(value), Number(form.get(`denomination-${value}`) || 0)])),
                    verified_payments: Object.fromEntries([...formElement.querySelectorAll('[data-verified-method]')].map(input => [input.dataset.verifiedMethod, input.value])),
                };
            const result = await window.app.request('/api/cash/', {method: 'POST', body: JSON.stringify(body)});
            const reconciliation = result.session.reconciliation;
            if (!isOpen) {
                const previewReady = previewWindow && window.posReceipt.writeCashClosePreview(
                    previewWindow,
                    result.session,
                    document.getElementById('paid-receipt-dialog').dataset.businessName,
                );
                if (!previewReady) {
                    window.app.toast('Cierre guardado, pero no se abrió la vista previa. Permite las ventanas emergentes o imprime desde el historial.');
                }
            }
            window.app.toast(isOpen ? 'Caja abierta' : `Cierre guardado: ${reconciliation.status === 'surplus' ? 'sobrante' : reconciliation.status === 'shortage' ? 'faltante' : 'cuadra'} ${formatSignedMoney(reconciliation.difference)}`);
            await loadCash();
        } catch (error) {
            if (previewWindow && !previewWindow.closed) previewWindow.close();
            window.app.toast(error.message);
        }
    });
    document.getElementById('cash-history').addEventListener('click', event => {
        const button = event.target.closest('[data-print-cash-close]');
        if (!button) return;
        const session = cashHistory.find(item => String(item.id) === button.dataset.printCashClose);
        if (!session) {
            window.app.toast('No se encontró la información de este cierre. Actualiza el historial e inténtalo de nuevo.');
            return;
        }
        if (!window.posReceipt.printCashClose(
            session,
            document.getElementById('paid-receipt-dialog').dataset.businessName,
        )) {
            window.app.toast('Permite las ventanas emergentes para ver el cierre.');
        }
    });
    document.getElementById('cash-history').addEventListener('submit', async event => {
        const form = event.target.closest('[data-historical-reconciliation]');
        if (!form) return;
        event.preventDefault();
        const verifiedPayments = Object.fromEntries([...form.querySelectorAll('[data-historical-method]')]
            .map(input => [input.dataset.historicalMethod, input.value]));
        try {
            const result = await window.app.request(`/api/cash/${form.dataset.historicalReconciliation}/reconcile/`, {
                method: 'POST', body: JSON.stringify({verified_payments: verifiedPayments}),
            });
            const reconciliation = result.session.reconciliation;
            window.app.toast(`Conciliación guardada: ${reconciliation.status === 'surplus' ? 'sobrante' : reconciliation.status === 'shortage' ? 'faltante' : 'cuadra'} ${formatSignedMoney(reconciliation.difference)}`);
            await loadCash();
        } catch (error) { window.app.toast(error.message); }
    });
    document.getElementById('cash-content').addEventListener('input', event => {
        const denominationInput = event.target.closest('[data-denomination]');
        const verifiedInput = event.target.closest('[data-verified-method]');
        if (denominationInput) {
            const count = Math.max(0, Math.floor(Number(denominationInput.value) || 0));
            const denomination = Number(denominationInput.dataset.denomination);
            denominationInput.value = String(count);
            document.querySelector(`[data-denomination-total="${denomination}"]`).textContent = window.app.money(denomination * count);
            const total = [...document.querySelectorAll('[data-denomination]')].reduce((sum, row) => sum + Number(row.dataset.denomination) * (Number(row.value) || 0), 0);
            document.getElementById('counted-cash-total').textContent = window.app.money(total);
        }
        if (denominationInput || verifiedInput) updateCashReconciliationPreview();
    });

    function formatSignedMoney(value) {
        const amount = Number(value || 0);
        return amount > 0 ? `+${window.app.money(amount)}` : amount < 0 ? `-${window.app.money(Math.abs(amount))}` : window.app.money(0);
    }

    function differenceExplanation(amount, complete) {
        if (!complete) return 'Conciliación pendiente: faltan valores comprobados de uno o más medios de pago.';
        if (amount > 0) return 'Sobrante: el valor contado o comprobado supera las ventas registradas. Revisa cambio no entregado, ventas sin registrar, duplicados o errores en el fondo inicial/conteo.';
        if (amount < 0) return 'Faltante: el valor contado o comprobado es menor que las ventas registradas. Revisa conteo, cambio entregado, pagos rechazados o pendientes, devoluciones y método asignado.';
        return 'Cuadra: los valores comprobados coinciden con las ventas registradas del turno.';
    }

    function updateCashReconciliationPreview() {
        const cashTotalElement = document.getElementById('counted-cash-total');
        if (!cashTotalElement || !currentCash) return;
        const cashActual = [...document.querySelectorAll('[data-denomination]')]
            .reduce((sum, input) => sum + Number(input.dataset.denomination) * (Number(input.value) || 0), 0);
        const cashDifference = cashActual - Number(currentCash.expected_cash || 0);
        document.querySelector('[data-cash-actual]').textContent = window.app.money(cashActual);
        document.querySelector('[data-cash-difference]').textContent = formatSignedMoney(cashDifference);
        document.querySelector('[data-cash-difference]').className = `difference-${cashDifference > 0 ? 'positive' : cashDifference < 0 ? 'negative' : 'zero'}`;

        let nonCashActual = 0;
        let verifiedComplete = true;
        document.querySelectorAll('[data-verified-method]').forEach(input => {
            const expected = Number(input.dataset.expected || 0);
            const isMissing = input.value.trim() === '' && expected > 0;
            const actual = Number(input.value || 0);
            const output = document.querySelector(`[data-method-difference="${CSS.escape(input.dataset.verifiedMethod)}"]`);
            if (isMissing) {
                verifiedComplete = false;
                output.textContent = 'Pendiente';
                output.className = '';
            } else {
                const difference = actual - expected;
                nonCashActual += actual;
                output.textContent = formatSignedMoney(difference);
                output.className = `difference-${difference > 0 ? 'positive' : difference < 0 ? 'negative' : 'zero'}`;
            }
        });
        const expectedTotal = Object.values(currentCash.payment_totals || {}).reduce((sum, value) => sum + Number(value), 0);
        const actualTotal = cashActual - Number(currentCash.opening_amount || 0) + nonCashActual;
        document.getElementById('reconcile-total-actual').textContent = verifiedComplete ? window.app.money(actualTotal) : 'Pendiente';
        const totalDifference = actualTotal - expectedTotal;
        const differenceElement = document.getElementById('reconcile-total-difference');
        differenceElement.textContent = verifiedComplete ? formatSignedMoney(totalDifference) : 'Pendiente';
        differenceElement.className = verifiedComplete ? `difference-${totalDifference > 0 ? 'positive' : totalDifference < 0 ? 'negative' : 'zero'}` : '';
        document.getElementById('reconcile-explanation').textContent = differenceExplanation(totalDifference, verifiedComplete);
    }

    function dateInput(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    }

    function monthInput(date) {
        return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
    }

    async function loadExpenses() {
        const requestId = ++expensesRequestId;
        const filterForm = document.getElementById('expense-filter-form');
        const params = new URLSearchParams();
        if (filterForm.elements.start.value) params.set('start', filterForm.elements.start.value);
        if (filterForm.elements.end.value) params.set('end', filterForm.elements.end.value);
        if (filterForm.elements.category.value) params.set('category', filterForm.elements.category.value);
        try {
            const data = await window.app.request(`/api/expenses/?${params}`);
            if (requestId !== expensesRequestId) return;
            const displayDate = value => new Intl.DateTimeFormat('es', {
                day: 'numeric',
                month: 'short',
                year: 'numeric',
            }).format(new Date(`${value}T12:00:00`));
            const expensePeriod = filterForm.elements.start.value && filterForm.elements.end.value
                ? `${displayDate(filterForm.elements.start.value)} – ${displayDate(filterForm.elements.end.value)}`
                : 'Todas las fechas';
            document.getElementById('expense-summary').innerHTML =
                `<span class="expense-count">${data.count} ${data.count === 1 ? 'gasto' : 'gastos'}<small>${window.app.escape(expensePeriod)}</small></span><strong class="expense-total">${window.app.money(data.total)}<small>Total de gastos filtrados</small></strong>`;
            document.getElementById('expense-list').innerHTML = data.expenses.map(expense => `
                <tr>
                    <td data-label="Fecha">${window.app.escape(expense.expense_date)}</td>
                    <td data-label="Gasto">${window.app.escape(expense.category_label)}${expense.description ? ` (${window.app.escape(expense.description)})` : ''}</td>
                    <td data-label="Valor"><strong>${window.app.money(expense.amount)}</strong></td>
                    <td data-label="Registrado por">${window.app.escape(expense.created_by)}</td>
                    <td data-label="Acciones" class="expense-actions">
                        <button class="small-button" type="button" data-expense-edit="${expense.id}">Editar</button>
                        <button class="small-button expense-delete-button" type="button" data-expense-delete="${expense.id}">Eliminar</button>
                    </td>
                </tr>`).join('') || '<tr><td colspan="5" class="empty-row">No hay gastos para los filtros seleccionados.</td></tr>';
        } catch (error) {
            if (requestId === expensesRequestId) {
                document.getElementById('expense-list').innerHTML =
                    `<tr><td colspan="5" class="empty-row">${window.app.escape(error.message)}</td></tr>`;
            }
        }
    }

    function resetExpenseForm() {
        const form = document.getElementById('expense-form');
        form.reset();
        form.elements.expense_date.value = todayInputValue;
        delete form.dataset.expenseId;
        form.elements.description.required = false;
        document.getElementById('cancel-expense-edit').hidden = true;
        form.querySelector('[type="submit"]').textContent = 'Registrar gasto';
        document.getElementById('expense-form-message').textContent = '';
    }

    document.getElementById('expense-form').elements.category.addEventListener('change', event => {
        const requiresDescription = event.currentTarget.value === 'remodeling';
        document.getElementById('expense-form').elements.description.required = requiresDescription;
        document.getElementById('expense-description-hint').textContent =
            requiresDescription ? '(obligatoria)' : '(obligatoria para remodelación)';
    });
    document.getElementById('cancel-expense-edit').addEventListener('click', resetExpenseForm);
    document.getElementById('expense-filter-form').addEventListener('submit', event => {
        event.preventDefault();
        loadExpenses();
    });
    document.getElementById('expense-form').addEventListener('submit', async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const body = Object.fromEntries(new FormData(form).entries());
        const expenseId = form.dataset.expenseId;
        try {
            await window.app.request(
                expenseId ? `/api/expenses/${expenseId}/` : '/api/expenses/',
                {method: expenseId ? 'PATCH' : 'POST', body: JSON.stringify(body)},
            );
            window.app.toast(expenseId ? 'Gasto actualizado' : 'Gasto registrado');
            resetExpenseForm();
            await loadExpenses();
            if (document.getElementById('view-profits').classList.contains('is-visible')) {
                loadProfits();
            }
        } catch (error) {
            document.getElementById('expense-form-message').textContent = error.message;
        }
    });
    document.getElementById('expense-list').addEventListener('click', async event => {
        const editButton = event.target.closest('[data-expense-edit]');
        const deleteButton = event.target.closest('[data-expense-delete]');
        const filterForm = document.getElementById('expense-filter-form');
        if (editButton) {
            const params = new URLSearchParams({
                start: filterForm.elements.start.value,
                end: filterForm.elements.end.value,
            });
            try {
                const data = await window.app.request(`/api/expenses/?${params}`);
                const expense = data.expenses.find(item => item.id === Number(editButton.dataset.expenseEdit));
                if (!expense) throw new Error('No se encontró el gasto seleccionado. Actualiza la lista.');
                const form = document.getElementById('expense-form');
                form.dataset.expenseId = expense.id;
                form.elements.expense_date.value = expense.expense_date;
                form.elements.category.value = expense.category;
                form.elements.amount.value = expense.amount;
                form.elements.description.value = expense.description;
                form.elements.description.required = expense.category === 'remodeling';
                form.querySelector('[type="submit"]').textContent = 'Guardar cambios';
                document.getElementById('cancel-expense-edit').hidden = false;
                document.getElementById('expense-form-message').textContent = 'Editando gasto existente.';
                form.scrollIntoView({behavior: 'smooth', block: 'center'});
            } catch (error) {
                window.app.toast(error.message);
            }
        }
        if (deleteButton && window.confirm('¿Eliminar este gasto? Esta acción no se puede deshacer.')) {
            try {
                await window.app.request(`/api/expenses/${deleteButton.dataset.expenseDelete}/`, {method: 'DELETE'});
                window.app.toast('Gasto eliminado');
                await loadExpenses();
                if (document.getElementById('view-profits').classList.contains('is-visible')) {
                    loadProfits();
                }
            } catch (error) {
                window.app.toast(error.message);
            }
        }
    });

    async function loadProfits() {
        const requestId = ++profitRequestId;
        const form = document.getElementById('profit-form');
        if (!form.elements.start_month.value || !form.elements.end_month.value) {
            const today = new Date();
            form.elements.start_month.value = monthInput(
                new Date(today.getFullYear(), today.getMonth() - 2, 1),
            );
            form.elements.end_month.value = monthInput(today);
        }
        try {
            const params = new URLSearchParams({
                start_month: form.elements.start_month.value,
                end_month: form.elements.end_month.value,
            });
            const data = await window.app.request(`/api/profits/?${params}`);
            if (requestId !== profitRequestId) return;
            const categoryRows = data.expense_by_category.map(item => `
                <div class="report-financial-row"><span>${window.app.escape(item.category)}</span><strong>${window.app.money(item.total)}</strong></div>`
            ).join('') || '<p class="empty-state">No hay gastos en el periodo.</p>';
            const monthRows = [...data.months].reverse().map(item => {
                const monthName = new Intl.DateTimeFormat('es', {month: 'long', year: 'numeric'})
                    .format(new Date(`${item.month}-01T12:00:00`));
                const profit = Number(item.profit);
                const isCurrentMonth = item.month === monthInput(new Date());
                return `<tr class="${isCurrentMonth ? 'is-current-month' : ''}">
                    <td data-label="Mes">${window.app.escape(monthName)}${isCurrentMonth ? '<span class="current-month-badge">Mes actual</span>' : ''}</td>
                    <td data-label="Ventas">${window.app.money(item.sales_total)}</td>
                    <td data-label="Gastos">${window.app.money(item.expense_total)}</td>
                    <td data-label="Beneficio" class="${profit < 0 ? 'profit-negative' : 'profit-positive'}"><strong>${profit < 0 ? '▼ Pérdida · ' : '▲ Beneficio · '}${window.app.money(item.profit)}</strong></td>
                </tr>`;
            }).join('');
            const startMonthName = new Intl.DateTimeFormat('es', {month: 'long', year: 'numeric'})
                .format(new Date(`${data.start_month}-01T12:00:00`));
            const endMonthName = new Intl.DateTimeFormat('es', {month: 'long', year: 'numeric'})
                .format(new Date(`${data.end_month}-01T12:00:00`));
            document.getElementById('profit-content').innerHTML = `
                <div class="profit-period-heading">
                    <span class="eyebrow">PERIODO CONSULTADO</span>
                    <strong>${window.app.escape(startMonthName)} – ${window.app.escape(endMonthName)}</strong>
                    <span>El mes actual aparece primero cuando está dentro del rango.</span>
                </div>
                <div class="report-kpis report-summary-kpis profit-summary">
                    <div class="report-kpi"><span>VENTAS COBRADAS</span><strong>${window.app.money(data.sales_total)}</strong></div>
                    <div class="report-kpi"><span>GASTOS REGISTRADOS</span><strong>${window.app.money(data.expense_total)}</strong></div>
                    <div class="report-kpi profit-total-kpi"><span>RESULTADO NETO ESTIMADO</span><strong class="${Number(data.profit) < 0 ? 'profit-negative' : 'profit-positive'}">${Number(data.profit) < 0 ? '▼ Pérdida · ' : '▲ Beneficio · '}${window.app.money(data.profit)}</strong><small>Ventas cobradas menos gastos registrados</small></div>
                </div>
                <div class="profit-detail-grid">
                    <section class="report-box"><span class="eyebrow">GASTOS POR CATEGORÍA</span><h3>En el rango seleccionado</h3>${categoryRows}</section>
                    <section class="report-box profit-monthly-table"><span class="eyebrow">RESULTADO MENSUAL</span><h3>${window.app.escape(data.start_month)} a ${window.app.escape(data.end_month)}</h3>
                        <div class="table-wrap"><table class="responsive-data-table"><thead><tr><th>MES</th><th>VENTAS</th><th>GASTOS</th><th>BENEFICIO ESTIMADO</th></tr></thead><tbody>${monthRows}</tbody></table></div>
                    </section>
                </div>`;
        } catch (error) {
            if (requestId === profitRequestId) {
                document.getElementById('profit-content').innerHTML =
                    `<p class="alert-message">${window.app.escape(error.message)}</p>`;
            }
        }
    }
    document.getElementById('profit-form').addEventListener('submit', event => {
        event.preventDefault();
        loadProfits();
    });

    async function loadReport(start, end, allSales = false) {
        const requestId = ++reportRequestId;
        const today = new Date();
        if (!allSales) {
            start ||= dateInput(new Date(today.getFullYear(), today.getMonth(), 1));
            end ||= dateInput(today);
        }
        const form = document.getElementById('report-form');
        if (start) form.elements.start.value = start;
        if (end) form.elements.end.value = end;
        try {
            const query = allSales
                ? 'all=1'
                : new URLSearchParams({start, end}).toString();
            const report = await window.app.request(`/api/reports/?${query}`);
            if (requestId !== reportRequestId) return;
            form.elements.start.value = report.start;
            form.elements.end.value = report.end;
            const methodMax = Math.max(...report.by_method.map(item => Number(item.total)), 1);
            const typeMax = Math.max(...report.by_order_type.map(item => Number(item.total)), 1);
            const dayMax = Math.max(...report.daily_sales.map(item => Number(item.total)), 1);
            const topMax = Math.max(...report.top_products.map(item => Number(item.quantity)), 1);
            const leastMax = Math.max(...report.least_products.map(item => Number(item.quantity)), 1);
            const productBars = (items, max, tone) => items.slice(0, 5).map((item, index) => {
                const width = Number(item.quantity) ? Math.max(Number(item.quantity) / max * 100, 2) : 0;
                return `<div class="product-chart-row">
                    <span class="product-chart-name">${index + 1}. ${window.app.escape(item.name)}</span>
                    <div class="product-chart-track"><span class="product-chart-fill ${tone}" style="width:${width}%"></span></div>
                    <strong>${item.quantity}</strong><small>${window.app.money(item.revenue)}</small>
                </div>`;
            }).join('') || '<p class="empty-state">No hubo productos vendidos en este periodo.</p>';
            const breakdownRows = (items, max, labelKey) => items.map(item => `
                <div class="bar-row">
                    <span>${window.app.escape(item[labelKey])}</span>
                    <div class="bar-track"><div class="bar-fill" style="width:${Math.max(Number(item.total) / max * 100, 2)}%"></div></div>
                    <strong>${window.app.money(item.total)}</strong>
                    <small>${item.count} ${item.count === 1 ? 'pedido' : 'pedidos'}</small>
                </div>`).join('') || '<p class="empty-state">No hay cobros en este periodo.</p>';
            const dailyBars = report.daily_sales.map(item => {
                const day = report.trend_interval === 'month'
                    ? new Date(`${item.date}T12:00:00`).toLocaleDateString('es', {month: 'short', year: '2-digit'})
                    : new Date(`${item.date}T12:00:00`).toLocaleDateString('es', {day: 'numeric', month: 'short'});
                const height = Number(item.total) ? Math.max(Number(item.total) / dayMax * 100, 3) : 0;
                return `<div class="daily-chart-column" title="${day}: ${window.app.money(item.total)}"><strong>${Number(item.total) ? window.app.money(item.total) : ''}</strong><div class="daily-bar-track"><span style="height:${height}%"></span></div><small>${window.app.escape(day)}</small></div>`;
            }).join('');
            const inventoryRows = report.inventory.map(product => {
                const stock = product.stock_quantity === null
                    ? '<span class="inventory-status inventory-unconfigured">Por configurar</span>'
                    : product.stock_quantity === 0
                        ? '<span class="inventory-status inventory-empty">Agotado</span>'
                        : `<span class="inventory-status">${product.stock_quantity} unidades</span>`;
                return `<tr>
                    <td>${window.app.escape(product.name)}<small>${window.app.escape(product.category)}</small></td>
                    <td>${stock}</td>
                    <td>${product.units_sold}</td>
                    <td>${product.available ? 'En carta' : 'Inactivo'}</td>
                </tr>`;
            }).join('') || '<tr><td colspan="4" class="empty-row">No hay productos con control de existencias.</td></tr>';
            document.getElementById('report-content').innerHTML = `
                <div class="report-period-intro">
                    <strong>Periodo: ${window.app.escape(report.start)} al ${window.app.escape(report.end)}</strong>
                    <p>Las ventas se agrupan por fecha del pago. ${report.trend_interval === 'month' ? 'La tendencia se resume por mes.' : ''} Los pedidos pendientes y cancelados se cuentan por fecha de creación. Anular un comprobante no descuenta un cobro ni significa que hubo reembolso.</p>
                </div>
                <div class="report-kpis report-summary-kpis">
                    <div class="report-kpi"><span>VENTAS COBRADAS</span><strong>${window.app.money(report.sales_total)}</strong></div>
                    <div class="report-kpi"><span>PEDIDOS PAGADOS</span><strong>${report.paid_order_count}</strong></div>
                    <div class="report-kpi"><span>VALOR PROMEDIO POR PEDIDO</span><strong>${window.app.money(report.average_ticket)}</strong></div>
                    <div class="report-kpi"><span>PENDIENTE DE COBRO</span><strong>${window.app.money(report.pending_total)}</strong><small>${report.pending_order_count} pedidos creados en el periodo</small></div>
                    <div class="report-kpi"><span>PEDIDOS CANCELADOS</span><strong>${report.cancelled_order_count}</strong><small>De ${report.created_order_count} creados en el periodo</small></div>
                    <div class="report-kpi"><span>COMPROBANTES ANULADOS</span><strong>${report.voided_invoice_count}</strong><small>${window.app.money(report.voided_invoice_total)} cobrados · sin reembolso</small></div>
                </div>
                <div class="report-content-grid">
                    <section class="report-box report-chart-box"><span class="eyebrow">INGRESOS POR FECHA DE PAGO</span><h3>Ventas cobradas por día</h3><div class="daily-sales-chart" role="img" aria-label="Gráfico de ventas cobradas por día">${dailyBars}</div></section>
                    <section class="report-box"><span class="eyebrow">COMPOSICIÓN DEL COBRO</span><h3>¿De qué se compone?</h3>
                        <div class="report-financial-row"><span>Productos</span><strong>${window.app.money(report.subtotal_total)}</strong></div>
                        <div class="report-financial-row"><span>Domicilios</span><strong>${window.app.money(report.delivery_fee_total)}</strong></div>
                        <div class="report-financial-row"><span>Impuestos / recargos</span><strong>${window.app.money(report.tax_total)}</strong></div>
                        <div class="report-financial-row report-financial-total"><span>Total cobrado</span><strong>${window.app.money(report.sales_total)}</strong></div>
                    </section>
                    <section class="report-box"><span class="eyebrow">CONCILIACIÓN</span><h3>Cobros por medio de pago</h3>${breakdownRows(report.by_method, methodMax, 'method')}</section>
                    <section class="report-box"><span class="eyebrow">TIPO DE VENTA</span><h3>Ventas por canal</h3>${breakdownRows(report.by_order_type, typeMax, 'kind')}</section>
                    <section class="report-box"><span class="eyebrow">PRODUCTOS</span><h3>Más vendidos por unidades</h3><div class="product-chart-list">${productBars(report.top_products, topMax, 'product-chart-fill-best')}</div></section>
                    <section class="report-box"><span class="eyebrow">PRODUCTOS</span><h3>Menos vendidos por unidades</h3><div class="product-chart-list">${productBars(report.least_products, leastMax, 'product-chart-fill-low')}</div></section>
                    <section class="report-box report-inventory-box"><span class="eyebrow">CONTROL DE EXISTENCIAS · DISPONIBLE AHORA</span><h3>Inventario de productos controlados</h3>
                        <p class="report-note">${report.out_of_stock_count} agotados · ${report.unconfigured_stock_count} por configurar. Las unidades vendidas sí corresponden al periodo consultado; las existencias son actuales.</p>
                        <div class="table-wrap"><table><thead><tr><th>PRODUCTO</th><th>EXISTENCIAS</th><th>VENDIDAS EN EL PERIODO</th><th>DISPONIBILIDAD</th></tr></thead><tbody>${inventoryRows}</tbody></table></div>
                    </section>
                </div>`;
        } catch (error) {
            if (requestId !== reportRequestId) return;
            document.getElementById('report-content').innerHTML =
                `<p class="alert-message">${window.app.escape(error.message)}</p>`;
        }
    }
    document.getElementById('report-form').addEventListener('submit', event => {
        event.preventDefault();
        reportAllSelected = false;
        document.querySelectorAll('[data-report-range]').forEach(button => {
            button.classList.remove('is-active');
            button.setAttribute('aria-pressed', 'false');
        });
        loadReport(event.currentTarget.elements.start.value, event.currentTarget.elements.end.value);
    });
    document.querySelector('.report-period-shortcuts').addEventListener('click', event => {
        const button = event.target.closest('[data-report-range]');
        if (!button) return;
        const today = new Date();
        let start;
        let end = today;
        if (button.dataset.reportRange === 'all') {
            reportAllSelected = true;
            document.querySelectorAll('[data-report-range]').forEach(rangeButton => {
                const selected = rangeButton === button;
                rangeButton.classList.toggle('is-active', selected);
                rangeButton.setAttribute('aria-pressed', String(selected));
            });
            loadReport('', '', true);
            return;
        } else {
            reportAllSelected = false;
        }
        if (button.dataset.reportRange === 'today') {
            start = today;
        } else if (button.dataset.reportRange === 'week') {
            const dayOfWeek = (today.getDay() + 6) % 7;
            start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - dayOfWeek);
        } else if (button.dataset.reportRange === 'last-month') {
            start = new Date(today.getFullYear(), today.getMonth() - 1, 1);
            end = new Date(today.getFullYear(), today.getMonth(), 0);
        } else {
            start = new Date(today.getFullYear(), today.getMonth(), 1);
        }
        document.querySelectorAll('[data-report-range]').forEach(rangeButton => {
            const selected = rangeButton === button;
            rangeButton.classList.toggle('is-active', selected);
            rangeButton.setAttribute('aria-pressed', String(selected));
        });
        loadReport(dateInput(start), dateInput(end));
    });
    document.getElementById('export-csv').addEventListener('click', () => {
        const form = document.getElementById('report-form');
        window.location.href = reportAllSelected
            ? '/reports/export.csv?all=1'
            : `/reports/export.csv?start=${form.elements.start.value}&end=${form.elements.end.value}`;
    });
    const profitToday = new Date();
    document.getElementById('profit-form').elements.start_month.value =
        monthInput(new Date(profitToday.getFullYear(), profitToday.getMonth() - 2, 1));
    document.getElementById('profit-form').elements.end_month.value = monthInput(profitToday);
    document.getElementById('expense-form').elements.expense_date.value = todayInputValue;
    document.getElementById('expense-filter-form').elements.start.value =
        dateInput(new Date(new Date().getFullYear(), new Date().getMonth(), 1));
    document.getElementById('expense-filter-form').elements.end.value = todayInputValue;
    refreshOperationalViews();
    setInterval(refreshOperationalViews, 12000);
})();