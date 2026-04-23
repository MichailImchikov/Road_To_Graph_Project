#!/bin/bash
# scripts/check_health.sh - Проверка здоровья всех компонентов

echo "╔════════════════════════════════════════════════════════╗"
echo "║  VMS Profiler - Проверка здоровья системы              ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

COLLECTOR_HOST="${COLLECTOR_HOST:-localhost}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"

# ═══════════════════════════════════════════════════════════════
# 1. Проверка коллектора
# ═══════════════════════════════════════════════════════════════
echo "🔍 Коллектор ($COLLECTOR_HOST:$COLLECTOR_PORT)..."
HEALTH=$(curl -s "http://$COLLECTOR_HOST:$COLLECTOR_PORT/health" 2>/dev/null)

if [ -n "$HEALTH" ]; then
    echo "✅ Коллектор работает"
    echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
else
    echo "❌ Коллектор недоступен"
fi

echo ""

# ═══════════════════════════════════════════════════════════════
# 2. Проверка процессов
# ═══════════════════════════════════════════════════════════════
echo "🔍 Процессы..."

check_process() {
    if pgrep -f "$1" > /dev/null; then
        echo "✅ $1 запущен"
    else
        echo "❌ $1 не запущен"
    fi
}

check_process "collector.py"
check_process "agent.py"
check_process "network_monitor.py"

echo ""

# ═══════════════════════════════════════════════════════════════
# 3. Проверка системных зависимостей
# ═══════════════════════════════════════════════════════════════
echo "🔍 Системные зависимости..."

check_command() {
    if command -v $1 &> /dev/null; then
        echo "✅ $1: $(command -v $1)"
    else
        echo "❌ $1: НЕ НАЙДЕН"
    fi
}

check_command python3
check_command likwid-topology
check_command tshark

echo ""

# ═══════════════════════════════════════════════════════════════
# 4. Проверка модуля MSR
# ═══════════════════════════════════════════════════════════════
echo "🔍 Модуль MSR..."
if lsmod | grep -q msr; then
    echo "✅ Модуль msr загружен"
else
    echo "⚠️  Модуль msr не загружен (LIKWID не будет работать)"
fi

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ПРОВЕРКА ЗАВЕРШЕНА                                    ║"
echo "╚════════════════════════════════════════════════════════╝"