# Informe Técnico de Resolución de Error

**Título y Resumen del Error:** Lock asyncio en loop diferente  
**Fecha y Hora:** 2026-10-06 13:50:35  
**Estado Final:** ✅ Resuelto  

---

## 1. Resumen Ejecutivo
Durante la ejecución periódica y evaluación concurrente de señales de trading en los subagentes (por ejemplo, `ScalperAgent_Tier1` procesando el símbolo `XRP/USDT`), se producía una excepción crítica `RuntimeError` originada en `asyncio/locks.py`:

```text
RuntimeError: <asyncio.locks.Lock object at 0x7f8e735940 [locked]> is bound to a different event loop
```

Este fallo impedía la ejecución segura de órdenes y provocaba el descarte de señales operativas en activos concurrentes.

---

## 2. Causa Raíz Identificada (Root Cause)
1. **Desincronización de ciclos de vida:**
   - `TradeEngine` es un servicio de larga duración instanciado al inicio de cada subagente.
   - En su inicialización original (`__init__`), se creaba estáticamente una única instancia de `self._trade_lock = asyncio.Lock()`.
2. **Recreación de bucles de eventos (`EventLoop`):**
   - El planificador de tareas periódico (`APScheduler`) en `agents/base_agent.py` ejecuta cada ciclo mediante `_run_cycle_sync()`, el cual invoca `asyncio.run(self.run_cycle())`.
   - `asyncio.run()` crea un nuevo `EventLoop` por cada ciclo y lo cierra al concluir.
3. **Comportamiento interno de `asyncio.Lock` en Python 3.10+ / 3.13:**
   - Al entrar en contención concurrente durante un ciclo, el objeto `asyncio.Lock` vincula internamente su atributo `_loop` al loop activo en ese instante.
   - En el ciclo siguiente (manejado por un loop nuevo), cuando una corrutina (`process_symbol` para `XRP/USDT`) intenta adquirir el lock mientras otro símbolo lo retiene, `self.acquire()` invoca `self._get_loop().create_future()`.
   - Al detectar que el loop actual no coincide con el loop guardado en la instancia del lock, `asyncio` lanza `RuntimeError: ... is bound to a different event loop`.

---

## 3. Archivos Modificados y Detalle de Cambios

### A. [`tradingbot/engine/trade_engine.py`](file:///home/shifu/tredding-agent/tradingbot/engine/trade_engine.py)
- **Eliminación de la inicialización estática:** Se reemplazó `self._trade_lock = asyncio.Lock()` por campos privados `self._trade_lock: Optional[asyncio.Lock] = None` y `self._trade_lock_loop: Optional[asyncio.AbstractEventLoop] = None`.
- **Implementación de propiedad dinámica (`trade_lock`):** Se creó la propiedad `@property def trade_lock(self) -> asyncio.Lock` que comprueba dinámicamente si existe un bucle activo (`asyncio.get_running_loop()`). Si el bucle ha cambiado respecto a la iteración previa o es la primera vez que se accede, genera automáticamente un `asyncio.Lock()` fresco vinculado al bucle en ejecución.
- **Acceso en `process_symbol`:** Se actualizó la línea de adquisición de lock a `async with self.trade_lock:`, garantizando sincronización segura y concurrente entre pares dentro del mismo ciclo.

```python
    @property
    def trade_lock(self) -> asyncio.Lock:
        """Retorna un Lock de asyncio asociado dinámicamente al event loop activo actual."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._trade_lock is None or self._trade_lock_loop is not current_loop:
            self._trade_lock = asyncio.Lock()
            self._trade_lock_loop = current_loop
        return self._trade_lock
```

### B. [`tests/test_risk_slot_and_lock.py`](file:///home/shifu/tredding-agent/tests/test_risk_slot_and_lock.py)
- Se agregaron pruebas unitarias especializadas:
  1. `test_trade_engine_lock_across_different_event_loops`: Valida que a través de múltiples llamadas independientes a `asyncio.run()`, el lock se recree y vincule sin fallar.
  2. `test_trade_engine_lock_shared_within_same_event_loop`: Valida que corrutinas concurrentes ejecutadas en el mismo ciclo (`asyncio.gather`) compartan la misma instancia de lock y preserven la exclusión mutua.

---

## 4. Pruebas y Verificaciones Realizadas
1. **Compilación de Sintaxis:**
   - Comando ejecutado: `python3 -m py_compile tradingbot/engine/trade_engine.py tests/test_risk_slot_and_lock.py`
   - Resultado: Sin errores de sintaxis (código 0).
2. **Ejecución de Tests de Concurrencia y Lock:**
   - Comando ejecutado: `pytest tests/test_risk_slot_and_lock.py`
   - Resultado: **7/7 tests aprobados (100% PASSED)**.
3. **Ejecución de Suite Completa de Pruebas:**
   - Comando ejecutado: `pytest`
   - Resultado: **33/33 tests aprobados (100% PASSED)**.

---

## 5. Conclusión y Estado
El error ha sido completamente solventado sin alterar la lógica de negocio ni la seguridad en la gestión de capital por moneda. El sistema ahora soporta ejecuciones periódicas continuas con recreación de bucles en APScheduler y concurrencia plena entre símbolos.

**Estado Final:** ✅ **Resuelto**
