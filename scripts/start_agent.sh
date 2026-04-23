#!/bin/bash
# scripts/start_agent.sh - Запуск агента профилирования на узле

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║  VMS Profiler - Запуск агента на узле                  ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════
NODE_ID="${NODE_ID:-node-$(hostname)}"
COLLECTOR_HOST="${COLLECTOR_HOST:-localhost}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"
LOG_FILE_AGENT="${LOG_FILE_AGENT:-logs/agent.log}"
LOG_FILE_NETWORK="${LOG_FILE_NETWORK:-logs/network_monitor.log}"

# ═══════════════════════════════════════════════════════════════
# Проверки
# ═══════════════════════════════════════════════════════════════
echo "🔍 Проверка зависимостей..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден!"
    exit 1
fi

if ! command -v likwid-topology &> /dev/null; then
    echo "⚠️  LIKWID не найден! Некоторые метрики будут недоступны"
fi

if ! command -v tshark &> /dev/null; then
    echo "⚠️  tshark не найден! Сетевой мониторинг будет ограничен"
fi

# ═══════════════════════════════════════════════════════════════
# Настройка LIKWID
# ═══════════════════════════════════════════════════════════════
echo ""
echo "⚙️  Настройка LIKWID..."

# Загрузка модуля MSR (требует sudo)
if ! lsmod | grep -q msr; then
    echo "📌 Загрузка модуля msr..."
    sudo modprobe msr || echo "⚠️  Не удалось загрузить msr (требуется sudo)"
fi

# ═══════════════════════════════════════════════════════════════
# Создание директорий
# ═══════════════════════════════════════════════════════════════
mkdir -p logs
mkdir -p output

# ═══════════════════════════════════════════════════════════════
# Экспорт переменных окружения
# ═══════════════════════════════════════════════════════════════
export NODE_ID
export COLLECTOR_HOST
export COLLECTOR_PORT

echo "📋 Конфигурация:"
echo "   Node ID:        $NODE_ID"
echo "   Collector Host: $COLLECTOR_HOST"
echo "   Collector Port: $COLLECTOR_PORT"
echo "   Лог агента:     $LOG_FILE_AGENT"
echo "   Лог сети:       $LOG_FILE_NETWORK"
echo ""

# ═══════════════════════════════════════════════════════════════
# Проверка на уже запущенные процессы
# ═══════════════════════════════════════════════════════════════
if pgrep -f "agent.py" > /dev/null; then
    echo "⚠️  Агент уже запущен!"
    echo "   Остановить: ./scripts/stop_all.sh"
    exit 1
fi

if pgrep -f "network_monitor.py" > /dev/null; then
    echo "⚠️  Network monitor уже запущен!"
fi

# ═══════════════════════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════════════════════
echo "🚀 Запуск agent.py..."
nohup python3 agent/agent.py > "$LOG_FILE_AGENT" 2>&1 &
AGENT_PID=$!
echo "✅ Агент запущен (PID: $AGENT_PID)"

echo "🚀 Запуск network_monitor.py..."
nohup python3 agent/network_monitor.py > "$LOG_FILE_NETWORK" 2>&1 &
NETWORK_PID=$!
echo "✅ Network monitor запущен (PID: $NETWORK_PID)"

echo ""

# ═══════════════════════════════════════════════════════════════
# Проверка запуска
# ═══════════════════════════════════════════════════════════════
sleep 2

echo "🔍 Проверка процессов..."
if ps -p $AGENT_PID > /dev/null; then
    echo "✅ Агент работает"
else
    echo "❌ Агент не запустился! Проверьте лог: $LOG_FILE_AGENT"
fi

if ps -p $NETWORK_PID > /dev/null; then
    echo "✅ Network monitor работает"
else
    echo "❌ Network monitor не запустился! Проверьте лог: $LOG_FILE_NETWORK"
fi

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ АГЕНТ ЗАПУЩЕН И ГОТОВ К РАБОТЕ!                    ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Полезные команды:"
echo "   Лог агента:  tail -f $LOG_FILE_AGENT"
echo "   Лог сети:    tail -f $LOG_FILE_NETWORK"
echo "   Остановить:  ./scripts/stop_all.sh"
echo "   Статус:      ps aux | grep -E 'agent|network'"
echo ""