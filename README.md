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
- Carta de solo lectura para compartir con QR: http://127.0.0.1:8000/carta/
- Panel: http://127.0.0.1:8000/login/
- En “Productos” del panel puedes descargar el QR de la carta pública; al generarlo en el dominio publicado, el código apunta a ese mismo dominio. La página QR es de solo lectura y refleja los productos y precios vigentes de la carta de pedidos.
- Gestión de productos y categorías: http://127.0.0.1:8000/django-admin/. En “Productos de la carta” puedes crear, editar, eliminar productos sin ventas, cambiar precio, disponibilidad y existencias, o usar las acciones “Marcar como agotados” / “Volver a ofrecer”. La acción “Eliminar” aparece en todos los productos: los que tienen ventas se retiran de la carta y conservan el historial de pedidos; los que no tienen ventas se borran definitivamente. Los adicionales se editan dentro de la ficha del producto.

El primer usuario creado con `createsuperuser` es el administrador del sistema. Usa una contraseña exclusiva y guárdala de forma segura.

## Funciones

- Pedidos para las mesas 1 a 10, para llevar y domicilio, con validación de mesa/dirección tanto en la carta como en la API.
- Estados de pedido: recibido, en preparación, preparado, entregado y cancelado; el panel y la cocina se actualizan cada 12 segundos. La cocina consulta por separado todos los pedidos activos, sin que los filtros de fecha del historial puedan ocultarlos. Al cancelar un pedido se pide un motivo obligatorio, que queda guardado y visible en la pestaña de pedidos cancelados.
- Los pedidos recibidos y pendientes de pago se pueden editar o eliminar por completo. Al iniciar la preparación o registrar el pago, la edición y eliminación quedan bloqueadas.
- Los productos de la categoría “Bebidas” controlan existencias por unidades. Al elegir esa categoría en “Agregar producto” o “Editar”, el campo “Unidades disponibles” aparece automáticamente y es obligatorio; no requiere activar otro control. El inventario se descuenta al crear el pedido; si no hay existencias configuradas o suficientes, el pedido se rechaza. Los pedidos eliminados o cancelados antes de iniciar la preparación devuelven las unidades; al cancelar después de iniciar la preparación no se reponen. Configura el conteo inicial en “Productos” antes de vender bebidas.
- Registro y agrupación de pagos por Bancolombia, Nequi, efectivo y tarjeta. Los registros históricos de transferencia u otro método se conservan etiquetados como anteriores.
- Apertura y cierre de caja con fondo inicial, ventas agrupadas por método, efectivo esperado y diferencia contra el conteo. El efectivo contado se captura por cantidad de monedas de $100, $200, $500 y $1.000 y billetes de $2.000, $5.000, $10.000, $20.000, $50.000 y $100.000; el total y desglose quedan guardados en el cierre.
- Cada cierre de caja genera una vista previa POS imprimible con horarios, responsables, efectivo, denominaciones, ventas y conciliación; los cierres anteriores también se pueden imprimir desde el historial.
- Conciliación por turno entre ventas pagadas y valores comprobados para Bancolombia, Nequi, efectivo y tarjeta. Los importes externos se comparan en valor bruto antes de comisiones; el sistema señala sobrantes o faltantes por método, total y causas posibles. Los pagos se asignan al turno según la hora real en que se registraron como pagados.
- Búsqueda de pedidos por número y filtros de rango de fechas en el panel, combinables con el filtro por estado; el historial usa paginación de servidor de 10 pedidos por página y no se limita a los pedidos recientes.
- La vista previa de impresión POS mantiene las opciones arriba del comprobante y el recibo debajo, ajustando el ancho al rollo seleccionado para evitar recortes horizontales.
- Panel de ventas del mes con base en la fecha del pago. Los informes permiten consultar hoy, semana, mes, mes anterior, todas las ventas o un rango manual; separan fecha de pedido y fecha de cobro, muestran promedio por pedido, pendientes, cancelaciones, comprobantes anulados, cobros por medio y canal, ventas por día o mes, productos más/menos vendidos e inventario controlado. El CSV incluye las fechas del pedido y del pago, y los motivos de cancelación/anulación. Los comprobantes anulados se informan aparte, sin restar cobros ni suponer reembolsos.
- Registro de gastos por fecha, valor y categoría (compras, pago a empleados, remodelación y servicios pagados), con descripción obligatoria para remodelaciones. Los gastos se pueden filtrar por fechas y categoría, corregir o eliminar; se conserva el usuario que los registró.
- Informe de beneficios por rango de meses, que compara mes a mes las ventas pagadas con los gastos registrados y muestra el beneficio estimado total y por mes, además de gastos agrupados por categoría. El beneficio no incluye costos que no se hayan registrado en el sistema.
- Comprobantes internos no fiscales con diseño POS: solo se generan cuando el panel registra el pago; se puede imprimir por separado la comanda de cocina y el comprobante con datos del cliente, productos, observaciones, precios, totales y estado/método de pago. Para efectivo se registra cuánto entregó el cliente y el vuelto calculado, tanto en el comprobante persistido como en su impresión. La anulación pide un motivo y se registra inmediatamente con el usuario y la fecha, conservando el comprobante en el historial; no procesa reembolsos. Los cobros de facturas anuladas siguen apareciendo como cobros registrados y se identifican aparte en informes, no se descuentan como si se hubiera devuelto el dinero.
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
$env:BUSINESS_WHATSAPP = "321*****"
```

El impuesto se expresa como porcentaje y la tarifa de domicilio como importe fijo. Usa `BUSINESS_ORDERS_OPEN=0` para pausar pedidos y `1` para volver a recibirlos; `BUSINESS_HOURS_LABEL` es solo el horario informativo visible en la carta. Ajusta la zona horaria a la ubicación del negocio. Si el país exige facturación fiscal, consulta primero los requisitos locales antes de usar el sistema para emitir comprobantes.


## WhatsApp Business

El webhook está en `/webhooks/whatsapp/`. Para activarlo, configura `PUBLIC_SITE_URL`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` y `WHATSAPP_APP_SECRET`; registra la URL pública HTTPS y el mismo token de verificación en la configuración de Webhooks de Meta. El webhook verifica la firma SHA-256 de Meta y responde al mensaje entrante con un enlace a la carta. No se incluyen credenciales reales ni se simula el envío si faltan.

El teléfono `BUSINESS_WHATSAPP` configura el chat del negocio para que el cliente envíe el detalle de su pedido. Por defecto se usa el número colombiano `+57 324 581 3427`; puedes reemplazarlo con esa variable de entorno. El botón de WhatsApp abre el chat con el número del negocio y el detalle listo para enviar. El cliente también puede compartir el comprobante PNG desde el menú de compartir del dispositivo o descargarlo para adjuntarlo en WhatsApp. Desde cada pedido del panel se puede imprimir la comanda de cocina; el comprobante POS solo se habilita después de registrar el pago. Son comprobantes internos no fiscales.

En local, WhatsApp/Meta no puede acceder a `localhost`; durante la integración se necesita desplegar el sitio o exponer temporalmente una URL HTTPS de desarrollo. La API oficial requiere una cuenta de WhatsApp Business Platform y puede tener costos o límites definidos por Meta.

## Datos y respaldos

En desarrollo se usa SQLite en `db.sqlite3`. Haz una copia del archivo con la aplicación detenida y guárdala en un lugar protegido. Antes de producción, configura PostgreSQL, HTTPS, `DJANGO_DEBUG=0`, una clave secreta nueva y copias automáticas fuera del servidor. En producción Django fuerza HTTPS, activa cookies seguras, requiere SSL para PostgreSQL y envía HSTS por un año; se limita el host permitido al dominio del servicio. No se activa HSTS para subdominios porque el dominio compartido `onrender.com` no está bajo el control del negocio.

Las contraseñas se almacenan con hash de Django, no como texto ni con cifrado reversible. Los campos de pedidos (por ejemplo, teléfono y dirección) no tienen cifrado campo a campo en la aplicación; protege la base de datos y los respaldos con las opciones de cifrado del proveedor. Añadir cifrado propio requiere administrar y respaldar claves por separado, así como migrar y probar búsquedas y exportaciones. No publiques la base de datos, secretos ni el archivo `.env`.

## Prueba gratuita en Render

El archivo `render.yaml` configura un servicio web Django y una base de datos PostgreSQL en el plan gratuito. Para desplegarlo, crea una cuenta en Render, conecta GitHub y crea un Blueprint desde el repositorio `ingjuangalvan/sistemas-comidas`; selecciona `render.yaml` y aplica el Blueprint. Render generará `DJANGO_SECRET_KEY`, conectará la base de datos y publicará la carta en una dirección `.onrender.com`. Para el usuario administrador sin acceso a Shell, agrega temporalmente al servicio las variables privadas `DJANGO_BOOTSTRAP_ADMIN_USERNAME`, `DJANGO_BOOTSTRAP_ADMIN_EMAIL` y `DJANGO_BOOTSTRAP_ADMIN_PASSWORD` desde Environment; al siguiente despliegue, `bootstrap_admin` creará la cuenta solo si aún no existe. Usa una contraseña fuerte, no la compartas ni la agregues al repositorio y elimina las tres variables de Environment después de confirmar el despliegue.

Esta configuración es solo para pruebas: Render puede suspender el servicio web gratuito cuando no recibe tráfico y su PostgreSQL gratuito vence a los 30 días; además, el almacenamiento local del servicio no es persistente. No registres pedidos reales ni dependas de conservar datos hasta migrar a un plan y base de datos persistentes.

## Validación

```powershell
python manage.py check
python manage.py test orders
```

## Alcance pendiente para producción

Esta primera versión no sustituye un sistema fiscal certificado ni procesa pagos en línea. La carta puede recibir solicitudes, pero el método elegido se confirma manualmente desde el panel. Horarios programables, inventario por ingredientes y QR individuales para cada mesa se pueden integrar cuando se definan las reglas del negocio.
