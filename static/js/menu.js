(() => {
    const cart = new Map();
    let menuData = null;
    let activeCategory = 'all';
    let acceptingOrders = false;
    let lastOrderReceipt = null;
    const grid = document.getElementById('menu-grid');
    const tabs = document.getElementById('category-tabs');
    const drawer = document.getElementById('cart-drawer');

    async function loadMenu() {
        try {
            menuData = await window.app.request('/api/menu/');
            window.BUSINESS_CURRENCY_SYMBOL = menuData.symbol;
            acceptingOrders = menuData.accepting_orders;
            if (!acceptingOrders) {
                document.getElementById('open-status').classList.add('is-closed');
                document.querySelector('#open-status span').textContent = 'Pedidos pausados: caja cerrada';
            }
            renderTabs();
            renderProducts();
            renderCart();
        } catch {
            grid.innerHTML = '<p class="empty-state">No pudimos cargar la carta. Intenta actualizar la página.</p>';
        }
    }

    function renderTabs() {
        tabs.innerHTML = `<button class="category-tab ${activeCategory === 'all' ? 'is-active' : ''}" data-category="all">Todo</button>` +
            menuData.categories.map(category => `<button class="category-tab ${activeCategory === String(category.id) ? 'is-active' : ''}" data-category="${category.id}">${window.app.escape(category.name)}</button>`).join('');
    }

    function renderProducts() {
        const categories = activeCategory === 'all' ? menuData.categories : menuData.categories.filter(category => String(category.id) === activeCategory);
        const products = categories.flatMap(category => category.products);
        grid.innerHTML = products.length ? products.map(product => `
      <article class="product-card"><div class="product-top"><div><div class="product-tag">${product.featured ? 'FAVORITO DE LA CASA' : 'PREPARADO AL MOMENTO'}</div><h3>${window.app.escape(product.name)}</h3></div><span class="product-price">${window.app.money(product.price)}</span></div>
    <p>${window.app.escape(product.description || 'Un clásico de la casa, preparado al momento.')}</p>${product.extras.length ? `<fieldset class="extra-list"><legend>Hazlo a tu gusto</legend>${product.extras.map(extra => `<label><input type="checkbox" data-extra-of="${product.id}" value="${extra.id}" ${acceptingOrders ? '' : 'disabled'}><span>${window.app.escape(extra.name)}</span><small>+${window.app.money(extra.price)}</small></label>`).join('')}</fieldset>` : ''}<label class="product-observation">Observación para este producto <span>(opcional)</span><textarea data-observation-of="${product.id}" maxlength="180" rows="2" placeholder="Ej. sin cebolla" ${acceptingOrders ? '' : 'disabled'}></textarea></label><div class="product-bottom"><span class="eyebrow">${window.app.escape(categories.find(c => c.products.includes(product))?.name || '')}</span><button class="product-add" data-add="${product.id}" aria-label="Agregar ${window.app.escape(product.name)}" ${acceptingOrders ? '' : 'disabled'}>+</button></div></article>`).join('') : '<p class="empty-state">No hay productos disponibles en esta categoría por ahora.</p>';
    }

    function renderCart() {
        const rows = [...cart.values()];
        const count = rows.reduce((sum, row) => sum + row.quantity, 0);
        const subtotal = rows.reduce((sum, row) => sum + (Number(row.price) + row.extraTotal) * row.quantity, 0);
        const delivery = document.getElementById('order-kind').value === 'delivery' ? Number(menuData?.delivery_fee || 0) : 0;
        document.getElementById('cart-count').textContent = count;
        document.getElementById('drawer-count').textContent = count;
        document.getElementById('cart-total').textContent = window.app.money(subtotal + delivery + subtotal * Number(menuData?.tax_rate || 0) / 100);
        document.getElementById('cart-items').innerHTML = rows.length ? rows.map(row => `
      <div class="cart-line"><strong>${window.app.escape(row.name)}</strong><span class="quantity-control"><button type="button" data-qty="${row.key}" data-delta="-1" aria-label="Quitar uno">−</button>${row.quantity}<button type="button" data-qty="${row.key}" data-delta="1" aria-label="Agregar uno">+</button></span><small>${window.app.escape(row.extras.map(extra => extra.name).join(', ') || 'Sin extras')}${row.extraTotal ? ` · ${window.app.money(row.extraTotal)} extra` : ''}</small>${row.instructions ? `<small class="cart-instruction">Observación: ${window.app.escape(row.instructions)}</small>` : ''}<small>${window.app.money((Number(row.price) + row.extraTotal) * row.quantity)}</small></div>`).join('') : '<p class="empty-state">Tu bolsa está esperando algo rico.</p>';
    }

    function orderWhatsAppMessage(order) {
        const lines = order.items.map(item =>
            `${item.quantity} x ${item.name}${item.extras.length ? ` (${item.extras.map(extra => extra.name).join(', ')})` : ''}${item.instructions ? `\n   Observación: ${item.instructions}` : ''} - ${window.app.money(item.line_total)}`
        );
        return [
            `Hola, acabo de realizar el pedido #${order.number}.`,
            `Fecha: ${new Intl.DateTimeFormat('es-CO', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(order.created_at))}`,
            `Cliente: ${order.customer_name}`,
            `Tipo: ${order.kind_label}`,
            order.table_number ? `Mesa: ${order.table_number}` : '',
            order.address ? `Dirección: ${order.address}` : '',
            order.phone ? `Teléfono: ${order.phone}` : '',
            '',
            ...lines,
            `Total: ${window.app.money(order.total)}`,
            'Adjunto el comprobante del pedido.',
        ].filter(Boolean).join('\n');
    }

    function drawOrderReceipt(order) {
        const canvas = document.getElementById('order-receipt-image');
        const context = canvas.getContext('2d');
        const width = 840;
        const padding = 58;
        const contentWidth = width - padding * 2;
        const lines = [];
        const addText = (text, font, color = '#26332a', gap = 12) => {
            context.font = font;
            const words = String(text).split(/\s+/);
            let line = '';
            const wrapped = [];
            words.forEach(word => {
                const candidate = line ? `${line} ${word}` : word;
                if (line && context.measureText(candidate).width > contentWidth) {
                    wrapped.push(line);
                    line = word;
                } else {
                    line = candidate;
                }
            });
            if (line) wrapped.push(line);
            lines.push({type: 'text', lines: wrapped, font, color, gap});
        };
        const addPair = (label, value, bold = false) =>
            lines.push({type: 'pair', label, value, bold});

        addText(menuData.business_name, '700 34px Arial', '#ffffff', 16);
        addText('COMPROBANTE INTERNO · NO FISCAL', '600 18px Arial', '#e0ef9d', 19);
        addText(`PEDIDO #${order.number}`, '700 30px Arial', '#ffffff', 32);
        addPair('Fecha del pedido', new Intl.DateTimeFormat('es-CO', {
            dateStyle: 'medium', timeStyle: 'short',
        }).format(new Date(order.created_at)));
        addPair('Cliente', order.customer_name);
        addPair('Tipo de pedido', order.kind_label);
        if (order.table_number) addPair('Mesa', order.table_number);
        if (order.address) addPair('Dirección', order.address);
        if (order.phone) addPair('Teléfono', order.phone);
        if (order.note) addText(`Nota: ${order.note}`, '16px Arial', '#546257');
        lines.push({type: 'divider'});
        addText('DETALLE DEL PEDIDO', '700 19px Arial', '#24553e', 8);
        order.items.forEach(item => {
            addPair(`${item.quantity} × ${item.name}`, window.app.money(item.line_total), true);
            addText(`  Precio unitario: ${window.app.money(item.price)}`, '15px Arial', '#68736a', 2);
            item.extras.forEach(extra =>
                addText(`  + ${extra.name} (${window.app.money(extra.price)})`, '15px Arial', '#68736a', 2)
            );
            if (item.instructions) addText(`  Nota: ${item.instructions}`, 'italic 15px Arial', '#a75b37', 3);
        });
        lines.push({type: 'divider'});
        addPair('Subtotal', window.app.money(order.subtotal));
        if (Number(order.delivery_fee)) addPair('Domicilio', window.app.money(order.delivery_fee));
        if (Number(order.tax)) addPair('Impuestos', window.app.money(order.tax));
        addPair('TOTAL', window.app.money(order.total), true);
        addText(`Pago: ${order.payment_status_label} · ${order.payment_method_label}`, '16px Arial', '#546257', 4);
        addText('Gracias por tu pedido. El negocio confirmará los detalles por WhatsApp.', '15px Arial', '#546257', 4);

        let height = 250;
        lines.forEach(line => {
            if (line.type === 'text') {
                context.font = line.font;
                height += line.lines.length * 28 + line.gap;
            } else {
                height += line.type === 'divider' ? 28 : 36;
            }
        });
        height += 45;
        canvas.width = width;
        canvas.height = height;
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, width, height);
        context.fillStyle = '#1d4933';
        context.fillRect(0, 0, width, 185);

        let y = 62;
        lines.forEach(line => {
            if (line.type === 'text') {
                context.font = line.font;
                context.fillStyle = line.color;
                line.lines.forEach(text => {
                    context.fillText(text, padding, y);
                    y += 28;
                });
                y += line.gap;
            } else if (line.type === 'divider') {
                y += 12;
                context.strokeStyle = '#dce3db';
                context.setLineDash([8, 6]);
                context.beginPath();
                context.moveTo(padding, y);
                context.lineTo(width - padding, y);
                context.stroke();
                context.setLineDash([]);
                y += 20;
            } else {
                const font = line.bold ? '700 19px Arial' : '16px Arial';
                context.font = font;
                context.fillStyle = line.bold ? '#1d4933' : '#546257';
                context.fillText(line.label, padding, y);
                context.textAlign = 'right';
                context.fillText(line.value, width - padding, y);
                context.textAlign = 'left';
                y += 34;
            }
        });
    }

    function orderReceiptBlob() {
        return new Promise((resolve, reject) => {
            document.getElementById('order-receipt-image').toBlob(blob => {
                if (blob) resolve(blob);
                else reject(new Error('No se pudo generar la imagen del comprobante.'));
            }, 'image/png');
        });
    }

    function downloadOrderReceipt(blob) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `pedido-${lastOrderReceipt.number}.png`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    async function shareOrderReceipt() {
        const hint = document.getElementById('receipt-share-hint');
        const button = document.getElementById('share-order-receipt');
        button.disabled = true;
        try {
            const blob = await orderReceiptBlob();
            const file = new File([blob], `pedido-${lastOrderReceipt.number}.png`, {type: 'image/png'});
            if (!navigator.share || !navigator.canShare?.({files: [file]})) {
                downloadOrderReceipt(blob);
                hint.textContent = 'La imagen se descargó. Adjuntala al mensaje de WhatsApp para enviarla al negocio.';
                return;
            }
            await navigator.share({
                files: [file],
                title: `Pedido #${lastOrderReceipt.number}`,
                text: `Comprobante del pedido #${lastOrderReceipt.number}. Selecciona el chat de WhatsApp del negocio para compartirlo.`,
            });
        } catch (error) {
            if (error.name !== 'AbortError') {
                try {
                    downloadOrderReceipt(await orderReceiptBlob());
                    hint.textContent = 'No se pudo abrir el menú para compartir. La imagen se descargó para que puedas adjuntarla en WhatsApp.';
                } catch (fallbackError) {
                    hint.textContent = fallbackError.message || error.message || 'No se pudo generar el comprobante.';
                }
                window.app.toast(hint.textContent);
            }
        } finally {
            button.disabled = false;
        }
    }

    function showOrderReceipt(order) {
        lastOrderReceipt = order;
        drawOrderReceipt(order);
        const dialog = document.getElementById('customer-receipt-dialog');
        const whatsappLink = document.getElementById('send-order-whatsapp');
        let phone = (menuData.whatsapp || '').replace(/\D/g, '');
        if (phone.length === 10) phone = `57${phone}`;
        const hint = document.getElementById('receipt-share-hint');
        hint.textContent = phone
            ? `El botón de WhatsApp abre el chat del negocio (+${phone}) con el detalle listo para enviar. Usa “Compartir imagen” para adjuntar el comprobante PNG.`
            : 'Descarga la imagen para compartirla. El envío directo por WhatsApp no está disponible porque falta configurar el número del negocio.';
        whatsappLink.hidden = !phone;
        if (phone) {
            whatsappLink.href = `https://wa.me/${phone}?text=${encodeURIComponent(orderWhatsAppMessage(order))}`;
        }
        dialog.showModal();
    }

    function openCart() { drawer.classList.add('is-open'); drawer.setAttribute('aria-hidden', 'false'); }
    function closeCart() { drawer.classList.remove('is-open'); drawer.setAttribute('aria-hidden', 'true'); }
    document.querySelector('.cart-open').addEventListener('click', openCart);
    drawer.querySelectorAll('[data-close-cart]').forEach(button => button.addEventListener('click', closeCart));
    tabs.addEventListener('click', event => {
        const button = event.target.closest('[data-category]');
        if (!button) return;
        activeCategory = button.dataset.category;
        renderTabs(); renderProducts();
    });
    grid.addEventListener('click', event => {
        const button = event.target.closest('[data-add]');
        if (!button) return;
        const product = menuData.categories.flatMap(category => category.products).find(item => String(item.id) === button.dataset.add);
        const instructions = grid.querySelector(`[data-observation-of="${product.id}"]`).value.trim();
        const extras = [...grid.querySelectorAll(`[data-extra-of="${product.id}"]:checked`)]
            .map(input => product.extras.find(extra => String(extra.id) === input.value)).filter(Boolean);
        const extraIds = extras.map(extra => extra.id).sort((a, b) => a - b);
        const key = `${product.id}:${extraIds.join(',')}:${instructions}`;
        const existing = cart.get(key);
        cart.set(key, {
            ...product, id: product.id, key, extras, extraIds, instructions,
            extraTotal: extras.reduce((sum, extra) => sum + Number(extra.price), 0),
            quantity: Math.min((existing?.quantity || 0) + 1, 30)
        });
        grid.querySelectorAll(`[data-extra-of="${product.id}"]`).forEach(input => { input.checked = false; });
        grid.querySelector(`[data-observation-of="${product.id}"]`).value = '';
        renderCart(); window.app.toast(`${product.name} agregado`);
    });
    document.getElementById('cart-items').addEventListener('click', event => {
        const button = event.target.closest('[data-qty]');
        if (!button) return;
        const row = cart.get(button.dataset.qty);
        row.quantity += Number(button.dataset.delta);
        if (row.quantity <= 0) cart.delete(row.key);
        renderCart();
    });
    document.getElementById('order-kind').addEventListener('change', () => {
        const isTable = document.getElementById('order-kind').value === 'table';
        const isDelivery = document.getElementById('order-kind').value === 'delivery';
        document.getElementById('table-field').classList.toggle('is-hidden', !isTable);
        document.getElementById('address-field').classList.toggle('is-hidden', !isDelivery);
        document.querySelector('[name=table_number]').required = isTable;
        document.querySelector('[name=address]').required = isDelivery;
        document.querySelector('[name=phone]').required = isDelivery;
        document.querySelector('[name=phone]').placeholder = isDelivery ? 'Obligatorio para domicilio' : 'Opcional';
        renderCart();
    });
    document.getElementById('customer-receipt-dialog').querySelectorAll('[data-close-customer-receipt]')
        .forEach(button => button.addEventListener('click', () =>
            document.getElementById('customer-receipt-dialog').close()
        ));
    document.getElementById('download-order-receipt').addEventListener('click', async () => {
        try {
            downloadOrderReceipt(await orderReceiptBlob());
        } catch (error) {
            window.app.toast(error.message);
        }
    });
    document.getElementById('share-order-receipt').addEventListener('click', shareOrderReceipt);

    document.getElementById('checkout-form').addEventListener('submit', async event => {
        event.preventDefault();
        const checkoutForm = event.currentTarget;
        const message = document.getElementById('checkout-message');
        const button = checkoutForm.querySelector('[type=submit]');
        if (!cart.size) { message.textContent = 'Agrega al menos un producto para continuar.'; return; }
        const form = new FormData(checkoutForm);
        const data = Object.fromEntries(form.entries());
        data.items = [...cart.values()].map(row => ({
            product_id: row.id,
            quantity: row.quantity,
            extra_ids: row.extraIds,
            instructions: row.instructions,
        }));
        button.disabled = true; button.textContent = 'Enviando pedido...'; message.textContent = '';
        try {
            const result = await window.app.request('/api/orders/', { method: 'POST', body: JSON.stringify(data) });
            cart.clear(); renderCart(); checkoutForm.reset();
            document.getElementById('order-kind').dispatchEvent(new Event('change', { bubbles: true }));
            message.innerHTML = `¡Pedido recibido! Tu número es <strong>${window.app.escape(result.order.number)}</strong>. Ya puedes ver y compartir tu comprobante.`;
            closeCart();
            showOrderReceipt(result.order);
            window.app.toast('Pedido enviado correctamente');
        } catch (error) { message.textContent = error.message; }
        finally { button.disabled = false; button.innerHTML = 'Confirmar pedido <span>→</span>'; }
    });
    document.getElementById('order-kind').dispatchEvent(new Event('change'));
    loadMenu();
})();