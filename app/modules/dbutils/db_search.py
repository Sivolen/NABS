from sqlalchemy import text
from app import db, logger

def search_in_db(request_data: str, user_id: int) -> list:
    """
    Поиск по конфигам с учётом прав пользователя.
    Возвращает список результатов (каждая запись – словарь).
    """
    if not isinstance(request_data, str) or not request_data:
        logger.info("Search request is empty")
        return []
    if not isinstance(user_id, int) or user_id is None:
        logger.info("Invalid user ID")
        return []

    try:
        # Увеличим буфер сниппета до 250 символов, но обрежем по словам позже
        # Используем ILIKE для регистронезависимого поиска (PostgreSQL)
        # Добавляем LIMIT 100, чтобы не перегружать страницу
        sql = text("""
            SELECT configs.id, device_ip, configs.device_id, timestamp,
                   substring(device_config,
                             greatest(strpos(device_config, :search) - 120, 1),
                             250) AS config_snippet
            FROM configs
            LEFT JOIN associating_device ON associating_device.device_id = configs.device_id
            LEFT JOIN group_permission ON group_permission.user_group_id = associating_device.user_group_id
            WHERE group_permission.user_id = :user_id
              AND device_config ILIKE '%' || :search || '%'
            GROUP BY configs.device_id, configs.id
            ORDER BY timestamp DESC
            LIMIT 100
        """)
        rows = db.session.execute(sql, {
            "search": request_data,
            "user_id": user_id
        }).fetchall()

        results = []
        for idx, row in enumerate(rows, start=1):
            snippet = row.config_snippet or ""
            # Разбиваем на строки и убираем пустые
            snippet_lines = [line for line in snippet.splitlines() if line.strip()]
            # Если сниппет пустой, попробуем взять первые 5 строк конфига? Можно оставить как есть
            results.append({
                "html_element_id": idx,
                "config_id": row.id,
                "device_id": row.device_id,
                "device_ip": row.device_ip,
                "timestamp": row.timestamp,
                "config_snippet": snippet_lines
            })
        return results

    except Exception as e:
        logger.error(f"Search error: {e}")
        return []