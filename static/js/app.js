(() => {
    const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    window.app = {
        token,
        money(value) {
            const amount = Number(value || 0);
            return `${window.BUSINESS_CURRENCY_SYMBOL || '$'}${new Intl.NumberFormat('es-CO', { maximumFractionDigits: 0 }).format(amount)}`;
        },
        async request(url, options = {}) {
            const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token, ...(options.headers || {}) };
            const response = await fetch(url, { ...options, headers });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.error || 'No se pudo completar la solicitud.');
            return data;
        },
        toast(message) {
            const toast = document.getElementById('toast');
            if (!toast) return;
            toast.textContent = message;
            toast.classList.add('is-visible');
            clearTimeout(window.toastTimeout);
            window.toastTimeout = setTimeout(() => toast.classList.remove('is-visible'), 2600);
        },
        escape(value) {
            return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
        },
    };
})();