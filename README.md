# Transport Delay Predictor

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Потоковый ML-прогноз задержек городского транспорта: бинарный поток телеметрии **NDTP** →
GPS-мэтчинг с расписанием → **CatBoost** → онлайн-инференс → BI-дашборд диспетчера.
Горизонт прогноза — **10–15 минут до события**: время опоздания, причина и участок маршрута
срабатывают до сбоя, а не постфактум.

## Возможности

- **Приём потока NDTP** (NPL/NPH, CRC-16/Modbus, навигационная ячейка `G6CellNav00`) по TCP,
  устойчивость к мусору в потоке и обрывам соединения;
- **Мэтчинг с расписанием** — восстановление прохождения остановок по треку, оценка фактического
  отклонения от графика; **HMM map matching** на графе дорог OSM: участок застревания определяется
  по имени улицы;
- **Прогноз задержки** на первой остановке с плановым прибытием в окне `(T+10; T+15]` мин:
  CatBoost поверх 69 признаков (отклонение, скорости по окнам, доля простоя, темп), строгая
  антиутечка (только телеметрия `event_time ≤ T`), LOO-приоры остановок;
- **BI-дашборд диспетчера** (MapLibre): карта маршрутной сети с ТС-стрелками по курсу, риск-цвета
  прогноза опоздания, карточка инцидента (прогноз, причина, участок, рекомендация), What-if
  сценарии (резервные ТС, сокращение стоянки), обновления по WebSocket;
- **Эксплуатация**: три сервиса в Docker, холодный старт за секунды, деградация при обрыве
  потока (последние данные + флаг вместо падения), ONNX-экспорт модели для ускоренного инференса.

## Архитектура

```
replay датасета / эмулятор NDTP
        │  TCP :9201 (NDTP)
        ▼
ML-ядро: парсер NDTP, признаки, CatBoost-инференс   (API :8100)
        │
        ▼
Backend: FastAPI, REST + WebSocket, оркестрация      (API :8000)
        │
        ▼
BI-дашборд: MapLibre, алерты, карточка инцидента     (статика /dashboard)
```

Модули независимы и общаются по сети; ML-ядро масштабируется отдельно от backend.

## Быстрый старт

Нужен Docker. Исторический датасет телеметрии кладётся в `./dataset` (см. «Формат данных»);
без него поднимается всё, кроме сервиса `replay` — поток можно подать своим NDTP-эмулятором.

```bash
docker compose up --build
```

- **Дашборд:** http://localhost:8000/dashboard/index.html (обновление в реальном времени)
- **Swagger:** http://localhost:8000/docs (backend), http://localhost:8100/docs (ml-core)
- **NDTP-вход для внешнего потока:** TCP :9201

Сервис `replay` автоматически превращает CSV датасета в живой NDTP-поток (окно 07:20–11:20,
ускорение ×600). Управление контуром — см. `docker-compose.yml`.

## Формат данных

Датасет не входит в репозиторий: подойдёт любой экспорт телеметрии в CSV (разделитель `,`, UTF-8).

| `traffic.csv` | |
|---|---|
| `tr_id`, `unit_id` | ID транспортного средства и бортового терминала |
| `event_time` | время телеметрии |
| `lat`, `lon`, `alt` | координаты и высота |
| `speed`, `heading` | скорость (км/ч), курс (°) |
| `location_valid` | достоверность координат |

| `schedule.csv` | |
|---|---|
| `tt_action_item_id` | ID планового прибытия на остановку |
| `tr_id` | ID ТС |
| `time_begin` | плановое время прибытия |
| `time_fact_begin` | фактическое время (только обучающая выборка) |
| `geom` | точка остановки |

Размеченные прогнозные точки — CSV с колонками `sample_id, tr_id, T, target_stop_id,
target_time_begin, cur_dev_s` (+ `target_delay_s, target_class` в обучающей выборке).
`cur_dev_s` — отклонение на последней пройденной остановке: в обучающей выборке берётся из
разметки, в живом потоке оценивается по GPS (это и делает стриминг честным).

## Метрики

Оценка на скрытом эталоне (hold-out), MAE прогнозируемой задержки:

| Модель | MAE, с |
|---|---|
| «задержки нет» | 103.3 |
| экстраполяция текущего отклонения (baseline) | 93.4 |
| CatBoost + подсказка отклонения (офлайн) | **40.9** |
| стриминг без подсказок, только GPS | **42.1** |

Числа воспроизводятся: `python tools/stream_eval.py --split test --model
data/gt/models/catboost_stream.cbm --use-est-dev`. Латентность инференса —
`python tools/bench_latency.py` (единицы–десятки мс на ТС при бюджете в 1–2 с).

## ML-пайплайн

| Шаг | Инструмент |
|---|---|
| признаки (антиутечка `event_time ≤ T`) | `tools/gt_features.py` |
| приоры остановок (LOO) | `tools/gt_features.py`, `mtp/gt_priors.py` |
| обучение CatBoost | `tools/gt_train.py`, `tools/gt_train_final.py` |
| стриминг-фичи и модель (без подсказок) | `tools/gt_stream_features.py`, `tools/gt_train_stream.py` |
| прогноз по CSV | `tools/gt_predict.py` |
| ONNX-экспорт и бенчмарк | `tools/export_onnx.py` |
| PyTorch GRU + бленд (эксперимент) | `tools/gt_gru.py` |
| граф дорог OSM для маршрутов | `tools/build_routes_osm.py` |

## Подача потока NDTP

Стандартный эмулятор бортовых терминалов подключается к NDTP-входу `:9201`:

```bash
docker load -i ndtp-telemetry-emulator.tar
docker run --rm -p 18080:18080 --add-host=host.docker.internal:host-gateway \
  --name ndtp-emu ndtp-telemetry-emulator:1.0

curl -X POST http://localhost:18080/api/config \
  -H 'Content-Type: application/json' \
  -d '{"targetHost":"host.docker.internal","targetPort":9201,
       "units":[{"unitId":1166336,"intervalMs":5000,"autoGenerate":true,"cells":[]}]}'
```

Остановить эмуляцию: `POST /api/config` с `"units": []`. Идентификаторы `unitId` связываются с
`tr_id` по `unit_id` из `traffic.csv`; время пакетов «сегодняшнего» потока автоматически
выравнивается на день расписания.

## Тесты и документация

```bash
pytest                        # протокол NDTP, GPS-фильтры, HMM-мэтчинг, привязка потока
python tools/gen_docs.py      # PyDoc → docs/pydoc/
```

Swagger генерируется FastAPI автоматически (`/docs` у обоих сервисов).

## Лицензия

[MIT](LICENSE) · by [@strmcrown](https://github.com/vikt-sav)
