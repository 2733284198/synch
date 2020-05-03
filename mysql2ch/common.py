import datetime
import json
import logging

import dateutil.parser
from decimal import Decimal

import redis
from kafka import KafkaAdminClient
from kafka.admin import NewPartitions

from mysql2ch import settings

logger = logging.getLogger('mysql2ch.common')

CONVERTERS = {
    'date': dateutil.parser.parse,
    'datetime': dateutil.parser.parse,
    'decimal': Decimal,
}


def complex_decode(xs):
    if isinstance(xs, dict):
        ret = {}
        for k in xs:
            ret[k.decode()] = complex_decode(xs[k])
        return ret
    elif isinstance(xs, list):
        ret = []
        for x in xs:
            ret.append(complex_decode(x))
        return ret
    elif isinstance(xs, bytes):
        return xs.decode()
    else:
        return xs


class JsonEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return {'val': obj.strftime('%Y-%m-%d %H:%M:%S'), '_spec_type': 'datetime'}
        elif isinstance(obj, datetime.date):
            return {'val': obj.strftime('%Y-%m-%d'), '_spec_type': 'date'}
        elif isinstance(obj, Decimal):
            return {'val': str(obj), '_spec_type': 'decimal'}
        else:
            return super().default(obj)


def object_hook(obj):
    _spec_type = obj.get('_spec_type')
    if not _spec_type:
        return obj

    if _spec_type in CONVERTERS:
        return CONVERTERS[_spec_type](obj['val'])
    else:
        raise TypeError('Unknown {}'.format(_spec_type))


def init_partitions():
    client = KafkaAdminClient(
        bootstrap_servers=settings.KAFKA_SERVER,
    )
    try:
        client.create_partitions(topic_partitions={
            settings.KAFKA_TOPIC: NewPartitions(total_count=len(settings.PARTITIONS.keys()))
        })
    except Exception as e:
        logger.warning(f'init_partitions error:{e}')


def parse_mysql_ddl_2_ch(schema: str, query: str):
    """
    parse ddl query
    :param schema:
    :param query:
    :return:
    """
    query = query.replace('not null', '').replace('null', '')
    query_list = list(query)
    space = 'table '
    query_list.insert(query.index(space) + len(space), f'{schema}.')
    if 'add' in query:
        space = 'add '
        query_list.insert(query.index(space) + len(space), ' column')
    return ''.join(query_list)


if settings.UI_ENABLE:
    pool = redis.ConnectionPool(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.UI_REDIS_DB,
                                password=settings.REDIS_PASSWORD, decode_responses=True)
    redis_ins = redis.StrictRedis(connection_pool=pool)


def insert_into_redis(prefix, schema: str, table: str, num: int):
    """
    insert producer or consumer num
    :param prefix:
    :param schema:
    :param table:
    :param num:
    :return:
    """
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    key = f'ui:{prefix}:{now}'
    exists = redis_ins.exists(key)
    redis_ins.hincrby(key, f'{schema}:{table}', num)
    if not exists:
        redis_ins.expire(key, settings.UI_MAX_NUM * 60)
