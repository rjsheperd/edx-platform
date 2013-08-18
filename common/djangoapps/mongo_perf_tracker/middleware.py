"""
Provide a means to aggregate and store MongoDB related performance in our product
"""
import threading
import logging
from xmodule.contentstore.content import XASSET_LOCATION_TAG
from django.conf import settings

_mongo_perf_tracker_threadlocal = threading.local()
_mongo_perf_tracker_threadlocal.data = {}

# counter to keep track of how many requests we've processed. This is used to
# keer track of when we need to flush out internal buffers out to some persistence
# layer
trackable_requests_processed = 0

# global object which retains a mapping of URL to DB performance information
db_stats_per_url = {}

log = logging.getLogger("lms.mongo_perf_tracker")


class MongoPerfTracker(object):
    """
    Implements Django middleware object which manages the lifetime of
    the performance tracker for our MongoDB store provider
    """
    def get_perf_tracker_data(self):
        """
        Returns the dictionary that is in the threadlocal
        """
        return _mongo_perf_tracker_threadlocal.data

    def set_perf_tracker_data_entry(self, key, value):
        """
        Sets a piece of tracking data
        """
        _mongo_perf_tracker_threadlocal.data[key] = value

    def increment_perf_tracker_counter(self, key):
        """
        Increases a counter by one
        """
        if key in _mongo_perf_tracker_threadlocal.data:
            _mongo_perf_tracker_threadlocal.data[key] = _mongo_perf_tracker_threadlocal.data[key] + 1
        else:
            _mongo_perf_tracker_threadlocal.data[key] = 1

    def add_to_float_perf_tracker_counter(self, key, increment_float):
        """
        Adds a number to a tracking element which is a float
        """
        if key in _mongo_perf_tracker_threadlocal.data:
            _mongo_perf_tracker_threadlocal.data[key] = _mongo_perf_tracker_threadlocal.data[key] + increment_float
        else:
            _mongo_perf_tracker_threadlocal.data[key] = increment_float

    def _is_trackable_path(self, request):
        """
        Returns whether this path is something we want to set up stats gathering for
        """
        # don't track requests for GridFS hosted assets
        if request.path.startswith('/' + XASSET_LOCATION_TAG + '/'):
            return False

        # don't track requests for things in /static/...
        if request.path.startswith('/static/'):
            return False

        # don't track POST-backs, for now at least
        if request.method in ('POST', 'PUT'):
            return False

        return True

    def clear_perf_tracker_data(self):
        """
        Resets all data in our threadlocal
        """
        _mongo_perf_tracker_threadlocal.data = {}

    def process_request(self, request):
        """
        Middleware entry point that is called on every received thread
        """
        self.clear_perf_tracker_data()

        return None

    def process_response(self, request, response):
        """
        Django middleware entry point that is called on every response sent back to client
        """
        global trackable_requests_processed, db_stats_per_url
        if self._is_trackable_path(request):
            # copy over any stats gathered in this request and put in the global dictionary
            # to get written out on a periodic basis

            set_entry = True

            # take what the overwrite key should be from settings, if defined
            overwrite_key = getattr(settings, 'MONGO_PERF_TRACKER_OVERWITE_KEY', None)

            # first see if we have an entry for this path, if so see if an overwrite key
            # has been specified so that we can use that value to compare to what exists
            # this can be used to implement a high-water mark
            if request.path in db_stats_per_url and overwrite_key:
                existing_level = db_stats_per_url[request.path].get(overwrite_key, 0)
                new_level = _mongo_perf_tracker_threadlocal.data.get(overwrite_key, 0)
                set_entry = existing_level < new_level

            if set_entry and len(_mongo_perf_tracker_threadlocal.data.keys()) > 0:
                db_stats_per_url[request.path] = _mongo_perf_tracker_threadlocal.data

            trackable_requests_processed = trackable_requests_processed + 1

            dump_limit = getattr(settings, 'MONGO_PERF_DUMP_AFTER_N_REQUESTS', 1)

            if trackable_requests_processed > dump_limit:
                # Note, we use WARN level so they don't get filtered out in the logs
                log.warning('mongo_db_stats dump = {0}'.
                            format(db_stats_per_url))
                trackable_requests_processed = 0
                db_stats_per_url = {}

        self.clear_perf_tracker_data()
        return response
