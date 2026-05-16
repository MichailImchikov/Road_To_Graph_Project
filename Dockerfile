# Используем официальный образ ROS 2 Humble на базе Ubuntu 22.04
FROM ros:humble

# Устанавливаем необходимые системные пакеты
RUN apt-get update && apt-get install -y \
    python3-pip \
    git \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Python-библиотеки
RUN pip3 install pyrgg psutil requests flask flask-cors numpy

# Копируем ваш проект внутрь контейнера
WORKDIR /app
COPY . .

# Активируем ROS 2 и запускаем оболочку bash по умолчанию
CMD ["bash"]