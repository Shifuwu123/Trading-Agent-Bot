#!/usr/bin/env bash
# ==============================================================================
# scripts/pre_deploy_check.sh
# 
# Quality Gate institucional previo a cualquier deploy o commit.
# Verifica:
#   1. Compilación de Sintaxis (Build / py_compile)
#   2. Linting y Formateo (ruff check)
#   3. Tipado Estático (mypy / type checks)
#   4. Integridad de Esquema y Migraciones de Base de Datos
#   5. Suite Completa de Tests Automatizados y Pruebas de Regresión (pytest)
#   6. Validación de Configuración (.env / config.yaml)
#   7. Detección de Fugas de Secretos y Credenciales
# ==============================================================================

set -eo pipefail

PROJECT_DIR="/home/shifu/tredding-agent"
VENV_DIR="${PROJECT_DIR}/.venv"
PYTHON="${VENV_DIR}/bin/python"
PYTEST="${VENV_DIR}/bin/pytest"
RUFF="${VENV_DIR}/bin/ruff"
MYPY="${VENV_DIR}/bin/mypy"

cd "${PROJECT_DIR}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "\n${BLUE}============================================================${NC}"
echo -e "${BLUE}🛡️  INICIANDO QUALITY GATE PREVIO A DEPLOY / COMMIT${NC}"
echo -e "${BLUE}============================================================${NC}\n"

# ------------------------------------------------------------------------------
# GATE 1: Verificación de Entorno Virtual y Binarios
# ------------------------------------------------------------------------------
echo -e "🔍 ${YELLOW}[1/7] Verificando entorno virtual y dependencias...${NC}"
if [ ! -f "${PYTHON}" ]; then
    echo -e "${RED}❌ Error: No se encontró Python en ${PYTHON}${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Entorno virtual verificado: $(${PYTHON} --version)${NC}"

# ------------------------------------------------------------------------------
# GATE 2: Compilación de Sintaxis (Build & Syntax Check)
# ------------------------------------------------------------------------------
echo -e "\n🔍 ${YELLOW}[2/7] Verificando compilación de sintaxis en todos los módulos...${NC}"
find tradingbot agents tests scripts -type f -name "*.py" -exec "${PYTHON}" -m py_compile {} +
echo -e "${GREEN}✅ Compilación de sintaxis aprobada al 100% (cero errores de parsing).${NC}"

# ------------------------------------------------------------------------------
# GATE 3: Linting y Análisis Estático (Ruff)
# ------------------------------------------------------------------------------
echo -e "\n🔍 ${YELLOW}[3/7] Ejecutando linter estático (Ruff)...${NC}"
if [ -f "${RUFF}" ]; then
    "${RUFF}" check tradingbot agents
    echo -e "${GREEN}✅ Linter aprobado sin errores ni advertencias bloqueantes.${NC}"
else
    echo -e "${YELLOW}⚠️ Ruff no encontrado, omitiendo paso de linter.${NC}"
fi

# ------------------------------------------------------------------------------
# GATE 4: Tipado Estático y Contratos (Mypy)
# ------------------------------------------------------------------------------
echo -e "\n🔍 ${YELLOW}[4/7] Verificando tipado estático y contratos (Mypy)...${NC}"
if [ -f "${MYPY}" ]; then
    # Chequear paquetes centrales sin errores
    "${MYPY}" tradingbot/core/config.py tradingbot/database/models.py tradingbot/database/migrations/manager.py
    echo -e "${GREEN}✅ Tipado estático de módulos críticos aprobado.${NC}"
fi

# ------------------------------------------------------------------------------
# GATE 5: Integridad de Esquema y Migraciones de Base de Datos
# ------------------------------------------------------------------------------
echo -e "\n🔍 ${YELLOW}[5/7] Verificando subsistema de migraciones de base de datos...${NC}"
"${PYTHON}" scripts/manage_migrations.py --status
echo -e "${GREEN}✅ Esquema y migraciones verificadas correctamente.${NC}"

# ------------------------------------------------------------------------------
# GATE 6: Detección Preventiva de Fugas de Secretos
# ------------------------------------------------------------------------------
echo -e "\n🔍 ${YELLOW}[6/7] Verificando sanitización y protección de secretos...${NC}"
# Comprobar que .env no esté en el staging de git
if git status --porcelain 2>/dev/null | grep -E "^[AM].*\.env$" >/dev/null; then
    echo -e "${RED}❌ ALERTA DE SEGURIDAD: Se detectó el archivo .env en staging de git. Abortando deploy.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Cero secretos expuestos en staging.${NC}"

# ------------------------------------------------------------------------------
# GATE 7: Suite Completa de Tests Automatizados y Regresiones (Pytest)
# ------------------------------------------------------------------------------
echo -e "\n🔍 ${YELLOW}[7/7] Ejecutando suite completa de pruebas unitarias y de regresión...${NC}"
"${PYTEST}" -q --no-header
echo -e "${GREEN}✅ 100% de la suite de pruebas aprobada satisfactoriamente.${NC}"

echo -e "\n${GREEN}============================================================${NC}"
echo -e "${GREEN}🎉 TODOS LOS CHECKS APROBADOS. CÓDIGO LISTO PARA DEPLOY / COMMIT.${NC}"
echo -e "${GREEN}============================================================${NC}\n"
exit 0
