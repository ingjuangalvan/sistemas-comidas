(() => {
    const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    window.app = {
        token,
        money(value) {
            const amount = Number(value || 0);
            return `${window.BUSINESS_CURRENCY_SYMBOL || '$'}${new Intl.NumberFormat('es-CO', {
                maximumFractionDigits: Number.isInteger(amount) ? 0 : 2,
            }).format(amount)}`;
        },
        async request(url, options = {}) {
            const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': token, ...(options.headers || {}) };
            const response = await fetch(url, { ...options, headers });
            const body = await response.text();
            let data = {};
            try {
                data = body ? JSON.parse(body) : {};
            } catch {
                if (response.ok) {
                    throw new Error('El servidor respondió en un formato inesperado.');
                }
            }
            if (!response.ok) {
                throw new Error(data.error || `Error del servidor (${response.status}). Inténtalo de nuevo o consulta los registros.`);
            }
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