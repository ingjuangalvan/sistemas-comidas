import webbrowser
from threading import Timer

from django.contrib.staticfiles.management.commands.runserver import (
    Command as StaticFilesRunserverCommand,
)


class Command(StaticFilesRunserverCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--nobrowser",
            action="store_false",
            dest="open_browser",
            default=True,
            help="Do not open the login page in a browser when the server starts.",
        )

    def handle(self, *args, **options):
        self.open_browser = options["open_browser"]
        super().handle(*args, **options)

    def on_bind(self, server_port):
        super().on_bind(server_port)
        if not self.open_browser:
            return

        host = self.addr
        if host in {"", "0", "0.0.0.0", "::"}:
            host = "127.0.0.1"
        elif ":" in host:
            host = f"[{host}]"
        url = f"{self.protocol}://{host}:{server_port}/login/"
        timer = Timer(0.5, self._open_browser, args=(url,))
        timer.daemon = True
        timer.start()

    def _open_browser(self, url):
        try:
            if not webbrowser.open(url):
                self.stderr.write(
                    self.style.WARNING(
                        f"No se pudo abrir el navegador automáticamente. "
                        f"Visita {url}"
                    )
                )
        except (OSError, webbrowser.Error) as error:
            self.stderr.write(
                self.style.WARNING(
                    f"No se pudo abrir el navegador automáticamente: {error}. "
                    f"Visita {url}"
                )
            )
