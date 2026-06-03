#!/bin/bash
# run_all.sh - Запуск всего стенда одной командой
# Использование: ./run_all.sh [nodes_count]
# Пример: ./run_all.sh 5  (запустит граф из 5 нод)

set -e  # Выход при ошибке

# ════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ════════════════════════════════════════════════════════════
PROJECT_DIR="$HOME/Road_To_Graph_Project"
LOG_DIR="$PROJECT_DIR/logs"
NODES_COUNT="${1:-5}"  # По умолчанию 5 нод, можно передать аргументом

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ════════════════════════════════════════════════════════════
# ФУНКЦИИ
# ════════════════════════════════════════════════════════════

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

# Очистка старых процессов
cleanup_old() {
    log_info "Очистка старых процессов..."
    sudo pkill -9 -f "agent.agent" 2>/dev/null || true
    pkill -9 -f "collector.py" 2>/dev/null || true
    pkill -9 -f "aggregator.py" 2>/dev/null || true
    pkill -9 -f "light_node" 2>/dev/null || true
    pkill -9 -f "create_light_ros_graph" 2>/dev/null || true
    sudo fuser -k 8080/tcp 2>/dev/null || true
    sleep 2
    log_success "Очистка завершена"
}

# Исправление конфига агента (критичные параметры)
fix_agent_config() {
    log_info "Проверка конфига агента..."
    python3 << 'PYEOF'
import re, sys
try:
    with open('agent/agent.py', 'r') as f: code = f.read()
    code = re.sub(r"LIKWID_GROUP\s*=\s*['\"]INST['\"]", "LIKWID_GROUP = 'MEM'", code)
    code = re.sub(r"MEASUREMENT_DURATION\s*=\s*5(?!0)", "MEASUREMENT_DURATION = 2", code)
    code = re.sub(r"CPU_THRESHOLD_PERCENT\s*=\s*5\.0", "CPU_THRESHOLD_PERCENT = 0.5", code)
    code = re.sub(r"COLLECTOR_HOST\s*=\s*['\"]localhost['\"]", "COLLECTOR_HOST = '127.0.0.1'", code)
    code = re.sub(r"timeout=self\.duration\s*\+\s*10", "timeout=self.duration + 30", code)
    with open('agent/agent.py', 'w') as f: f.write(code)
    print("✅ Конфиг агента исправлен")
except Exception as e:
    print(f"⚠️ Не удалось исправить конфиг: {e}", file=sys.stderr)
PYEOF
}

# Запуск коллектора
start_collector() {
    log_info "Запуск Collector (порт 8080)..."
    cd "$PROJECT_DIR"
    mkdir -p "$LOG_DIR"
    
    python3 collector/collector.py > "$LOG_DIR/collector.log" 2>&1 &
    COLLECTOR_PID=$!
    
    # Ждём и проверяем
    for i in {1..10}; do
        if curl -s http://127.0.0.1:8080/health > /dev/null 2>&1; then
            log_success "Collector запущен (PID: $COLLECTOR_PID)"
            return 0
        fi
        sleep 1
    done
    log_error "Collector не запустился! См. $LOG_DIR/collector.log"
    return 1
}

# Запуск агента (с sudo для LIKWID + ROS окружение)
start_agent() {
    log_info "Запуск Agent (sudo + ROS env)..."
    cd "$PROJECT_DIR"
    
    # Кэшируем пароль sudo заранее
    sudo -v
    
    # Запускаем в фоне с полным окружением
    nohup sudo bash -c "
        source /opt/ros/jazzy/setup.bash
        export ROS_DOMAIN_ID=0
        export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
        export PYTHONPATH=/opt/ros/jazzy/lib/python3.12/site-packages:\$PYTHONPATH
        cd $PROJECT_DIR
        export COLLECTOR_HOST=127.0.0.1
        python3 -m agent.agent
    " > "$LOG_DIR/agent.log" 2>&1 &
    AGENT_PID=$!
    
    sleep 5
    if ps -p $AGENT_PID > /dev/null 2>&1; then
        log_success "Agent запущен (PID: $AGENT_PID)"
        return 0
    else
        log_error "Agent не запустился! См. $LOG_DIR/agent.log"
        return 1
    fi
}

# Запуск ROS-графа
start_ros_graph() {
    local count=$1
    log_info "Запуск ROS 2 Graph ($count нод)..."
    cd "$PROJECT_DIR/benchmark"
    source /opt/ros/jazzy/setup.bash
    
    # Запускаем скрипт создания графа в фоне
    python3 create_light_ros_graph.py --nodes $count > "$LOG_DIR/graph.log" 2>&1 &
    GRAPH_PID=$!
    
    sleep 3
    if ros2 node list 2>/dev/null | grep -q light_worker; then
        log_success "ROS Graph запущен (PID: $GRAPH_PID)"
        return 0
    else
        log_warn "Граф запущен, но ноды ещё инициализируются..."
        return 0
    fi
}

# (Опционально) Запуск агрегатора
start_aggregator() {
    log_info "Запуск Aggregator..."
    cd "$PROJECT_DIR"
    
    python3 aggregator/aggregator.py > "$LOG_DIR/aggregator.log" 2>&1 &
    AGGREGATOR_PID=$!
    
    sleep 2
    log_success "Aggregator запущен (PID: $AGGREGATOR_PID)"
}

# Обработчик Ctrl+C
cleanup_on_exit() {
    echo ""
    log_warn "Получен сигнал остановки. Завершаю процессы..."
    
    # Останавливаем в обратном порядке
    [ -n "$GRAPH_PID" ] && kill $GRAPH_PID 2>/dev/null || true
    [ -n "$AGENT_PID" ] && sudo kill $AGENT_PID 2>/dev/null || true
    [ -n "$COLLECTOR_PID" ] && kill $COLLECTOR_PID 2>/dev/null || true
    [ -n "$AGGREGATOR_PID" ] && kill $AGGREGATOR_PID 2>/dev/null || true
    
    # Ждём завершения
    sleep 2
    
    # Если не завершились — убиваем жёстко
    sudo pkill -9 -f "agent.agent" 2>/dev/null || true
    pkill -9 -f "collector.py" 2>/dev/null || true
    pkill -9 -f "light_node" 2>/dev/null || true
    
    log_success "Все процессы остановлены"
    exit 0
}

# Показ полезных команд
show_help() {
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅ ВСЕ СИСТЕМЫ ЗАПУЩЕНЫ!                               ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "📊 Проверка в другом терминале:"
    echo "   • Статус коллектора:  curl -s http://127.0.0.1:8080/health"
    echo "   • Список узлов:       curl -s http://127.0.0.1:8080/nodes"
    echo "   • Полный отчёт:       curl -s http://127.0.0.1:8080/report"
    echo "   • ROS ноды:           ros2 node list | grep light"
    echo "   • Трафик топика:      ros2 topic bw /light_topic_1_to_2"
    echo ""
    echo "📁 Логи:"
    echo "   • Collector:  tail -f $LOG_DIR/collector.log"
    echo "   • Agent:      tail -f $LOG_DIR/agent.log"
    echo "   • Graph:      tail -f $LOG_DIR/graph.log"
    echo ""
    echo "🛑 Остановка: нажми ${RED}Ctrl+C${NC} в этом терминале"
    echo ""
}

# ════════════════════════════════════════════════════════════
# ОСНОВНОЙ СКРИПТ
# ════════════════════════════════════════════════════════════

main() {
    echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  🚀 Road To Graph - Single Launch Script                ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    # Переход в директорию проекта
    cd "$PROJECT_DIR" || { log_error "Не найдена директория проекта"; exit 1; }
    
    # Подгружаем ROS для текущей сессии (для проверок)
    if [ -f /opt/ros/jazzy/setup.bash ]; then
        source /opt/ros/jazzy/setup.bash
        log_success "ROS 2 Jazzy окружение загружено"
    fi
    
    # 0. Чистим старые процессы
    cleanup_old
    
    # 1. Фиксим конфиг агента
    fix_agent_config
    
    # 2. Запускаем компоненты
    start_collector || exit 1
    start_agent || exit 1
    start_ros_graph "$NODES_COUNT" || exit 1
    
    # 3. (Опционально) Агрегатор
    # start_aggregator
    
    # 4. Ждём инициализации
    log_info "Ожидание инициализации (15 сек)..."
    sleep 15
    
    # 5. Показываем справку
    show_help
    
    # 6. Регистрируем обработчик Ctrl+C
    trap cleanup_on_exit INT TERM
    
    # 7. Держим скрипт запущенным (ждём граф)
    log_info "Жду завершения графа (нажми Ctrl+C для остановки)..."
    wait $GRAPH_PID 2>/dev/null || true
}

# Запуск
main "$@"
