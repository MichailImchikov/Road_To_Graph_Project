#!/bin/bash
# scripts/start_collector.sh - Запуск центрального сервера сбора данных

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║  VMS Profiler - Запуск центрального сборщика           ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════
COLLECTOR_HOST="${COLLECTOR_HOST:-0.0.0.0}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"
LOG_FILE="${LOG_FILE:-logs/collector.log}"

# ═══════════════════════════════════════════════════════════════
# Проверки
# ═══════════════════════════════════════════════════════════════
echo "🔍 Проверка зависимостей..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден!"
    exit 1
fi

if ! python3 -c "import flask" &> /dev/null; then
    echo "❌ Flask не установлен! Запустите ./scripts/install.sh"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
# Создание директорий
# ═══════════════════════════════════════════════════════════════
mkdir -p logs
mkdir -p output

# ═══════════════════════════════════════════════════════════════
# Экспорт переменных окружения
# ═══════════════════════════════════════════════════════════════
export COLLECTOR_HOST
export COLLECTOR_PORT

echo "📋 Конфигурация:"
echo "   Хост: $COLLECTOR_HOST"
echo "   Порт: $COLLECTOR_PORT"
echo "   Лог:  $LOG_FILE"
echo ""

# ═══════════════════════════════════════════════════════════════
# Запуск
# ═══════════════════════════════════════════════════════════════
echo "🚀 Запуск collector.py..."

# Проверка на уже запущенный процесс
if pgrep -f "collector.py" > /dev/null; then
    echo "⚠️  Collector уже запущен!"
    echo "   Остановить: ./scripts/stop_all.sh"
    exit 1
fi

# Запуск в фоне
nohup python3 collector/collector.py > "$LOG_FILE" 2>&1 &
COLLECTOR_PID=$!

echo "✅ Collector запущен (PID: $COLLECTOR_PID)"
echo ""

# ═══════════════════════════════════════════════════════════════
# Проверка запуска
# ═══════════════════════════════════════════════════════════════
sleep 2

echo "🔍 Проверка здоровья..."
if curl -s "http://localhost:$COLLECTOR_PORT/health" > /dev/null; then
    echo "✅ Collector работает корректно"
    curl -s "http://localhost:$COLLECTOR_PORT/health" | python3 -m json.tool
else
    echo "❌ Collector не отвечает! Проверьте лог: $LOG_FILE"
    exit 1
fi

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ СБОРЩИК ЗАПУЩЕН И ГОТОВ К РАБОТЕ!                  ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Полезные команды:"
echo "   Проверка статуса: curl http://localhost:$COLLECTOR_PORT/health"
echo "   Список узлов:     curl http://localhost:$COLLECTOR_PORT/nodes"
echo "   Отчёт:            curl http://localhost:$COLLECTOR_PORT/report"
echo "   Остановить:       ./scripts/stop_all.sh"
echo "   Лог:              tail -f $LOG_FILE"
echo ""