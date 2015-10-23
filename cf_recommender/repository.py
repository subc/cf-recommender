# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
from collections import defaultdict
from redis import Redis
from cf_recommender.timeit import timeit
from .settings import DEFAULT_SETTINGS

# redis key
PREFIX = 'CF_RECOMMENDER'
GOODS_TAG_BASE = '%s:GOODS:TAG:{}' % PREFIX
USER_LIKE_HISTORY_BASE = '%s:USER:LIKE-HISTORY:{}:{}' % PREFIX
INDEX_GOODS_USER_BASE = '%s:INDEX:GOODS-USER-LIKE-HISTORY:{}:{}' % PREFIX
GOODS_ALL = '%s:GOODS:ALL' % PREFIX
GOODS_RECOMMENDATION = '%s:GOODS:RECOMMENDATION:{}:{}' % PREFIX

# redis TTL
PERSISTENT_SEC = 3600 * 24 * 365 * 1000


class GetALLMixin(object):
    def get_goods_all(self):
        return self.client.lrange(GOODS_ALL, 0, -1)

    def add_goods(self, goods_ids):
        goods_ids = [str(goods_id) for goods_id in goods_ids]
        self.client.rpush(GOODS_ALL, *goods_ids)
        return


class Repository(object):
    _cli = None
    _CACHE_GOODS_TAG = {}  # class cache

    def __init__(self, settings):
        DEFAULT_SETTINGS.update(settings)
        self.settings = DEFAULT_SETTINGS

    @classmethod
    def get_key_goods_tag(cls, goods_id):
        return GOODS_TAG_BASE.format(str(goods_id)).upper()

    @classmethod
    def get_key_user_like_history(cls, tag, user_id):
        return USER_LIKE_HISTORY_BASE.format(tag, user_id).upper()

    @classmethod
    def get_key_index_goods_user_like_history(cls, tag, goods_id):
        return INDEX_GOODS_USER_BASE.format(tag, str(goods_id)).upper()

    @classmethod
    def get_key_goods_recommendation(cls, tag, goods_id):
        return GOODS_RECOMMENDATION.format(tag, str(goods_id)).upper()

    @classmethod
    def get_user_and_key_from_redis_key(cls, key):
        """
        >>> key = "CF_RECOMMENDER:USER:LIKE-HISTORY:BOOK:035A6959-B024-43CD-9FE9-5BCD4A0E5A92"
        >>> r = key.split(':')
        >>> r[3:]
        ['BOOK', '035A6959-B024-43CD-9FE9-5BCD4A0E5A92']
        :rtype : list[str]
        """
        r = key.split(':')
        return r[3:]

    @property
    def client(self):
        if self._cli is None:
            self._cli = Redis(host=self.settings.get('redis').get('host'),
                              port=self.settings.get('redis').get('port'),
                              db=self.settings.get('redis').get('db'),)
        return self._cli

    @property
    def expire(self):
        return self.settings.get('expire')

    def touch(self, key):
        self.client.expire(key, self.expire)

    def get(self, goods_id, count=None):
        """
        get recommendation list
        :param goods_id: str
        :param count: int
        :rtype list[str]: list of recommendation goods
        """
        if not count:
            count = self.settings.get('recommendation_count')
        tag = self.get_tag(goods_id)
        key = Repository.get_key_goods_recommendation(tag, goods_id)
        return self.client.zrevrange(key, 0, count - 1)

    def get_goods_tag(self, goods_id):
        tag = Repository._CACHE_GOODS_TAG.get(goods_id)
        if tag is None:
            tag = self.get_tag(goods_id)
            Repository._CACHE_GOODS_TAG[goods_id] = tag
        return tag

    def get_tag(self, goods_id):
        key = self.get_key_goods_tag(goods_id)
        return self.client.get(key)

    def goods_exist(self, goods_id):
        """
        already registered goods
        :param : str
        :rtype : bool
        """
        return bool(self.client.get(Repository.get_key_goods_tag(goods_id)))

    def register(self, goods_id, tag):
        """
        register goods_id
        :param goods_id: str
        :param tag: str
        :rtype : None
        """
        key = Repository.get_key_goods_tag(goods_id)
        return self.client.setex(key, tag, PERSISTENT_SEC)

    def like(self, user_id, goods_ids):
        """
        record user like history
        :param user_id: str
        :param goods_ids: list[str]
        :rtype : None
        """
        goods_group = self.categorized(goods_ids)
        for tag in goods_group:
            key = Repository.get_key_user_like_history(tag, user_id)
            _goods_ids = goods_group[tag]
            if _goods_ids:
                self.client.rpush(key, *_goods_ids)
        return

    def categorized(self, goods_ids):
        """
        :param dict{str: list[str]} goods_ids: dict{tag: list[goods_id]}
        :return:
        """
        result = defaultdict(list)
        for goods_id in goods_ids:
            result[self.get_tag(str(goods_id))] += [str(goods_id)]
        return result

    @timeit
    def update_recommendation(self, goods_id):
        tag = self.get_tag(goods_id)

        # get user
        users = self.get_goods_like_history(goods_id)

        # calc recommendation
        recommendation_list = []
        for user_id in users:
            recommendation_list += self.get_user_like_history(user_id, tag)

        result = defaultdict(int)
        for _tmp_goods_id in recommendation_list:
            if _tmp_goods_id == goods_id:
                continue
            result[_tmp_goods_id] += 1

        # set sorted set of redis
        key = Repository.get_key_goods_recommendation(tag, goods_id)
        self.client.delete(key)
        for _tmp_goods_id in result:
            self.push_recommendation(key, _tmp_goods_id, result[_tmp_goods_id])
        return

    def update_index(self, user_id, goods_ids):
        """
        update goods index
        :param user_id: str
        :param goods_ids: list[str]
        :rtype : None
        """
        for goods_id in goods_ids:
            tag = self.get_tag(goods_id)
            key = Repository.get_key_index_goods_user_like_history(tag, goods_id)
            self.client.rpush(key, user_id)
        return

    def get_goods_like_history(self, goods_id, count=None):
        """
        :param goods_id: str
        :param count: int
        :rtype list[str]: liked users of goods
        """
        if not count:
            count = self.settings.get('recommendation').get('goods_like_history_search_depth')
        tag = self.get_tag(goods_id)
        key = Repository.get_key_index_goods_user_like_history(tag, goods_id)
        return self.client.lrange(key, -1 * count, -1)

    def get_all_goods_ids(self):
        """
        all registered goods ids
        :rtype : list[str]
        """
        key = Repository.get_key_goods_tag('*')
        result = self.client.keys(key)
        del_word = GOODS_TAG_BASE[0:len(GOODS_TAG_BASE)-2]
        return map(lambda x: x.replace(del_word, ''), result)

    def get_all_user_ids(self):
        """
        all user ids
        :rtype : list[str]
        """
        key = Repository.get_key_user_like_history('*', '*')
        return self.client.keys(key)

    def get_user_like_history(self, user_id, tag, count=None):
        """
        :param user_id: str or unicode
        :rtype list[str]: goods_ids of user
        """
        if not count:
            count = self.settings.get('recommendation').get('user_history_count')
        key = Repository.get_key_user_like_history(tag, user_id)
        result = self.client.lrange(key, -1 * count, -1)
        if not result:
            return []
        return result

    def push_recommendation(self, key, goods_id, value):
        """
        update recommendation sorted set
        :param str goods_id:
        :param str value: count
        """
        self.client.zadd(key, goods_id, int(value))
        self.touch(key)

    def recreate_index(self, goods_id, user_ids):
        """
        recreate goods_id liked users index
        :param goods_id: str
        :param user_ids: list[str or unicode]
        :rtype : None
        """
        if not user_ids:
            return
        tag = self.get_tag(goods_id)
        key = Repository.get_key_index_goods_user_like_history(tag, goods_id)
        # print '@@@@@', key, user_ids
        # delete list
        self.client.delete(key)
        # update list
        self.client.rpush(key, *user_ids)
        return