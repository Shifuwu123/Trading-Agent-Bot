# Reglas de Desarrollo y Control de Versiones - Tredding Agent

1. **Respaldo Obligatorio en Git:**
   - Todo cambio, adición, corrección o mejora de código y configuración realizado dentro de este proyecto debe ser respaldado en Git.
   - Cada intervención debe finalizar con su respectivo `git add`, `git commit` describiendo brevemente los cambios técnicos implementados (usando prefijos claros: `Feat:`, `Fix:`, `Refactor:`, `Test:`, `Docs:`), y posterior `git push` a la rama de trabajo en el repositorio remoto.

2. **Seguridad y Cuidado de Archivos Sensibles:**
   - Nunca incluir claves privadas, tokens, archivos `.env`, bases de datos SQLite (`.db`), ni archivos de caché en los commits (asegurar cumplimiento estricto del `.gitignore`).
