#!/bin/bash
# scripts/install.sh - Установка всех зависимостей для VMS Profiler

set -e  # Остановка при ошибке

echo "╔════════════════════════════════════════════════════════╗"
echo "║  VMS Profiler - Установка зависимостей                 ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Проверка ОС
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    echo "✅ Обнаружена Linux система"
    DISTRO=$(cat /etc/os-release | grep "^ID=" | cut -d= -f2 | tr -d '"')
    echo "📦 Дистрибутив: $DISTRO"
else
    echo "⚠️  Предупреждение: Скрипт предназначен для Linux"
    echo "   На Windows используйте WSL или виртуальную машину"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════
# 1. Обновление пакетов
# ═══════════════════════════════════════════════════════════════
echo ""
echo "🔄 Обновление списков пакетов..."
sudo apt update || sudo yum update -y || sudo dnf update -y

# ═══════════════════════════════════════════════════════════════
# 2. Установка системных зависимостей
# ═══════════════════════════════════════════════════════════════
echo ""
echo "📦 Установка системных зависимостей..."

case $DISTRO in
    ubuntu|debian|linuxmint)
        sudo apt install -y \
            likwid \
            tshark \
            net-tools \
            iproute2 \
            python3 \
            python3-pip \
            python3-venv \
            curl \
            wget \
            git
        ;;
    centos|rhel|fedora)
        sudo yum install -y \
            likwid \
            wireshark-cli \
            net-tools \
            iproute \
            python3 \
            python3-pip \
            curl \
            wget \
            git
        ;;
    *)
        echo "⚠️  Неизвестный дистрибутив, попробуйте вручную:"
        echo "   sudo apt install likwid tshark python3-pip"
        ;;
esac

# ═══════════════════════════════════════════════════════════════
# 3. Настройка LIKWID
# ═══════════════════════════════════════════════════════════════
echo ""
echo "⚙️  Настройка LIKWID..."

# Загрузка модуля MSR
echo "📌 Загрузка модуля msr..."
sudo modprobe msr

# Автозагрузка модуля
if ! grep -q "^msr$" /etc/modules-load.d/msr.conf 2>/dev/null; then
    echo "msr" | sudo tee -a /etc/modules-load.d/msr.conf > /dev/null
    echo "✅ Модуль msr добавлен в автозагрузку"
else
    echo "✅ Модуль msr уже в автозагрузке"
fi

# Проверка LIKWID
echo "🔍 Проверка LIKWID..."
if likwid-topology > /dev/null 2>&1; then
    echo "✅ LIKWID работает корректно"
    likwid-topology | head -5
else
    echo "❌ LIKWID не работает! Проверьте установку."
fi

# ═══════════════════════════════════════════════════════════════
# 4. Настройка tshark
# ═══════════════════════════════════════════════════════════════
echo ""
echo "⚙️  Настройка tshark..."

# Права для захвата трафика без root
if command -v tshark > /dev/null 2>&1; then
    sudo setcap cap_net_raw,cap_net_admin=eip /usr/bin/tshark 2>/dev/null || true
    echo "✅ tshark настроен для захвата трафика"
else
    echo "⚠️  tshark не найден, сетевой мониторинг будет ограничен"
fi

# ═══════════════════════════════════════════════════════════════
# 5. Установка Python зависимостей
# ═══════════════════════════════════════════════════════════════
echo ""
echo "🐍 Установка Python зависимостей..."

# Создание виртуального окружения (опционально)
if [ ! -d "venv" ]; then
    echo "📦 Создание виртуального окружения..."
    python3 -m venv venv
    echo "✅ Виртуальное окружение создано"
fi

# Активация и установка
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "📦 Активировано виртуальное окружение"
fi

pip3 install --upgrade pip
pip3 install -r requirements.txt

echo "✅ Python зависимости установлены"

# ═══════════════════════════════════════════════════════════════
# 6. Создание директорий
# ═══════════════════════════════════════════════════════════════
echo ""
echo "📁 Создание директорий..."

mkdir -p output
mkdir -p logs
touch output/.gitkeep
touch logs/.gitkeep

echo "✅ Директории созданы"

# ═══════════════════════════════════════════════════════════════
# 7. Итоговая проверка
# ═══════════════════════════════════════════════════════════════
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ПРОВЕРКА УСТАНОВКИ                                    ║"
echo "╚════════════════════════════════════════════════════════╝"

check_command() {
    if command -v $1 > /dev/null 2>&1; then
        echo "✅ $1: $(command -v $1)"
    else
        echo "❌ $1: НЕ НАЙДЕН"
    fi
}

check_command python3
check_command pip3
check_command likwid-topology
check_command tshark
check_command curl

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║  ✅ УСТАНОВКА ЗАВЕРШЕНА!                               ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "📋 Следующие шаги:"
echo "   1. На центральном узле: ./scripts/start_collector.sh"
echo "   2. На вычислительных узлах: ./scripts/start_agent.sh"
echo "   3. Для отчёта: ./scripts/generate_report.sh"
echo ""