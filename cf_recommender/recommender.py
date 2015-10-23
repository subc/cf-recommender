# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals
from collections import defaultdict
from .timeit import timeit
from .repository import Repository
from .settings import DEFAULT_SETTINGS

DEFAULT_TAG = 'default'


class Recommender(object):
    _r = None

    def __init__(self, settings):
        DEFAULT_SETTINGS.update(settings)
        self.settings = DEFAULT_SETTINGS

    @property
    def repository(self):
        if self._r is None:
            self._r = Repository(self.settings)
        return self._r

    @property
    def is_recommendation_real_time_update(self):
        return self.settings.get('recommendation').get('recommendation_real_time_update')

    def get(self, goods_id, count=None):
        return self.repository.get(goods_id, count=count)

    @timeit
    def update(self, goods_id):
        """
        update recommendation list
        :param goods_id: str
        """
        self.repository.update_recommendation(goods_id)
        return

    def register(self, goods_id, tag=DEFAULT_TAG):
        """
        register goods_id
        :param goods_id: int
        :param tag: str
        :rtype : None
        """
        return self.repository.register(goods_id, tag)

    @timeit
    def like(self, user_id, goods_ids):
        """
        record user like history
        about: 100ms * count(goods_ids)
        :param user_id: str
        :param goods_ids: list[int]
        :rtype : None
        """
        assert type(goods_ids) == list

        # like
        self.repository.like(user_id, goods_ids)

        # create index
        self.repository.update_index(user_id, goods_ids)

        # update recommendation
        if not self.is_recommendation_real_time_update:
            return
        for goods_id in goods_ids:
            self.repository.update_recommendation(goods_id)  # RealTime update

        return

    def get_all_goods_ids(self):
        """
        all registered goods ids
        WARNING!! this is heavy method about 1-100sec
        :rtype : list[int]
        """
        return self.repository.get_all_goods_ids()

    @timeit
    def update_all(self, proc=1, scope=(1, 1)):
        """
        update all recommendation

        :param int proc: Multiprocess thread count
        :param tuple(list[int, int]) scope: update scope [start, partition count]
        :rtype : None
        """
        all_goods_ids = self.get_all_goods_ids()
        for goods_id in all_goods_ids:
            self.repository.update_recommendation(goods_id)

    @timeit
    def recreate_all_index(self):
        """
        update all index

        WARNING!! this method use high memory
        100,000 user >> memory 100MByte
        1,000,000 user >> memory 1GByte
        10,000,000 user >> memory 10GByte

        :rtype : None
        """
        # get all goods ids
        all_goods_ids = self.get_all_goods_ids()

        # get all user's like history
        all_users_like_history = self.get_all_users_like_history()

        # marge user's like history by goods_id
        for tag in all_users_like_history:
            hist = defaultdict(list)
            users_like_history = all_users_like_history.get(tag)
            for user_id in users_like_history:
                for goods_id in users_like_history[user_id]:
                    hist[goods_id] += [user_id]

            # recreate index
            for goods_id in all_goods_ids:
                if goods_id in hist:
                    self.repository.recreate_index(goods_id, hist[goods_id])

    def get_all_users_like_history(self):
        """
        :rtype : dict{str: list[int]}
        :rtype dict{str: dict{str: list[str]}} : dict{user_id: dict{tag:list[goods_id]}}
        """
        # get all user like history keys
        all_user_keys = self.repository.get_all_user_ids()

        result = defaultdict(dict)
        for key in all_user_keys:
            tag, user_id = Repository.get_user_and_key_from_redis_key(key)
            result[tag].update({user_id: self.repository.get_user_like_history(user_id, tag)})
        return result