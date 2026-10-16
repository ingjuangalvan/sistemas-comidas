# Sistema de pedidos y caja

Aplicación web en Django para administrar una carta de comidas, recibir pedidos, preparar comandas, registrar pagos y hacer cierres de caja. La carta pública funciona desde el celular; el panel privado requiere un usuario administrador.

Los comprobantes que aparecen en esta versión son **recibos internos no fiscales**. La factura electrónica oficial depende del país, su autoridad tributaria y la integración autorizada correspondiente.

## Requisitos

- Python 3.10 o superior.
- Windows PowerShell, macOS o Linux.

## Puesta en marcha en Windows

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

Al iniciar, el servidor abre el navegador en la pantalla de inicio de sesión. Para iniciar sin abrir una pestaña, ejecuta `python manage.py runserver --nobrowser`.

Si PowerShell no encuentra `py`, usa la ruta de Python instalada en el equipo. En macOS/Linux activa el entorno con `source .venv/bin/activate`.

- Carta pública: http://127.0.0.1:8000/
- Panel: http://127.0.0.1:8000/login/
- Gestión de productos y categorías: http://127.0.0.1:8000/django-admin/. En “Productos de la carta” puedes crear, editar, eliminar productos sin ventas, cambiar precio y disponibilidad, o usar las acciones “Marcar como agotados” / “Volver a ofrecer”. La acción “Eliminar” aparece en todos los productos: los que tienen ventas se retiran de la carta y conservan el historial de pedidos; los que no tienen ventas se borran definitivamente. Los adicionales se editan dentro de la ficha del producto.

El primer usuario creado con `createsuperuser` es el administrador del sistema. Usa una contraseña exclusiva y guárdala de forma segura.

## Funciones

- Pedidos de mesa, para llevar y domicilio, con validación de mesa/dirección.
- Estados de pedido: recibido, en preparación, preparado, entregado y cancelado; el panel y la cocina se actualizan cada 12 segundos.
- Registro y agrupación de pagos por Bancolombia, Nequi, efectivo y tarjeta. Los registros históricos de transferencia u otro método se conservan etiquetados como anteriores.
- Apertura y cierre de caja con fondo inicial, ventas agrupadas por método, efectivo esperado y diferencia contra el conteo. El efectivo contado se captura por cantidad de monedas de $100, $200, $500 y $1.000 y billetes de $2.000, $5.000, $10.000, $20.000, $50.000 y $100.000; el total y desglose quedan guardados en el cierre.
- Cada cierre de caja genera una vista previa POS imprimible con horarios, responsables, efectivo, denominaciones, ventas y conciliación; los cierres anteriores también se pueden imprimir desde el historial.
- Conciliación por turno entre ventas pagadas y valores comprobados para Bancolombia, Nequi, efectivo y tarjeta. Los importes externos se comparan en valor bruto antes de comisiones; el sistema señala sobrantes o faltantes por método, total y causas posibles. Los pagos se asignan al turno según la hora real en que se registraron como pagados.
- Búsqueda de pedidos por número y filtros de rango de fechas en el panel, combinables con el filtro por estado; los criterios consultan también el historial más allá de los 100 pedidos recientes.
- La vista previa de impresión POS mantiene las opciones arriba del comprobante y el recibo debajo, ajustando el ancho al rollo seleccionado para evitar recortes horizontales.
- Informes por rango de fechas, productos más vendidos y descarga CSV.
- Comprobantes internos no fiscales con diseño POS: el cliente puede compartir su orden como imagen; en el panel se puede imprimir por separado la comanda de cocina y la factura POS con datos del cliente, productos, observaciones, precios, totales y estado/método de pago.
- La impresión abre primero una vista previa centrada, sin mostrar automáticamente el diálogo del navegador; permite elegir el ancho de papel térmico POS de 58 mm u 80 mm e iniciar la impresión manualmente. Configura el mismo ancho en las preferencias de papel de la impresora POS.
- En pedidos a domicilio son obligatorios el nombre, la dirección y el teléfono; para pedidos a mesa son obligatorios el nombre y el número de mesa. Cada producto permite añadir una observación que se conserva en la orden y aparece en la comanda y factura POS.
- Registro de usuario y hora en los cambios de estado. Los cierres guardados se conservan como historial.
- Extras con precio configurables por producto; la comanda conserva el precio y nombre elegidos aunque el catálogo cambie después.
- Configuración de nombre, moneda, impuesto, zona horaria, tarifa y teléfono de domicilio mediante variables de entorno.
- Pausa de pedidos en línea y texto de horarios configurables sin retirar la carta pública.
- La carta solo acepta pedidos si hay una caja abierta; al cerrar el turno se bloquean los nuevos pedidos hasta la siguiente apertura.
- Enlace de WhatsApp y webhook verificado para responder a mensajes entrantes con el enlace público de la carta.

## Configuración del negocio

Copia `.env.example` a `.env` y define las variables en el entorno antes de iniciar Django. Django no carga `.env` automáticamente, por lo que en Windows puedes establecerlas en la sesión de PowerShell, por ejemplo:

```powershell
$env:BUSINESS_NAME = "Mi restaurante"
$env:BUSINESS_CURRENCY = "COP"
$env:BUSINESS_CURRENCY_SYMBOL = "$"
$env:BUSINESS_TAX_RATE = "0"
$env:BUSINESS_DELIVERY_FEE = "5000"
$env:BUSINESS_HOURS_LABEL = "Todos los días, 12:00 a 22:00"
$env:BUSINESS_ORDERS_OPEN = "1"
$env:BUSINESS_WHATSAPP = "573245813427"
```

El impuesto se expresa como porcentaje y la tarifa de domicilio como importe fijo. Usa `BUSINESS_ORDERS_OPEN=0` para pausar pedidos y `1` para volver a recibirlos; `BUSINESS_HOURS_LABEL` es solo el horario informativo visible en la carta. Ajusta la zona horaria a la ubicación del negocio. Si el país exige facturación fiscal, consulta primero los requisitos locales antes de usar el sistema para emitir comprobantes.

## WhatsApp Business

El webhook está en `/webhooks/whatsapp/`. Para activarlo, configura `PUBLIC_SITE_URL`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` y `WHATSAPP_APP_SECRET`; registra la URL pública HTTPS y el mismo token de verificación en la configuración de Webhooks de Meta. El webhook verifica la firma SHA-256 de Meta y responde al mensaje entrante con un enlace a la carta. No se incluyen credenciales reales ni se simula el envío si faltan.

El teléfono `BUSINESS_WHATSAPP` configura el chat del negocio para que el cliente envíe el detalle de su pedido. Por defecto se usa el número colombiano `+57 324 581 3427`; puedes reemplazarlo con esa variable de entorno. El botón de WhatsApp abre el chat con el número del negocio y el detalle listo para enviar. El cliente también puede compartir el comprobante PNG desde el menú de compartir del dispositivo o descargarlo para adjuntarlo en WhatsApp. Desde cada pedido del panel se pueden imprimir por separado la comanda de cocina y la factura POS con precios y datos del cliente; después de registrar un pago también se ofrece imprimirla. Son comprobantes internos no fiscales.

En local, WhatsApp/Meta no puede acceder a `localhost`; durante la integración se necesita desplegar el sitio o exponer temporalmente una URL HTTPS de desarrollo. La API oficial requiere una cuenta de WhatsApp Business Platform y puede tener costos o límites definidos por Meta.

## Datos y respaldos

En desarrollo se usa SQLite en `db.sqlite3`. Haz una copia del archivo con la aplicación detenida y guárdala en un lugar protegido. Antes de producción, configura PostgreSQL, HTTPS, `DJANGO_DEBUG=0`, una clave secreta nueva y copias automáticas fuera del servidor. No publiques la base de datos, secretos ni el archivo `.env`.

## Validación

```powershell
python manage.py check
python manage.py test orders
```

## Alcance pendiente para producción

Esta primera versión no sustituye un sistema fiscal certificado ni procesa pagos en línea. La carta puede recibir solicitudes, pero el método elegido se confirma manualmente desde el panel. Horarios programables, inventario por ingredientes y el QR de cada mesa se pueden integrar cuando se definan las reglas del negocio.