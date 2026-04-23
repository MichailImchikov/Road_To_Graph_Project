#!/bin/bash
# scripts/generate_report.sh - Генерация итогового отчёта

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║  VMS Profiler - Генерация отчёта                       ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════
COLLECTOR_HOST="${COLLECTOR_HOST:-localhost}"
COLLECTOR_PORT="${COLLECTOR_PORT:-8080}"
OUTPUT_DIR="${OUTPUT_DIR:-./output}"

# ═══════════════════════════════════════════════════════════════
# Проверка доступности коллектора
# ═══════════════════════════════════════════════════════════════
echo "🔍 Проверка подключения к коллектору..."

if ! curl -s "http://$COLLECTOR_HOST:$COLLECTOR_PORT/health" > /dev/null; then
    echo "❌ Коллектор недоступен на $COLLECTOR_HOST:$COLLECTOR_PORT"
    echo "   Запустите: ./scripts/start_collector.sh"
    exit 1
fi

echo "✅ Коллектор доступен"

# Получение статистики
echo ""
echo "📊 Статистика системы:"
curl -s "http://$COLLECTOR_HOST:$COLLECTOR_PORT/stats" | python3 -m json.tool

# ═══════════════════════════════════════════════════════════════
# Генерация отчёта
# ═══════════════════════════════════════════════════════════════
echo ""
echo "📝 Генерация отчёта..."

mkdir -p "$OUTPUT_DIR"

python3 aggregator/aggregator.py \
    --collector-host "$COLLECTOR_HOST" \
    --collector-port "$COLLECTOR_PORT" \
    --output-dir "$OUTPUT_DIR"

# ═══════════════════════════════════════════════════════════════
# Итог
# ═══════════════════════════════════════════════════════════════
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ ОТЧЁТ СГЕНЕРИРОВАН!                                ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "📁 Файлы отчёта в: $OUTPUT_DIR"
ls -lh "$OUTPUT_DIR"/report_*.{json,txt,csv} 2>/dev/null || echo "   (файлы не найдены)"
echo ""