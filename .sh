#!/bin/bash
# run_experiment.sh - Автоматизированный запуск эксперимента
# Использование: ./run_experiment.sh [NUM_NODES] [DURATION_SEC] [OUTPUT_FILE]

set -e  # Выход при ошибке

# === Настройки по умолчанию ===
NUM_NODES=${1:-20}              # Число нод (по умолчанию 20)
DURATION_SEC=${2:-120}          # Длительность эксперимента в секундах (по умолчанию 2 минуты)
OUTPUT_FILE=${3:-report.json}   # Имя выходного файла
PROJECT_DIR=~/Road_To_Graph_Project
LOG_DIR="$PROJECT_DIR/logs"

# === Цвета для вывода ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# === Логирование ===
log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $1"; }
success() { echo -e "${GREEN}✅ $1${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; exit 1; }

# === Очистка при выходе (гарантируем остановку процессов) ===
cleanup() {
    log "🧹 Остановка процессов..."
    pkill -9 -f "python3 light_node_.*\.py" 2>/dev/null || true
    pkill -9 -f "create_light_ros_graph.py" 2>/dev/null || true
    pkill -9 -f "agent.agent" 2>/dev/null || true
    pkill -9 -f "collector.py" 2>/dev/null || true
    ros2 daemon stop 2>/dev/null || true
    success "Процессы остановлены"
}
trap cleanup EXIT INT TERM

# === Начало ===
log "🚀 Запуск эксперимента: $NUM_NODES нод, $DURATION_SEC сек"
mkdir -p "$LOG_DIR"

# === Шаг 1: Очистка ===
log "🧹 Очистка старых процессов..."
pkill -9 -f "light_node|agent|collector|create_light" 2>/dev/null || true
ros2 daemon stop 2>/dev/null || true
sleep 2
find "$PROJECT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
success "Система очищена"

# === Шаг 2: Запуск коллектора ===
log "📡 Запуск коллектора..."
cd "$PROJECT_DIR"
python3 collector/collector.py > "$LOG_DIR/collector.log" 2>&1 &
COLLECTOR_PID=$!
sleep 3
if ! kill -0 $COLLECTOR_PID 2>/dev/null; then
    error "Коллектор не запустился! См. $LOG_DIR/collector.log"
fi
success "Коллектор запущен (PID: $COLLECTOR_PID)"

# === Шаг 3: Настройка параметров графа ===
log "⚙️  Настройка графа: $NUM_NODES нод..."
GRAPH_SCRIPT="$PROJECT_DIR/benchmark/create_light_ros_graph.py"

# Обновляем параметры в скрипте генератора (если нужно)
sed -i "s/NUM_NODES = .*/NUM_NODES = $NUM_NODES/" "$GRAPH_SCRIPT"
# Для больших графов снижаем нагрузку автоматически
if [ "$NUM_NODES" -gt 30 ]; then
    sed -i "s/TARGET_BW_MBPS = .*/TARGET_BW_MBPS = 5/" "$GRAPH_SCRIPT"
    sed -i "s/BASE_MEM_MB = .*/BASE_MEM_MB = 5/" "$GRAPH_SCRIPT"
    sed -i "s/MAX_EDGES = .*/MAX_EDGES = 1/" "$GRAPH_SCRIPT"
    warn "Больше 30 нод: снижена нагрузка (BW=5, MEM=5, EDGES=1)"
fi
success "Параметры графа настроены"

# === Шаг 4: Запуск графа ===
log "🕸️  Запуск графа..."
cd "$PROJECT_DIR/benchmark"
python3 create_light_ros_graph.py > "$LOG_DIR/graph.log" 2>&1 &
GRAPH_PID=$!
sleep 8

# Проверка, что ноды запустились
NODE_COUNT=$(ros2 node list 2>/dev/null | grep -c light_worker || echo 0)
if [ "$NODE_COUNT" -lt "$NUM_NODES" ]; then
    warn "Запущено только $NODE_COUNT из $NUM_NODES нод (возможно, ещё загружаются)"
else
    success "Граф запущен: $NODE_COUNT нод (PID: $GRAPH_PID)"
fi

# === Шаг 5: Запуск агента ===
log "🤖 Запуск агента профилирования..."
cd "$PROJECT_DIR"

# Переменные окружения для гибкого маппинга
export TARGET_PROCESS_PATTERN='light_node'
export NODE_NAME_PATTERN='light_node_(\d+)\.py'
export ROS_NAME_TEMPLATE='light_node_{}'

# ROS-окружение
source /opt/ros/jazzy/setup.bash 2>/dev/null || true
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export COLLECTOR_HOST=127.0.0.1

python3 -m agent.agent > "$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!
sleep 15

if ! kill -0 $AGENT_PID 2>/dev/null; then
    error "Агент не запустился! См. $LOG_DIR/agent.log"
fi
success "Агент запущен (PID: $AGENT_PID)"

# === Шаг 6: Ожидание сбора данных ===
log "⏳ Сбор данных: $DURATION_SEC секунд..."
log "💡 Мониторь в реальном времени:"
log "   • Топики:  ros2 topic list | grep light"
log "   • Метрики: curl -s http://127.0.0.1:8080/report | jq '.nodes[0].num_active_tasks'"
log "   • Лог агента: tail -f $LOG_DIR/agent.log"

# Прогресс-бар (опционально)
for i in $(seq 1 10); do
    sleep $((DURATION_SEC / 10))
    printf "${YELLOW}▶${NC} "
done
echo ""
success "Сбор данных завершён"

# === Шаг 7: Остановка (автоматически через trap, но можно явно) ===
log "🛑 Остановка компонентов..."
# trap cleanup сделает это автоматически при выходе, но можно продублировать:
pkill -9 -f "python3 light_node_.*\.py" 2>/dev/null || true
pkill -9 -f "create_light_ros_graph.py" 2>/dev/null || true
pkill -9 -f "agent.agent" 2>/dev/null || true
success "Граф и агент остановлены"

# === Шаг 8: Агрегация отчёта ===
log "📊 Формирование итогового отчёта..."

# Скачиваем финальный отчёт
curl -s "http://127.0.0.1:8080/report" > "$PROJECT_DIR/$OUTPUT_FILE" 2>/dev/null || {
    warn "Не удалось получить отчёт через HTTP, пробуем из кэша..."
    # Если коллектор ещё жив — повторить, иначе взять последний сохранённый
    sleep 2
    curl -s "http://127.0.0.1:8080/report" > "$PROJECT_DIR/$OUTPUT_FILE" 2>/dev/null || true
}

if [ -f "$PROJECT_DIR/$OUTPUT_FILE" ] && [ -s "$PROJECT_DIR/$OUTPUT_FILE" ]; then
    success "Отчёт сохранён: $PROJECT_DIR/$OUTPUT_FILE"
    
    # === Краткая сводка ===
    echo ""
    echo "📈 === СВОДКА ЭКСПЕРИМЕНТА ==="
    python3 << PYEOF
import json, sys
try:
    with open("$PROJECT_DIR/$OUTPUT_FILE") as f:
        d = json.load(f)
    node = d['nodes'][0]
    tasks = node['tasks']
    print(f"📦 Нод в отчёте: {len(tasks)}")
    print(f"💻 CPU: {node['total_cpu_load']:.1f}%")
    print(f"🧠 RAM: {node['total_memory_usage_mb']:.0f} MB")
    
    # Трафик
    with_traffic = [t for t in tasks if t['network_traffic_mbps'] > 0]
    print(f"🌐 Нод с трафиком: {len(with_traffic)}/{len(tasks)}")
    
    # Смежные задачи
    with_adj = [t for t in tasks if t['adjacent_tasks']]
    print(f"🔗 Нод со связями: {len(with_adj)}/{len(tasks)}")
    
    # Топ-3 по трафику
    if with_traffic:
        top = sorted(with_traffic, key=lambda x: x['network_traffic_mbps'], reverse=True)[:3]
        print(f"🏆 Топ-3 по трафику:")
        for t in top:
            name = t['task_name'].split('/')[-1]
            print(f"   • {name}: {t['network_traffic_mbps']:.4f} Mbps")
except Exception as e:
    print(f"⚠️  Не удалось распарсить отчёт: {e}")
PYEOF
    echo "==============================="
    echo ""
else
    error "Не удалось сохранить отчёт"
fi

# === Шаг 9: Остановка коллектора ===
log "🔌 Остановка коллектора..."
pkill -9 -f "collector.py" 2>/dev/null || true
ros2 daemon stop 2>/dev/null || true
success "Коллектор остановлен"

# === Финал ===
success "🎉 Эксперимент завершён!"
log "📁 Отчёт: $PROJECT_DIR/$OUTPUT_FILE"
log "📋 Логи: $LOG_DIR/"
log "💡 Для анализа: cat $PROJECT_DIR/$OUTPUT_FILE | jq '.'"

# Отключаем trap, чтобы не чистить ещё раз при нормальном выходе
trap - EXIT INT TERM
exit 0