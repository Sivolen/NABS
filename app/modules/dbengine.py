import psycopg2
from config import DBHost, DBUser, DBPassword, DBPort, DBName


def execute_query(query: str):
    conn = psycopg2.connect(
        host=DBHost, database=DBName, user=DBUser, password=DBPassword, port=DBPort
    )
    cur = conn.cursor()
    cur.execute(query)
    result = cur.fetchall()
    conn.close()
    return result


def get_device_id(ipaddress):
    sql_query = f"""
        select id 
        from devices where devices.device_ip = '{ipaddress}'
        """
    result = execute_query(query=sql_query)[0][0]
    return result if execute_query(query=sql_query) is not None else None
