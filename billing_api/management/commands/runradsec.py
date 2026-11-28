"""Run the application-native RadSec listener for Railway TCP Proxy."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Start the TLS/TCP RadSec server for MikroTik PPPoE and Hotspot"

    def add_arguments(self, parser):
        parser.add_argument("--host", default=None, help="TLS bind address")
        parser.add_argument("--port", type=int, default=None, help="TLS listen port")

    def handle(self, *args, **options):
        from billing_api.radius_server import run_radsec_server

        self.stdout.write("Starting native RadSec server...")
        try:
            run_radsec_server(host=options["host"], port=options["port"])
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nRadSec server stopped."))
