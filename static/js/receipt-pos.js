(() => {
    const escape = value => window.app.escape(value);
    const dateTime = value => value
        ? new Intl.DateTimeFormat('es-CO', {
            dateStyle: 'medium',
            timeStyle: 'short',
        }).format(new Date(value))
        : 'Pendiente de pago';

    function renderKitchen(order, businessName) {
        const details = [
            ['CLIENTE', order.customer_name],
            ['TELÉFONO', order.phone || 'No registrado'],
            ['TIPO', order.kind_label],
            order.table_number ? ['MESA', order.table_number] : null,
            order.address ? ['DIRECCIÓN', order.address] : null,
        ].filter(Boolean);
        const items = order.items.map((item, index) => `
            <section class="kitchen-item">
                <span class="kitchen-item-index">${String(index + 1).padStart(2, '0')}</span>
                <div class="kitchen-item-content">
                    <strong><b>${escape(item.quantity)}×</b> ${escape(item.name)}</strong>
                    ${item.extras?.length ? `<p>ADICIONALES · ${item.extras.map(extra => escape(extra.name)).join(', ')}</p>` : ''}
                    ${item.instructions ? `<p class="kitchen-instruction">NOTA · ${escape(item.instructions)}</p>` : ''}
                </div>
            </section>`).join('');
        return `
            <article class="kitchen-ticket-print">
                <header class="kitchen-ticket-header">
                    <div class="kitchen-ticket-brand"><span>ORDEN INTERNA</span><strong>${escape(businessName)}</strong></div>
                    <div class="kitchen-order-number"><small>COMANDA</small><b>#${escape(order.number)}</b></div>
                    <div class="kitchen-ticket-meta">
                        <span>${escape(order.kind_label)}${order.table_number ? ` · MESA ${escape(order.table_number)}` : ''}</span>
                        <time>${escape(dateTime(order.created_at))}</time>
                    </div>
                </header>
                <section class="kitchen-customer">
                    ${details.map(([label, value]) => `<div><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`).join('')}
                </section>
                <section class="kitchen-items">
                    <div class="kitchen-section-title"><span>PREPARAR</span><span>${order.items.length} ${order.items.length === 1 ? 'PRODUCTO' : 'PRODUCTOS'}</span></div>
                    ${items}
                </section>
                ${order.note ? `<section class="kitchen-alert"><strong>ATENCIÓN · NOTA DEL PEDIDO</strong><p>${escape(order.note)}</p></section>` : ''}
                <footer class="kitchen-ticket-footer"><span>${escape(businessName)}</span><span>COMANDA INTERNA · NO ENTREGAR AL CLIENTE</span></footer>
            </article>`;
    }

    function render(order, mode = 'sale', businessName = '') {
        const kitchen = mode === 'kitchen';
        if (kitchen) return renderKitchen(order, businessName);
        const details = [
            ['Cliente', order.customer_name],
            ['Teléfono', order.phone || 'No registrado'],
            ['Tipo', order.kind_label],
            order.table_number ? ['Mesa', order.table_number] : null,
            order.address ? ['Dirección', order.address] : null,
            ['Fecha del pedido', dateTime(order.created_at)],
            order.paid_at ? ['Fecha de pago', dateTime(order.paid_at)] : null,
            ['Medio de pago', order.payment_method_label],
            ['Pago', order.payment_status_label],
        ].filter(Boolean);
        const itemRows = order.items.map(item => `
            <section class="item">
                <div class="item-line"><strong>${escape(item.quantity)} × ${escape(item.name)}</strong><strong>${window.app.money(item.line_total)}</strong></div>
                <p class="item-note">Precio unitario: ${window.app.money(item.price)}</p>
                ${item.extras?.length ? `<p class="item-note">Adicionales: ${item.extras.map(extra => `${escape(extra.name)} (+${window.app.money(extra.price)})`).join(', ')}</p>` : ''}
                ${item.instructions ? `<p class="item-note">Instrucciones: ${escape(item.instructions)}</p>` : ''}
            </section>`).join('');
        const notes = order.note ? `<section class="order-note"><strong>Nota para cocina</strong><p>${escape(order.note)}</p></section>` : '';
        const total = `
            <div class="amount-row"><span>Subtotal</span><span>${window.app.money(order.subtotal)}</span></div>
            ${Number(order.delivery_fee) ? `<div class="amount-row"><span>Domicilio</span><span>${window.app.money(order.delivery_fee)}</span></div>` : ''}
            ${Number(order.tax) ? `<div class="amount-row"><span>Impuestos</span><span>${window.app.money(order.tax)}</span></div>` : ''}
            <div class="amount-row grand-total"><strong>TOTAL</strong><strong>${window.app.money(order.total)}</strong></div>`;
        return `
            <article class="pos-receipt ${kitchen ? 'pos-kitchen-receipt' : ''}">
                <header class="pos-receipt-brand">
                    <strong>${escape(businessName)}</strong>
                    <span>FACTURA POS · COMPROBANTE INTERNO</span>
                    <b>PEDIDO #${escape(order.number)}</b>
                </header>
                <dl class="pos-receipt-details">${details.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>
                <div class="pos-receipt-items">${itemRows}</div>
                ${total}
                ${notes}
                <footer class="pos-receipt-footer">Gracias por tu compra · Comprobante interno no fiscal</footer>
            </article>`;
    }

    function openPrintWindow() {
        const popupWidth = 460;
        const popupHeight = 760;
        const screenLeft = Number.isFinite(window.screen.availLeft)
            ? window.screen.availLeft
            : 0;
        const screenTop = Number.isFinite(window.screen.availTop)
            ? window.screen.availTop
            : 0;
        const left = Math.max(
            screenLeft,
            Math.round(window.screenX + (window.outerWidth - popupWidth) / 2),
        );
        const top = Math.max(
            screenTop,
            Math.round(window.screenY + (window.outerHeight - popupHeight) / 2),
        );
        const printWindow = window.open(
            '',
            '_blank',
            `popup,width=${popupWidth},height=${popupHeight},left=${left},top=${top}`,
        );
        if (!printWindow) return false;
        printWindow.opener = null;
        return printWindow;
    }

    function printCashCloseContent(session, businessName) {
        const signedMoney = value => {
            const amount = Number(value || 0);
            return amount > 0
                ? `+${window.app.money(amount)}`
                : amount < 0
                    ? `-${window.app.money(Math.abs(amount))}`
                    : window.app.money(0);
        };
        const dateTime = value => value
            ? new Intl.DateTimeFormat('es-CO', {dateStyle: 'medium', timeStyle: 'short'}).format(new Date(value))
            : '—';
        const reconciliation = session.reconciliation;
        const methodRows = reconciliation.methods.map(method => `
            <div class="cash-row">
                <strong>${escape(method.method)}</strong>
                <span>Esperado ${window.app.money(method.expected)}</span>
                <span>Comprobado ${method.actual === null ? 'Pendiente' : window.app.money(method.actual)}</span>
                <b>${method.difference === null ? 'Pendiente' : signedMoney(method.difference)}</b>
            </div>`).join('');
        const denominationRows = Object.entries(session.counted_denominations || {})
            .filter(([, count]) => Number(count) > 0)
            .map(([denomination, count]) => `
                <div class="cash-row">
                    <span>${escape(count)} × ${window.app.money(denomination)}</span>
                    <b>${window.app.money(Number(denomination) * Number(count))}</b>
                </div>`).join('') || '<p class="cash-muted">Sin desglose de denominaciones.</p>';
        const paymentsRows = Object.entries(session.payment_totals || {})
            .map(([method, amount]) => `
                <div class="cash-row"><span>${escape(method)}</span><b>${window.app.money(amount)}</b></div>`)
            .join('') || '<p class="cash-muted">No hubo ventas pagadas en el turno.</p>';
        const statusLabel = reconciliation.status === 'matched'
            ? 'CUADRA'
            : reconciliation.status === 'surplus'
                ? 'SOBRANTE'
                : reconciliation.status === 'shortage' ? 'FALTANTE' : 'PENDIENTE';
        return `
            <article class="cash-close-receipt">
                <header class="cash-header">
                    <span>CIERRE DE CAJA · TURNO #${escape(session.id)}</span>
                    <strong>${escape(businessName)}</strong>
                </header>
                <section>
                    <h2>Resumen del turno</h2>
                    <div class="cash-row"><span>Apertura</span><b>${dateTime(session.opened_at)}</b></div>
                    <div class="cash-row"><span>Cierre</span><b>${dateTime(session.closed_at)}</b></div>
                    <div class="cash-row"><span>Abrió</span><b>${escape(session.opened_by || '—')}</b></div>
                    <div class="cash-row"><span>Cerró</span><b>${escape(session.closed_by || '—')}</b></div>
                </section>
                <section>
                    <h2>Resumen de efectivo</h2>
                    <div class="cash-row"><span>Fondo inicial</span><b>${window.app.money(session.opening_amount)}</b></div>
                    <div class="cash-row"><span>Efectivo esperado</span><b>${window.app.money(session.expected_cash)}</b></div>
                    <div class="cash-row"><span>Efectivo contado</span><b>${window.app.money(session.counted_amount)}</b></div>
                    <div class="cash-row cash-total"><strong>Diferencia de efectivo</strong><strong>${signedMoney(session.difference)}</strong></div>
                    <h3>Desglose contado</h3>
                    ${denominationRows}
                </section>
                <section>
                    <h2>Ventas por medio de pago</h2>
                    ${paymentsRows}
                </section>
                <section>
                    <h2>Conciliación de ventas · ${statusLabel}</h2>
                    ${methodRows}
                    <div class="cash-row cash-total"><strong>Ventas esperadas</strong><strong>${window.app.money(reconciliation.expected_sales)}</strong></div>
                        <div class="cash-row"><span>Ventas comprobadas</span><b>${reconciliation.actual_sales === null ? 'Pendiente' : window.app.money(reconciliation.actual_sales)}</b></div>
                        <div class="cash-row"><span>Diferencia total</span><b>${reconciliation.difference === null ? 'Pendiente' : signedMoney(reconciliation.difference)}</b></div>
                    <p class="cash-muted">${escape(reconciliation.reason)}</p>
                </section>
                <footer>Conciliado ${dateTime(session.reconciled_at)} · ${escape(session.reconciled_by || '—')}</footer>
            </article>`;
    }

    function writeCashClosePreview(printWindow, session, businessName) {
        if (!printWindow || printWindow.closed) return false;
        const content = printCashCloseContent(session, businessName);
        printWindow.document.open();
        printWindow.document.write(`<!doctype html>
            <html lang="es"><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Cierre de caja · ${escape(session.id)}</title>
            <style>
                *{box-sizing:border-box}body{--paper-width:80mm;display:flex;flex-direction:column;align-items:center;width:100%;margin:0;padding:20px;background:#f2f3f0;color:#202720;font:12px Arial,sans-serif;overflow-x:hidden}
                .print-toolbar{position:sticky;top:0;z-index:1;display:flex;width:100%;justify-content:center;align-items:center;gap:12px;margin:-20px 0 16px;padding:12px;background:#f1f1f1;border-bottom:1px solid #bbb}
                .print-toolbar label{display:flex;align-items:center;gap:6px;font-weight:700}.print-toolbar select,.print-toolbar button{min-height:36px;padding:7px 12px;border:1px solid #555;border-radius:4px;background:#fff;color:#111;font:inherit}
                .print-toolbar button{background:#111;color:#fff;font-weight:700;cursor:pointer}
                .cash-close-receipt{width:min(100%,calc(var(--paper-width) - 8mm));padding:4mm;background:#fff;border:1px solid #aaa}
                .cash-header{padding-bottom:12px;border-bottom:1px dashed #888;text-align:center}.cash-header span,.cash-header strong{display:block}.cash-header span{font-size:9px;font-weight:700;letter-spacing:1px}.cash-header strong{margin-top:7px;font-size:18px}
                section{margin-top:13px}h2{margin:0 0 6px;padding-bottom:5px;border-bottom:1px solid #666;font-size:12px;text-transform:uppercase}h3{margin:10px 0 5px;font-size:10px;text-transform:uppercase}
                .cash-row{display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px dotted #bbb;line-height:1.35}.cash-row>*{min-width:0;overflow-wrap:anywhere}.cash-row b{text-align:right}
                .cash-total{margin-top:4px;border-top:1px solid #555;border-bottom:1px solid #555;font-weight:700}
                .cash-muted{margin:7px 0;color:#444;font-size:10px;line-height:1.4}
                footer{margin-top:14px;padding-top:8px;border-top:1px dashed #888;color:#444;font-size:9px;text-align:center}
                @page{size:80mm auto;margin:2mm}@media print{body{display:block;padding:0;background:#fff}.print-toolbar{display:none!important}.cash-close-receipt{width:100%;padding:2mm;border:0}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
            </style></head><body>
            <nav class="print-toolbar" aria-label="Opciones de impresión">
                <label for="pos-paper-width">Papel POS
                    <select id="pos-paper-width"><option value="80">80 mm</option><option value="58">58 mm</option></select>
                </label>
                <button type="button" id="start-pos-print">Imprimir en POS</button>
                <button type="button" id="close-pos-preview">Cerrar</button>
            </nav>${content}
            <script>
                const paper=document.getElementById('pos-paper-width');
                paper.addEventListener('change',()=>{const width=paper.value;document.body.style.setProperty('--paper-width',width+'mm');const page=document.querySelector('style');page.textContent=page.textContent.replace(/@page\\{size:\\d+mm auto;margin:2mm\\}/,'@page{size:'+width+'mm auto;margin:2mm}');});
                document.getElementById('start-pos-print').addEventListener('click',()=>{window.focus();window.print();});
                document.getElementById('close-pos-preview').addEventListener('click',()=>window.close());
            <\/script></body></html>`);
        printWindow.document.close();
        return true;
    }

    function printCashClose(session, businessName = '') {
        const printWindow = openPrintWindow();
        return printWindow ? writeCashClosePreview(printWindow, session, businessName) : false;
    }

    function print(order, mode, businessName = '') {
        const printWindow = openPrintWindow();
        if (!printWindow) return false;
        const heading = mode === 'kitchen' ? 'Comanda de cocina' : 'Recibo interno no fiscal';
        const printContent = mode === 'kitchen'
            ? renderKitchen(order, businessName)
            : render(order, mode, businessName);
        const printStyles = mode === 'kitchen' ? `
                body{display:flex;flex-direction:column;align-items:center;width:100%;padding:10px;background:#fff;color:#111;font:13px Arial,sans-serif}
                .kitchen-ticket-print{width:min(100%,calc(var(--paper-width) - 8mm));margin:0 auto;background:#fff;border:1px solid #777}
                .kitchen-ticket-header{display:flex;flex-direction:column;align-items:stretch;padding:14px 18px 12px;background:#fff;color:#111;border-bottom:2px solid #111;text-align:center}
                .kitchen-ticket-brand span,.kitchen-order-number small{display:block;color:#333;font-size:9px;font-weight:700;letter-spacing:1.4px}
                .kitchen-ticket-brand strong{display:block;margin-top:5px;font-size:15px;line-height:1.25}
                .kitchen-order-number{position:static;display:flex;justify-content:center;align-items:baseline;gap:7px;margin-top:8px;text-align:center}
                .kitchen-order-number small{display:inline}
                .kitchen-order-number b{display:inline;margin:0;color:#111;font-size:19px;overflow-wrap:anywhere}
                .kitchen-ticket-meta{display:flex;justify-content:space-between;gap:8px;margin-top:11px;padding-top:9px;border-top:1px solid #999;color:#111}
                .kitchen-ticket-meta span{font-weight:700;letter-spacing:.5px}.kitchen-ticket-meta time{color:#333;text-align:right;font-size:11px}
                .kitchen-customer{display:grid;grid-template-columns:1fr 1fr;gap:0 14px;padding:10px 18px;background:#fff;border-bottom:1px solid #777}
                .kitchen-customer>div{min-width:0;padding:5px 0}.kitchen-customer>div span{display:block;color:#444;font-size:9px;font-weight:700;letter-spacing:1px}
                .kitchen-customer>div strong{display:block;margin-top:3px;overflow-wrap:anywhere;font-size:12px}
                .kitchen-items{padding:12px 18px 8px}.kitchen-section-title{display:flex;justify-content:space-between;margin-bottom:4px;padding-bottom:7px;border-bottom:1px solid #777;color:#111;font-size:10px;font-weight:700;letter-spacing:1.2px}
                .kitchen-item{display:grid;grid-template-columns:24px 1fr;gap:8px;padding:10px 0;border-bottom:1px solid #bbb}
                .kitchen-item-index{padding-top:2px;color:#444;font-size:10px;font-weight:700}
                .kitchen-item-content>strong{display:block;font-size:16px;line-height:1.35}.kitchen-item-content>strong b{color:#111;font-size:18px}
                .kitchen-item-content p{margin:5px 0 0;color:#222;font-size:10px;line-height:1.45}
                .kitchen-item-content p.kitchen-instruction{padding:5px 7px;border:1px solid #777;background:#fff;color:#111;font-weight:700}
                .kitchen-alert{margin:10px 18px 14px;padding:10px;border:1px solid #555;background:#fff}
                .kitchen-alert strong{color:#111;font-size:9px;letter-spacing:1px}.kitchen-alert p{margin:5px 0 0;font-weight:700;line-height:1.45}
                .kitchen-ticket-footer{display:flex;flex-direction:column;gap:4px;padding:10px 18px;border-top:1px solid #777;background:#fff;color:#222;font-size:8px;font-weight:700;letter-spacing:1px;text-align:center}
                .kitchen-ticket-footer span:first-child{color:#111;font-size:10px}
                .print-toolbar{position:sticky;top:0;z-index:1;display:flex;width:100%;justify-content:center;align-items:center;gap:12px;margin:-10px 0 16px;padding:12px;background:#f1f1f1;border-bottom:1px solid #bbb}
                .print-toolbar label{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700}
                .print-toolbar select,.print-toolbar button{min-height:36px;padding:7px 12px;border:1px solid #555;border-radius:4px;background:#fff;color:#111;font:inherit}
                .print-toolbar button{background:#111;color:#fff;font-weight:700;cursor:pointer}
                @media print{body{display:block;padding:0;background:#fff}.print-toolbar{display:none!important}.kitchen-ticket-print{width:100%;border:0}}
        ` : `
                body{display:flex;flex-direction:column;align-items:center;width:100%;padding:20px;background:#f2f3f0;color:#202720;font:14px Arial,sans-serif}
                .pos-receipt{width:min(100%,calc(var(--paper-width) - 8mm));margin:0 auto;padding:4mm;background:#fff;border:1px solid #d8ddd7}
                .pos-receipt-brand{text-align:center;padding-bottom:18px;border-bottom:1px dashed #aab2a8}
                .pos-receipt-brand>*{display:block}.pos-receipt-brand strong{font-size:22px}.pos-receipt-brand span{margin:5px 0;color:#657166;font-size:11px;letter-spacing:1px}
                .pos-receipt-brand b{margin-top:12px;font-size:17px}
                .pos-receipt-details{margin:14px 0;padding:0}.pos-receipt-details>div{display:flex;justify-content:space-between;gap:12px;padding:4px 0}
                dt{color:#667067}dd{margin:0;text-align:right;font-weight:600}
                .item{padding:10px 0;border-top:1px dashed #d8ddd7}.item-line{display:flex;justify-content:space-between;gap:10px}
                .item-note{margin:5px 0 0;color:#526052;font-size:12px;line-height:1.45}
                .amount-row{display:flex;justify-content:space-between;gap:12px;padding:5px 0}.grand-total{margin-top:7px;padding:12px 0;border-top:2px solid #243b2b;font-size:18px}
                .order-note{margin-top:14px;padding:12px;background:#f2f5ef}.order-note p{margin:6px 0 0}
                .pos-receipt-footer{margin-top:18px;padding-top:12px;border-top:1px dashed #aab2a8;text-align:center;color:#59655c;font-size:11px}
                .print-toolbar{position:sticky;top:0;z-index:1;display:flex;width:100%;justify-content:center;align-items:center;gap:12px;margin:-20px 0 16px;padding:12px;background:#f1f1f1;border-bottom:1px solid #bbb}
                .print-toolbar label{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700}
                .print-toolbar select,.print-toolbar button{min-height:36px;padding:7px 12px;border:1px solid #555;border-radius:4px;background:#fff;color:#111;font:inherit}
                .print-toolbar button{background:#111;color:#fff;font-weight:700;cursor:pointer}
                @media print{body{display:block;padding:0;background:#fff}.print-toolbar{display:none!important}.pos-receipt{width:100%;padding:2mm;border:0}}
        `;
        const pageSizeStyle = `
            body{--paper-width:80mm;overflow-x:hidden}
            @page{size:80mm auto;margin:2mm}
            @media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
        `;
        const toolbar = `
            <nav class="print-toolbar" aria-label="Opciones de impresión">
                <label for="pos-paper-width">Papel POS
                    <select id="pos-paper-width">
                        <option value="80">80 mm</option>
                        <option value="58">58 mm</option>
                    </select>
                </label>
                <button type="button" id="start-pos-print">Imprimir en POS</button>
                <button type="button" id="close-pos-preview">Cerrar</button>
            </nav>`;
        printWindow.document.open();
        printWindow.document.write(`<!doctype html>
            <html lang="es"><head><meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>${escape(heading)} · ${escape(order.number)}</title>
            <style id="pos-print-styles">*{box-sizing:border-box}body{margin:0}${printStyles}</style>
            <style id="pos-page-size">${pageSizeStyle}</style></head><body>${toolbar}${printContent}
            <script>
                const paper=document.getElementById('pos-paper-width');
                paper.addEventListener('change',()=>{const width=paper.value;document.body.style.setProperty('--paper-width',width+'mm');document.getElementById('pos-page-size').textContent='body{--paper-width:'+width+'mm;overflow-x:hidden}@page{size:'+width+'mm auto;margin:2mm}@media print{*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}';});
                document.getElementById('start-pos-print').addEventListener('click',()=>{window.focus();window.print();});
                document.getElementById('close-pos-preview').addEventListener('click',()=>window.close());
            <\/script></body></html>`);
        printWindow.document.close();
        return true;
    }

    window.posReceipt = {
        render,
        print,
        openCashCloseWindow: openPrintWindow,
        writeCashClosePreview,
        printCashClose,
    };
})();
