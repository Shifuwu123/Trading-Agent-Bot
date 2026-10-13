# Reglas de Desarrollo y Control de Versiones - Tredding Agent

1. **Respaldo Obligatorio en Git:**
   - Todo cambio, adición, corrección o mejora de código y configuración realizado dentro de este proyecto debe ser respaldado en Git.
   - Cada intervención debe finalizar con su respectivo `git add`, `git commit` describiendo brevemente los cambios técnicos implementados (usando prefijos claros: `Feat:`, `Fix:`, `Refactor:`, `Test:`, `Docs:`), y posterior `git push` a la rama de trabajo en el repositorio remoto.

2. **Seguridad y Cuidado de Archivos Sensibles:**
   - Nunca incluir claves privadas, tokens, archivos `.env`, bases de datos SQLite (`.db`), ni archivos de caché en los commits (asegurar cumplimiento estricto del `.gitignore`).

3. **🛡️ Regla de Blindaje de Base de Datos en Pruebas y Diagnósticos (Test DB Shield):**
   - **Aislamiento Total Obligatorio:** Ninguna prueba automatizada (`pytest`), prueba unitaria, test de integración, benchmark o script de diagnóstico puede conectarse directa ni indirectamente a la base de datos de producción (`tradingbot.db`, `/dev/shm/tradingbot.db`, `data/tradingbot.db`).
   - Toda prueba debe ejecutarse obligatoriamente sobre una base de datos temporal aislada (`test_*.db` generada en `tempfile`) o en memoria (`sqlite:///:memory:`).
   - **Prohibición de Símbolos Reales en Pruebas con Mocks de Precios:** Queda estrictamente prohibido utilizar símbolos de monedas reales activas (como `SOL/USDT`, `BTC/USDT`, `ETH/USDT`, etc.) en pruebas que simulen precios ficticios o caídas abruptas de cotización. Todo test que requiera simular velas o precios de ejecución debe utilizar exclusivamente símbolos ficticios de prueba (`MOCK/USDT`, `TEST/USDT`, `FIXTURE/USDT`).
   - **Verificación Previa a la Ejecución de Tests:** Antes de ejecutar cualquier test o suite de `pytest`, verificar que `DATABASE_URL` y las variables de sesión apunten a la instancia temporal y jamás a la base viva de producción.

