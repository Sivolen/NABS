# Локальная разработка NABS на Windows

Проект: C:\progects\NABS. Python 3.12 в `venv`.

## Запуск и остановка

```powershell
cd C:\progects\NABS
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
powershell -ExecutionPolicy Bypass -File .\stop-local.ps1
```

Интерфейс: http://127.0.0.1:5055. После изменения Python-кода перезапустите приложение.
Оба процесса запускаются локально, без системных служб и автозапуска.
Планировщик резервирования отдельно не запускается.

## Конфигурация и данные

- `config.py`: локальные настройки, ключи шифрования и пароль БД; исключён из Git.
- `.local/pgdata`: отдельный кластер PostgreSQL, адрес 127.0.0.1:55432, база и пользователь `nabs`.
- `.local/admin-login.txt`: реквизиты первого входа в локальную копию.
- `.local/web.stderr.log`, `.local/web.stdout.log`, `.local/postgresql.log`: журналы запуска.
- `.local/` исключена из Git через `.gitignore`.

Для работы с БД используйте данные из `config.py`. Не удаляйте и не пересоздавайте ключ
CREDENTIALS_ENCRYPTION_KEY после сохранения паролей устройств.

## Зависимости

`requirements.txt` — исходный список проекта. `requirements-windows.txt` — отдельный
список для локального Windows-окружения. Gunicorn, supervisor и jeepney исключены:
для локального веб-сервера используется Flask, без Linux-служб.
Установленные версии сохранены в `requirements-windows.lock.txt` (локальный файл).

```powershell
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe -m flask --app app db migrate -m "describe change"
.\venv\Scripts\python.exe -m flask --app app db upgrade
```

Для подключения реальных устройств добавьте их через интерфейс вместе с учётными данными.
Резервирование и восстановление на реальном оборудовании при подготовке окружения не проверялись.

## Особенности этого развёртывания

Используется существующая ветка `dev` (tracking `origin/dev`).
Для первичной инициализации: `.\venv\Scripts\python.exe init-local-db.py`.
Python взят из установленного runtime Codex; `venv` привязан к этому Python.
Для автономного переноса на другой компьютер окружение нужно пересоздать.

Для новой PostgreSQL БД исправлен PK модели Devices: только `id` вместо
`(id, device_ip)`. Применена локальная миграция `local_device_pk`.
Также выбраны совместимые сборки Brotli 1.1.0, regex 2024.11.6 и psutil 6.1.1.
Основной requirements.txt не менялся. Подробности в docs/UI-AUDIT-2026-11-16.md.

Для повторения браузерного аудита дополнительно установлен Playwright; его
сценарий и результаты находятся в `.local`, это не зависимость приложения.


## Обновление до NABS 2.9.0

Перед запуском новой версии примените миграцию. Установщик NABS генерирует и
применяет её при обновлении. На существующем локальном стенде команды такие:

~~~powershell
.\venv\Scripts\python.exe -m flask --app app db migrate -m "Upgrade to NABS 2.9.0"
.\venv\Scripts\python.exe -m flask --app app db upgrade
~~~

Миграция добавляет таблицу фоновых задач и расширяет поле команд кастомного
профиля. Старые профили читаются автоматически, их последняя непустая команда
используется для чтения конфига.

Настройка BACKUP_WORKERS в config.py задаёт число потоков массового опроса
(по умолчанию 20). Веб-процессы и планировщик одной установки должны иметь
доступ к общему каталогу logs/backup-locks для блокировки параллельного опроса.

Объединение реализации одиночного и массового бэкапа отложено на следующий этап.
