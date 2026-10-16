(() => {
    let orders = [];
    let activeFilter = 'all';
    let currentCash = null;
    let cashHistory = [];
    let products = [];
    let productCategories = [];
    let paidReceiptOrder = null;
    const cashDenominations = [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000];
    const digitalPaymentMethods = [
        {label: 'Bancolombia', name: 'verified-bancolombia'},
        {label: 'Nequi', name: 'verified-nequi'},
        {label: 'Tarjeta', name: 'verified-card'},
    ];
    const titles = { overview: 'Resumen del día', orders: 'Pedidos', kitchen: 'Cocina', products: 'Carta', cash: 'Caja', reports: 'Informes' };
    const statusLabels = { received: 'Recibido', preparing: 'En preparación', ready: 'Preparado', delivered: 'Entregado', cancelled: 'Cancelado' };
    const statusClass = status => `status-${status}`;
    const shortTime = iso => new Intl.DateTimeFormat('es', { hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
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
        if (name === 'reports') loadReport();
    }
    document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => setView(button.dataset.view)));
    document.getElementById('mobile-menu').addEventListener('click', () => document.getElementById('sidebar').classList.toggle('is-open'));

    async function loadOrders() {
        try {
            const params = new URLSearchParams();
            const number = document.getElementById('order-number-filter').value.trim();
            const dateFrom = document.getElementById('order-date-from').value;
            const dateTo = document.getElementById('order-date-to').value;
            if (number) params.set('number', number);
            if (dateFrom) params.set('date_from', dateFrom);
            if (dateTo) params.set('date_to', dateTo);
            const query = params.toString();
            const data = await window.app.request(`/api/orders/${query ? `?${query}` : ''}`);
            orders = data.orders;
            renderOverview(); renderOrders(); renderKitchen();
        } catch (error) { window.app.toast(error.message); }
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
            document.getElementById('products-list').innerHTML = `<tr><td colspan="6" class="empty-row">${window.app.escape(error.message)}</td></tr>`;
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
                    <td><div class="product-name-cell"><strong>${window.app.escape(product.name)}${product.featured ? ' · Destacado' : ''}</strong><small>${window.app.escape(product.description || 'Sin descripción')}</small></div></td>
                    <td>${window.app.escape(product.category_name)}</td>
                    <td><strong>${window.app.money(product.price)}</strong></td>
                    <td><span class="status-chip ${product.available ? 'status-ready' : 'status-cancelled'}">${product.available ? 'Disponible' : 'Agotado'}</span></td>
                    <td>${product.sold_count}</td>
                    <td><div class="product-row-actions"><button class="small-button" data-product-edit="${product.id}">Editar</button><button class="small-button" data-product-toggle="${product.id}">${product.available ? 'Marcar agotado' : 'Volver a ofrecer'}</button><button class="small-button product-delete-button" data-product-delete="${product.id}">Eliminar</button></div></td>
                </tr>`).join('');
            return `
                <tr class="product-category-row"><td colspan="6"><div class="product-category-heading"><strong>${window.app.escape(category.name)}</strong><span>${categoryProducts.length} producto${categoryProducts.length === 1 ? '' : 's'}${category.active ? '' : ' · Categoría inactiva'}</span></div></td></tr>
                ${productRows}`;
        }).join('');
        document.getElementById('products-list').innerHTML = groupedRows ||
            '<tr><td colspan="6" class="empty-row">No se encontraron productos.</td></tr>';
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
        } else {
            form.elements.available.checked = true;
        }
        document.getElementById('product-dialog').showModal();
    }

    document.getElementById('add-product-button').addEventListener('click', () => openProductDialog());
    document.getElementById('product-search').addEventListener('input', renderProducts);
    document.getElementById('product-category-filter').addEventListener('change', renderProducts);
    document.getElementById('products-list').addEventListener('click', async event => {
        const edit = event.target.closest('[data-product-edit]');
        const toggle = event.target.closest('[data-product-toggle]');
        const remove = event.target.closest('[data-product-delete]');
        if (edit) {
            openProductDialog(products.find(product => product.id === Number(edit.dataset.productEdit)));
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
        const payload = {
            name: form.elements.name.value.trim(),
            category_id: Number(form.elements.category_id.value),
            description: form.elements.description.value.trim(),
            price: form.elements.price.value,
            available: form.elements.available.checked,
            featured: form.elements.featured.checked,
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
        actions.push(`<button class="small-button" data-sale-print="${order.id}">Imprimir factura</button>`);
        if (order.status === 'received') actions.push(`<button class="small-button confirm" data-status="preparing" data-id="${order.id}">Empezar preparación</button>`);
        if (order.status === 'preparing') actions.push(`<button class="small-button confirm" data-status="ready" data-id="${order.id}">Marcar preparado</button>`);
        if (order.status === 'ready') actions.push(`<button class="small-button confirm" data-status="delivered" data-id="${order.id}">Entregar pedido</button>`);
        if (!kitchen && order.status !== 'cancelled' && order.payment_status !== 'paid') actions.push(`<button class="small-button" data-pay-open="${order.id}">Registrar pago</button>`);
        if (!kitchen && !['delivered', 'cancelled'].includes(order.status)) actions.push(`<button class="small-button" data-status="cancelled" data-id="${order.id}">Cancelar</button>`);
        return actions.join('');
    }
    function renderOverview() {
        const today = new Date().toLocaleDateString('en-CA');
        const todayOrders = orders.filter(order => new Date(order.created_at).toLocaleDateString('en-CA') === today);
        const paid = todayOrders.filter(order => order.payment_status === 'paid' && order.status !== 'cancelled');
        document.getElementById('metric-sales').textContent = window.app.money(paid.reduce((sum, order) => sum + Number(order.total), 0));
        document.getElementById('metric-orders').textContent = todayOrders.length;
        document.getElementById('metric-pending').textContent = `${todayOrders.filter(order => order.payment_status !== 'paid').length} pendientes de pago`;
        document.getElementById('metric-active').textContent = orders.filter(order => ['received', 'preparing', 'ready'].includes(order.status)).length;
        document.getElementById('nav-order-count').textContent = orders.filter(order => ['received', 'preparing'].includes(order.status)).length;
        document.getElementById('recent-orders').innerHTML = todayOrders.slice(0, 6).map(order => `<tr><td><span class="order-ref">#${window.app.escape(order.number)}</span></td><td>${window.app.escape(order.customer_name)}</td><td>${window.app.escape(order.kind_label)}</td><td><span class="status-chip ${statusClass(order.status)}">${order.status_label}</span></td><td><b>${window.app.money(order.total)}</b></td><td>${shortTime(order.created_at)}</td><td><button class="small-button" data-jump="orders">Abrir</button></td></tr>`).join('') || '<tr><td colspan="7" class="empty-row">Todavía no hay pedidos.</td></tr>';
        window.app.request('/api/cash/').then(data => {
            currentCash = data.session;
            document.getElementById('metric-cash').textContent = currentCash ? window.app.money(currentCash.opening_amount) : 'Cerrada';
            document.getElementById('metric-cash-note').textContent = currentCash ? 'Turno en curso' : 'Abre tu turno para empezar';
        }).catch(() => { });
    }
    function renderOrders() {
        const numberQuery = document.getElementById('order-number-filter').value.trim().toLocaleLowerCase();
        const dateFrom = document.getElementById('order-date-from').value;
        const dateTo = document.getElementById('order-date-to').value;
        const list = orders.filter(order => {
            const createdAt = new Date(order.created_at);
            const orderDate = [
                createdAt.getFullYear(),
                String(createdAt.getMonth() + 1).padStart(2, '0'),
                String(createdAt.getDate()).padStart(2, '0'),
            ].join('-');
            return (activeFilter === 'all' || order.status === activeFilter) &&
                (!numberQuery || order.number.toLocaleLowerCase().includes(numberQuery)) &&
                (!dateFrom || orderDate >= dateFrom) &&
                (!dateTo || orderDate <= dateTo);
        });
        document.getElementById('orders-list').innerHTML = list.map(order => `
      <article class="order-card"><div class="order-card-main"><strong><span class="order-ref">#${window.app.escape(order.number)}</span> · ${window.app.escape(order.customer_name)}</strong><small>${window.app.escape(order.kind_label)}${order.table_number ? ` · Mesa ${window.app.escape(order.table_number)}` : ''}${order.address ? ` · ${window.app.escape(order.address)}` : ''} · ${shortTime(order.created_at)}</small><span><span class="status-chip ${statusClass(order.status)}">${order.status_label}</span> <span class="payment-chip ${order.payment_status === 'paid' ? 'payment-paid' : ''}">${order.payment_status_label}</span></span></div><div class="order-card-items">${order.items.map(item => `${item.quantity} × ${window.app.escape(item.name)}${item.instructions ? ` <small>(${window.app.escape(item.instructions)})</small>` : ''}`).join('<br>')}${order.note ? `<br><small>Nota: ${window.app.escape(order.note)}</small>` : ''}<br><b>${window.app.money(order.total)} · ${window.app.escape(order.payment_method_label)}</b></div><div class="order-card-actions">${orderActions(order)}</div></article>`).join('') || '<div class="empty-row">No hay pedidos en esta vista.</div>';
    }
    function renderKitchen() {
        const active = orders.filter(order => ['received', 'preparing', 'ready'].includes(order.status));
        const columns = [['received', 'Recibidos'], ['preparing', 'En preparación'], ['ready', 'Preparados']];
        document.getElementById('kitchen-board').innerHTML = columns.map(([status, label]) => {
            const items = active.filter(order => order.status === status);
            return `<section class="kitchen-column"><h3>${label}<b>${items.length}</b></h3>${items.map(order => `<article class="kitchen-ticket ${status === 'ready' ? 'ready' : ''}"><div class="ticket-head"><span>#${window.app.escape(order.number)}</span><small>${shortTime(order.created_at)}</small></div><div class="ticket-meta">${window.app.escape(order.customer_name)} · ${window.app.escape(order.kind_label)}${order.table_number ? ` · Mesa ${window.app.escape(order.table_number)}` : ''}</div><div class="ticket-items">${order.items.map(item => `<div><b>${item.quantity}×</b>${window.app.escape(item.name)}</div>${item.instructions ? `<small>${window.app.escape(item.instructions)}</small>` : ''}`).join('')}${order.note ? `<small>Nota: ${window.app.escape(order.note)}</small>` : ''}</div>${orderActions(order, true)}</article>`).join('') || '<div class="empty-state">Sin comandas</div>'}</section>`;
        }).join('');
    }
    document.getElementById('order-filters').addEventListener('click', event => {
        const button = event.target.closest('[data-filter]'); if (!button) return;
        activeFilter = button.dataset.filter;
        document.querySelectorAll('.filter-tab').forEach(tab => tab.classList.toggle('is-active', tab === button)); renderOrders();
    });
    let orderSearchTimer;
    document.getElementById('order-number-filter').addEventListener('input', () => {
        renderOrders();
        clearTimeout(orderSearchTimer);
        orderSearchTimer = setTimeout(loadOrders, 250);
    });
    ['order-date-from', 'order-date-to'].forEach(id =>
        document.getElementById(id).addEventListener('change', loadOrders)
    );
    document.getElementById('clear-order-filters').addEventListener('click', () => {
        document.getElementById('order-number-filter').value = '';
        document.getElementById('order-date-from').value = todayInputValue;
        document.getElementById('order-date-to').value = todayInputValue;
        loadOrders();
    });
    document.getElementById('refresh-orders').addEventListener('click', loadOrders);
    document.body.addEventListener('click', async event => {
        const jumpButton = event.target.closest('[data-jump]');
        const statusButton = event.target.closest('[data-status]');
        const payOpenButton = event.target.closest('[data-pay-open]');
        const payCancelButton = event.target.closest('[data-pay-cancel]');
        const kitchenPrintButton = event.target.closest('[data-kitchen-print]');
        const salePrintButton = event.target.closest('[data-sale-print]');
        const receiptCloseButton = event.target.closest('[data-close-paid-receipt]');
        const receiptPrintButton = event.target.closest('#print-paid-receipt');
        if (jumpButton) setView(jumpButton.dataset.jump);
        if (kitchenPrintButton) {
            const order = orders.find(item => String(item.id) === kitchenPrintButton.dataset.kitchenPrint);
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
                window.app.toast('Permite las ventanas emergentes para imprimir la factura.');
            }
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
            const dialog = document.getElementById('payment-dialog');
            const form = document.getElementById('payment-form');
            form.dataset.paymentForm = order.id;
            form.elements.payment_method.value = order.payment_method;
            dialog.showModal();
        }
        if (payCancelButton) {
            document.getElementById('payment-dialog').close();
        }
        if (statusButton) {
            statusButton.disabled = true;
            try { await window.app.request(`/api/orders/${statusButton.dataset.id}/status/`, { method: 'POST', body: JSON.stringify({ status: statusButton.dataset.status }) }); await loadOrders(); window.app.toast('Estado actualizado'); }
            catch (error) { window.app.toast(error.message); }
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
            const result = await window.app.request(`/api/orders/${paymentForm.dataset.paymentForm}/payment/`, {
                method: 'POST', body: JSON.stringify({payment_method: paymentMethod, paid: true}),
            });
            document.getElementById('payment-dialog').close();
            await loadOrders();
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

    function dateInput(date) { return date.toLocaleDateString('en-CA'); }
    async function loadReport(start, end) {
        const today = new Date();
        start ||= dateInput(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 6));
        end ||= dateInput(today);
        const form = document.getElementById('report-form'); form.elements.start.value = start; form.elements.end.value = end;
        try {
            const report = await window.app.request(`/api/reports/?start=${start}&end=${end}`);
                const methodMax = Math.max(...report.by_method.map(item => Number(item.total)), 1);
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
                const dailyBars = report.daily_sales.map(item => {
                    const day = new Date(`${item.date}T12:00:00`).toLocaleDateString('es', {day: 'numeric', month: 'short'});
                    const height = Number(item.total) ? Math.max(Number(item.total) / dayMax * 100, 3) : 0;
                    return `<div class="daily-chart-column" title="${day}: ${window.app.money(item.total)}"><strong>${Number(item.total) ? window.app.money(item.total) : ''}</strong><div class="daily-bar-track"><span style="height:${height}%"></span></div><small>${window.app.escape(day)}</small></div>`;
                }).join('');
                document.getElementById('report-content').innerHTML = `
                    <div class="report-kpis report-summary-kpis">
                        <div class="report-kpi"><span>VENTAS PAGADAS</span><strong>${window.app.money(report.sales_total)}</strong></div>
                        <div class="report-kpi"><span>PEDIDOS</span><strong>${report.order_count}</strong></div>
                        <div class="report-kpi"><span>PENDIENTE DE PAGO</span><strong>${window.app.money(report.pending_total)}</strong></div>
                    </div>
                    <div class="report-content-grid">
                        <section class="report-box report-chart-box"><span class="eyebrow">TENDENCIA</span><h3>Ventas por día</h3><div class="daily-sales-chart" role="img" aria-label="Gráfico de ventas diarias">${dailyBars}</div></section>
                        <section class="report-box"><span class="eyebrow">MEDIOS DE PAGO</span><h3>Ventas por método</h3>${report.by_method.map(item => `<div class="bar-row"><span>${window.app.escape(item.method)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(Number(item.total) / methodMax * 100, 2)}%"></div></div><strong>${window.app.money(item.total)}</strong></div>`).join('') || '<p class="empty-state">No hay ventas pagadas en este periodo.</p>'}</section>
                        <section class="report-box"><span class="eyebrow">MEJOR SALIDA</span><h3>Productos más vendidos</h3><div class="product-chart-list">${productBars(report.top_products, topMax, 'product-chart-fill-best')}</div></section>
                        <section class="report-box"><span class="eyebrow">MENOR SALIDA</span><h3>Productos menos vendidos</h3><div class="product-chart-list">${productBars(report.least_products, leastMax, 'product-chart-fill-low')}</div></section>
                    </div>`;
        } catch (error) { document.getElementById('report-content').innerHTML = `<p class="alert-message">${window.app.escape(error.message)}</p>`; }
    }
    document.getElementById('report-form').addEventListener('submit', event => { event.preventDefault(); loadReport(event.currentTarget.elements.start.value, event.currentTarget.elements.end.value); });
    document.getElementById('export-csv').addEventListener('click', () => {
        const form = document.getElementById('report-form');
        window.location.href = `/reports/export.csv?start=${form.elements.start.value}&end=${form.elements.end.value}`;
    });
    loadOrders();
    setInterval(loadOrders, 12000);
})();