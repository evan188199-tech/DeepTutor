"""CLI commands for setting up the mobile PWA companion."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid

from rich.console import Console
import typer

console = Console()


def register(app: typer.Typer) -> None:
    """Register the companion command group."""
    companion_app = typer.Typer(help="Manage the iPad and iPhone PWA companion setup.")

    @companion_app.command("setup")
    def setup_companion(
        port: int = typer.Option(8001, "--port", help="Local DeepTutor server port."),
    ) -> None:
        """Expose DeepTutor through Tailscale HTTPS and print a pairing QR code."""
        if shutil.which("tailscale") is None:
            console.print("[red]Error:[/] Tailscale not found. Install Tailscale first.")
            raise typer.Exit(1)

        try:
            completed = subprocess.run(
                ["tailscale", "status", "--json"],
                check=True,
                capture_output=True,
                text=True,
            )
            status = json.loads(completed.stdout)
            self_status = status.get("Self") or {}
            tailscale_ips = self_status.get("TailscaleIPs") or []
            if not tailscale_ips:
                raise ValueError("No Tailscale IP is assigned to this device")
            tailscale_ip = str(tailscale_ips[0])
            tailnet_name = str(self_status.get("DNSName") or "").rstrip(".")
            if not tailnet_name:
                tailnet_name = tailscale_ip
        except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            console.print(f"[red]Error:[/] Could not read Tailscale status: {exc}")
            raise typer.Exit(1) from exc

        console.print(f"Tailscale IP: [bold]{tailscale_ip}[/]")
        console.print(f"Tailnet DNS: [bold]{tailnet_name}[/]")

        try:
            subprocess.run(
                [
                    "tailscale",
                    "serve",
                    "--bg",
                    "https",
                    "/",
                    f"http://127.0.0.1:{port}",
                ],
                check=True,
            )
        except subprocess.CalledProcessError:
            console.print("[yellow]Warning:[/] Tailscale serve failed. Check its permissions.")

        import qrcode

        pairing_code = uuid.uuid4().hex[:12].upper()
        pairing_url = f"https://{tailnet_name}/companion/pair?code={pairing_code}"
        qr_code = qrcode.QRCode(border=2)
        qr_code.add_data(pairing_url)
        qr_code.make()
        qr_code.print_ascii()

        console.print(f"Pairing URL: [bold]{pairing_url}[/]")
        console.print(
            "Bind DeepTutor to loopback when exposing it through Tailscale: "
            "deeptutor serve --host 127.0.0.1."
        )

    app.add_typer(companion_app, name="companion")
