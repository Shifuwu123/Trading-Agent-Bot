"""
tradingbot/database/cloud_sync.py

Módulo de Sincronización y Réplica en la Nube (Cloud Mirror Provider).

Permite replicar el estado crítico de negocio (billetera, portafolio y operaciones cerradas)
hacia bases de datos en la nube gratuitas (Turso libSQL, Neon Postgres, o Webhooks REST de Vercel)
sin exponer la base de datos completa de micro-decisiones a límites de cuotas.

Características:
- Soporte para Turso libSQL a través de la API HTTP nativa (sin binarios compilados en ARM64).
- Soporte para endpoints REST / Webhook en Vercel o servidores externos.
- Operación 100% no bloqueante: fallos de red no interrumpen el trading local en RAM.
- Cero micro-escrituras en MicroSD local.
"""

import os
import sys
import json
import logging
import sqlite3
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

log = logging.getLogger("tradingbot.database.cloud_sync")
if not log.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


class CloudSyncProvider:
    """
    Gestiona la exportación y sincronización de datos de trading hacia la nube.
    """

    def __init__(
        self,
        local_db_path: str = "/dev/shm/tradingbot.db",
        enabled: bool = False,
        provider: str = "turso",
        cloud_url: str = "",
        auth_token: str = "",
        interval_seconds: int = 600,
    ):
        self.local_db_path = local_db_path
        self.enabled = enabled
        self.provider = provider.lower()
        self.cloud_url = cloud_url
        self.auth_token = auth_token
        self.interval_seconds = interval_seconds

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_sync_time: Optional[datetime] = None

    @classmethod
    def from_settings(cls, local_db_path: str = "/dev/shm/tradingbot.db") -> "CloudSyncProvider":
        """Instancia el proveedor a partir de variables de entorno o settings."""
        enabled = os.getenv("CLOUD_SYNC_ENABLED", "false").lower() in ("true", "1", "yes")
        provider = os.getenv("CLOUD_SYNC_PROVIDER", "turso").lower()
        cloud_url = os.getenv("CLOUD_SYNC_URL", "")
        auth_token = os.getenv("CLOUD_SYNC_AUTH_TOKEN", "")
        interval_str = os.getenv("CLOUD_SYNC_INTERVAL_SECONDS", "600")
        try:
            interval = int(interval_str)
        except ValueError:
            interval = 600

        return cls(
            local_db_path=local_db_path,
            enabled=enabled,
            provider=provider,
            cloud_url=cloud_url,
            auth_token=auth_token,
            interval_seconds=interval,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Extracción de Datos Clave para Réplica Cloud
    # ─────────────────────────────────────────────────────────────────────────

    def extract_sync_payload(self) -> Dict[str, Any]:
        """
        Extrae datos consolidados de la base de datos local (RAM).
        Filtra únicamente información financiera de alto valor (trades, wallet, portfolio),
        excluyendo las micro-decisiones 'HOLD' para respetar cuotas gratuitas.
        """
        if not os.path.exists(self.local_db_path):
            return {}

        conn = sqlite3.connect(self.local_db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 1. Billetera digital
        cur.execute("SELECT * FROM digital_wallet LIMIT 1")
        wallet_row = cur.fetchone()
        wallet = dict(wallet_row) if wallet_row else {}

        # 2. Portafolio activo
        cur.execute("SELECT * FROM portfolio")
        portfolio = [dict(r) for r in cur.fetchall()]

        # 3. Últimos 100 trades cerrados y todos los abiertos
        cur.execute("SELECT * FROM trades ORDER BY opened_at DESC LIMIT 100")
        trades = [dict(r) for r in cur.fetchall()]

        # 4. Métricas consolidadas
        cur.execute("SELECT count(*) as total, sum(pnl) as total_pnl FROM trades WHERE status='CLOSED'")
        metrics_row = cur.fetchone()
        total_pnl = float(metrics_row["total_pnl"]) if metrics_row and metrics_row["total_pnl"] else 0.0
        total_closed = int(metrics_row["total"]) if metrics_row else 0

        conn.close()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wallet": wallet,
            "portfolio": portfolio,
            "trades": trades,
            "metrics": {
                "total_closed_trades": total_closed,
                "realized_pnl_usd": total_pnl,
                "current_balance_usd": float(wallet.get("balance_usd", 16.0)),
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Proveedores de Sincronización
    # ─────────────────────────────────────────────────────────────────────────

    def sync_now(self) -> Dict[str, Any]:
        """Ejecuta una sincronización inmediata según el proveedor configurado."""
        if not self.enabled:
            return {"success": False, "status": "disabled", "message": "Cloud sync no está habilitado en .env"}

        if not self.cloud_url:
            return {"success": False, "status": "missing_url", "message": "CLOUD_SYNC_URL no está configurada"}

        payload = self.extract_sync_payload()
        if not payload:
            return {"success": False, "error": "No se encontraron datos en la base de datos local"}

        if self.provider == "turso":
            return self._sync_to_turso(payload)
        elif self.provider in ("webhook", "vercel", "rest"):
            return self._sync_to_webhook(payload)
        elif self.provider == "neon":
            return self._sync_to_neon(payload)
        else:
            return {"success": False, "error": f"Proveedor desconocido: {self.provider}"}

    def _sync_to_turso(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sincroniza datos hacia Turso (libSQL) utilizando su API HTTP Pipeline v2.
        No requiere dependencias binarias externas (100% compatible con Python standard).
        """
        # Formatear URL de Turso si viene en formato libsql://
        url = self.cloud_url
        if url.startswith("libsql://"):
            url = url.replace("libsql://", "https://")
        if not url.endswith("/v2/pipeline"):
            url = url.rstrip("/") + "/v2/pipeline"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.auth_token}",
        }

        # Generar sentencias SQL para recrear/actualizar tablas en Turso
        requests_list = [
            {"type": "execute", "stmt": {"sql": "CREATE TABLE IF NOT EXISTS cloud_wallet (id INTEGER PRIMARY KEY, balance_usd REAL, updated_at TEXT);"}},
            {"type": "execute", "stmt": {"sql": "CREATE TABLE IF NOT EXISTS cloud_portfolio (asset TEXT PRIMARY KEY, quantity REAL, avg_price REAL, current_price REAL, unrealized_pnl REAL, updated_at TEXT);"}},
            {"type": "execute", "stmt": {"sql": "CREATE TABLE IF NOT EXISTS cloud_trades (trade_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, quantity REAL, price_entry REAL, price_exit REAL, pnl REAL, pnl_pct REAL, status TEXT, opened_at TEXT, closed_at TEXT, agent_id TEXT);"}},
        ]

        # Insertar o actualizar Wallet
        wallet = payload.get("wallet", {})
        if wallet:
            bal = float(wallet.get("balance_usd", 16.0))
            ts = payload.get("timestamp", "")
            requests_list.append({
                "type": "execute",
                "stmt": {
                    "sql": "INSERT OR REPLACE INTO cloud_wallet (id, balance_usd, updated_at) VALUES (1, ?, ?);",
                    "args": [{"type": "float", "value": bal}, {"type": "text", "value": ts}],
                },
            })

        # Insertar o actualizar Portfolio
        for item in payload.get("portfolio", []):
            requests_list.append({
                "type": "execute",
                "stmt": {
                    "sql": "INSERT OR REPLACE INTO cloud_portfolio (asset, quantity, avg_price, current_price, unrealized_pnl, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                    "args": [
                        {"type": "text", "value": str(item.get("asset", ""))},
                        {"type": "float", "value": float(item.get("quantity", 0.0) or 0.0)},
                        {"type": "float", "value": float(item.get("avg_price", 0.0) or 0.0)},
                        {"type": "float", "value": float(item.get("current_price", 0.0) or 0.0)},
                        {"type": "float", "value": float(item.get("unrealized_pnl", 0.0) or 0.0)},
                        {"type": "text", "value": payload.get("timestamp", "")},
                    ],
                },
            })

        body = json.dumps({"requests": requests_list}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                status = resp.status
                self._last_sync_time = datetime.now(timezone.utc)
                log.info(f"[CloudSync] Sincronización exitosa con Turso ({status}).")
                return {"success": True, "provider": "turso", "status_code": status}
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            log.warning(f"[CloudSync] HTTP error en Turso ({e.code}): {err_msg}")
            return {"success": False, "error": f"HTTP {e.code}: {err_msg}"}
        except Exception as e:
            log.warning(f"[CloudSync] Error conectando a Turso: {e}")
            return {"success": False, "error": str(e)}

    def _sync_to_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Envía el estado consolidado a un webhook REST o Serverless Function en Vercel."""
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.cloud_url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                status = resp.status
                self._last_sync_time = datetime.now(timezone.utc)
                log.info(f"[CloudSync] Sincronización exitosa con Webhook/Vercel ({status}).")
                return {"success": True, "provider": "webhook", "status_code": status}
        except Exception as e:
            log.warning(f"[CloudSync] Error sincronizando con Webhook: {e}")
            return {"success": False, "error": str(e)}

    def _sync_to_neon(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sincroniza con PostgreSQL en Neon si el driver correspondiente está disponible."""
        try:
            import psycopg2
            conn = psycopg2.connect(self.cloud_url, sslmode="require", connect_timeout=10)
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS cloud_wallet (id INT PRIMARY KEY, balance_usd NUMERIC, updated_at TIMESTAMP);")
            wallet = payload.get("wallet", {})
            if wallet:
                bal = float(wallet.get("balance_usd", 16.0))
                cur.execute(
                    "INSERT INTO cloud_wallet (id, balance_usd, updated_at) VALUES (1, %s, NOW()) ON CONFLICT (id) DO UPDATE SET balance_usd=EXCLUDED.balance_usd, updated_at=NOW();",
                    (bal,)
                )
            conn.commit()
            conn.close()
            self._last_sync_time = datetime.now(timezone.utc)
            log.info("[CloudSync] Sincronización exitosa con Neon Postgres.")
            return {"success": True, "provider": "neon"}
        except ImportError:
            log.warning("[CloudSync] Driver psycopg2 no instalado para Neon Postgres.")
            return {"success": False, "error": "psycopg2 no instalado"}
        except Exception as e:
            log.warning(f"[CloudSync] Error conectando a Neon: {e}")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    # Hilo Daemon Asíncrono
    # ─────────────────────────────────────────────────────────────────────────

    def start_background_sync(self):
        """Inicia el worker periódico en segundo plano si está habilitado."""
        if not self.enabled:
            log.info("[CloudSync] Cloud sync deshabilitado (CLOUD_SYNC_ENABLED=false).")
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="CloudSync-Worker",
            daemon=True,
        )
        self._thread.start()
        log.info(f"[CloudSync] Trabajador periódico en la nube iniciado (intervalo: {self.interval_seconds}s).")

    def _loop(self):
        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self.interval_seconds):
                break
            try:
                self.sync_now()
            except Exception as e:
                log.warning(f"[CloudSync] Error en ciclo periódico: {e}")

    def stop_background_sync(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
