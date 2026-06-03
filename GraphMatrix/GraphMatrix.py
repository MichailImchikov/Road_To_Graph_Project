import json
import networkx as nx
import matplotlib.pyplot as plt


def extract_metrics_and_build_matrix(json_filepath):
    with open(json_filepath, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # Рекурсивная очистка ключей и строк от пробелов
    def clean_obj(obj):
        if isinstance(obj, dict):
            return {k.strip(): (v.strip() if isinstance(v, str) else clean_obj(v)) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_obj(i) for i in obj]
        return obj

    data = clean_obj(raw_data)

    # Извлекаем основные поля ноды
    target_fields = [
        "node_id", "timestamp", "total_cpu_load",
        "total_memory_usage_mb", "num_cores", "num_active_tasks"
    ]
    result = {field: data.get(field) for field in target_fields}

    # Строим матрицу смежности
    tasks = data.get("tasks", [])

    all_task_ids = set()
    for task in tasks:
        all_task_ids.add(task["task_id"])
        for adj in task.get("adjacent_tasks", []):
            all_task_ids.add(adj["task_id"])

    task_ids = sorted(list(all_task_ids))
    id_to_idx = {tid: i for i, tid in enumerate(task_ids)}
    size = len(task_ids)

    adj_matrix = [[0.0] * size for _ in range(size)]

    for task in tasks:
        src_idx = id_to_idx[task["task_id"]]
        for adj in task.get("adjacent_tasks", []):
            tgt_id = adj["task_id"]
            if tgt_id in id_to_idx:
                tgt_idx = id_to_idx[tgt_id]
                adj_matrix[src_idx][tgt_idx] = adj["bandwidth_mbps"]

    result["task_ids"] = task_ids
    result["adjacency_matrix"] = adj_matrix
    return result


def draw_directed_graph(task_ids, adj_matrix, save_path="graph.png"):
    """
    Визуализирует ориентированный взвешенный граф.
    Вес ребра = bandwidth_mbps, толщина линии пропорциональна весу.
    """
    G = nx.DiGraph()

    # Добавляем все узлы
    G.add_nodes_from(task_ids)

    # Добавляем взвешенные рёбра
    for i, src in enumerate(task_ids):
        for j, tgt in enumerate(task_ids):
            weight = adj_matrix[i][j]
            if weight > 0:  # Только существующие связи
                G.add_edge(src, tgt, weight=weight)

    # Позиционирование узлов (spring layout с фиксированным seed для воспроизводимости)
    pos = nx.spring_layout(G, k=2, iterations=50, seed=42)

    # Подготовка к отрисовке
    plt.figure(figsize=(14, 10))

    # Цвета и размеры узлов
    node_colors = ['#66b3ff' if 'node-1' in n else '#99ff99' for n in G.nodes()]
    node_sizes = [2000 + 500 * len(n) for n in G.nodes()]

    # Рисуем узлы
    nx.draw_networkx_nodes(G, pos,
                           node_color=node_colors,
                           node_size=node_sizes,
                           edgecolors='black',
                           linewidths=1.5)

    # Рисуем подписи узлов
    nx.draw_networkx_labels(G, pos,
                            font_size=9,
                            font_weight='bold',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.7))

    # Веса рёбер для подписей и толщины
    edge_weights = [G[u][v]['weight'] for u, v in G.edges()]
    edge_widths = [0.5 + w / 30 for w in edge_weights]  # Масштабируем толщину

    # Рисуем рёбра со стрелками
    nx.draw_networkx_edges(G, pos,
                           arrowstyle='->',
                           arrowsize=20,
                           width=edge_widths,
                           edge_color='gray',
                           connectionstyle='arc3,rad=0.1')  # Изогнутые стрелки для наглядности

    # Подписи весов на рёбрах
    edge_labels = {(u, v): f"{G[u][v]['weight']:.1f} Mbps" for u, v in G.edges()}
    nx.draw_networkx_edge_labels(G, pos,
                                 edge_labels=edge_labels,
                                 font_size=8,
                                 bbox=dict(boxstyle='round,pad=0.2', facecolor='yellow', alpha=0.5))

    # Оформление
    plt.title("Ориентированный граф задач (вес = bandwidth_mbps)",
              fontsize=16, fontweight='bold', pad=20)
    plt.axis('off')
    plt.tight_layout()

    # Сохраняем и показываем
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"✅ Граф сохранён в файл: {save_path}")
    plt.show()


def print_results(result):
    print("=" * 50)
    print("Метрики ноды")
    print("=" * 50)
    for k, v in result.items():
        if k not in ("task_ids", "adjacency_matrix"):
            print(f"{k:<25}: {v}")

    print("\n Матрица смежности (bandwidth_mbps)")
    print("(Строки = источник → Столбцы = приёмник)")
    print("-" * 50)

    task_ids = result["task_ids"]
    matrix = result["adjacency_matrix"]

    if not task_ids:
        print("Нет данных для построения матрицы")
        return

    max_id_len = max(len(str(tid)) for tid in task_ids)

    # Заголовки
    header = " " * (max_id_len + 2) + " | " + " | ".join(f"{str(tid):<{max_id_len}}" for tid in task_ids)
    print(header)
    print("-" * len(header))

    # Строки матрицы
    for i, row in enumerate(matrix):
        row_vals = " | ".join(f"{val:>{max_id_len}.1f}" for val in row)
        print(f"{str(task_ids[i]):<{max_id_len}} | {row_vals}")


if __name__ == "__main__":
    FILE_PATH = "report_20260527_131829.json"

    try:
        print(" Чтение и обработка данных...")
        res = extract_metrics_and_build_matrix(FILE_PATH)

        # Вывод текстовой информации
        print_results(res)

        # Визуализация графа
        print("\n Построение графа...")
        draw_directed_graph(res["task_ids"], res["adjacency_matrix"])

    except FileNotFoundError:
        print(f" Ошибка: файл '{FILE_PATH}' не найден.")
    except ImportError as e:
        print(f" Не установлены необходимые библиотеки: {e}")
        print(" Установите их командой:\n   pip install networkx matplotlib")
    except Exception as e:
        print(f" Ошибка: {e}")
        import traceback

        traceback.print_exc()
