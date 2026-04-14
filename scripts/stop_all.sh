#!/bin/bash
# scripts/stop_all.sh - Остановка всех сервисов VMS Profiler

echo "╔════════════════════════════════════════════════════════╗"
echo "║  VMS Profiler - Остановка всех сервисов                ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# Поиск и остановка процессов
# ═══════════════════════════════════════════════════════════════
echo "🔍 Поиск процессов..."

# Collector
COLLECTOR_PIDS=$(pgrep -f "collector.py" || true)
if [ -n "$COLLECTOR_PIDS" ]; then
    echo "🛑 Остановка collector.py (PID: $COLLECTOR_PIDS)..."
    kill $COLLECTOR_PIDS 2>/dev/null || true
    sleep 1
    # Принудительная остановка если нужно
    kill -9 $COLLECTOR_PIDS 2>/dev/null || true
    echo "✅ Collector остановлен"
else
    echo "ℹ️  Collector не запущен"
fi

# Agent
AGENT_PIDS=$(pgrep -f "agent.py" || true)
if [ -n "$AGENT_PIDS" ]; then
    echo "🛑 Остановка agent.py (PID: $AGENT_PIDS)..."
    kill $AGENT_PIDS 2>/dev/null || true
    sleep 1
    kill -9 $AGENT_PIDS 2>/dev/null || true
    echo "✅ Агент остановлен"
else
    echo "ℹ️  Агент не запущен"
fi

# Network Monitor
NETWORK_PIDS=$(pgrep -f "network_monitor.py" || true)
if [ -n "$NETWORK_PIDS" ]; then
    echo "🛑 Остановка network_monitor.py (PID: $NETWORK_PIDS)..."
    kill $NETWORK_PIDS 2>/dev/null || true
    sleep 1
    kill -9 $NETWORK_PIDS 2>/dev/null || true
    echo "✅ Network monitor остановлен"
else
    echo "ℹ️  Network monitor не запущен"
fi

# ═══════════════════════════════════════════════════════════════
# Проверка
# ═══════════════════════════════════════════════════════════════
echo ""
echo "🔍 Проверка..."
sleep 1

REMAINING=$(pgrep -f "collector.py|agent.py|network_monitor.py" || true)
if [ -z "$REMAINING" ]; then
    echo "✅ Все процессы остановлены"
else
    echo "⚠️  Остались процессы: $REMAINING"
    echo "   Попробуйте: kill -9 <PID>"
fi

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ ВСЕ СЕРВИСЫ ОСТАНОВЛЕНЫ!                           ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""